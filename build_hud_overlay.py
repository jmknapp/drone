#!/usr/bin/env python3
"""
Parse DJI SRT telemetry and build an ASS (Advanced Substation Alpha) overlay
for a green HUD-style burn-in on the video.
"""
import argparse
import math
import re
import sys
from pathlib import Path

from velocity_filters import apply_velocity_filter, apply_vertical_velocity_filter

M_TO_FT = 3.28084
MPS_TO_MPH = 2.23694

# Meters per degree at equator; longitude scale varies with latitude
M_PER_DEG_LAT = 111320.0


def latlon_to_relative_str(
    lat: float, lon: float, ref_lat: float, ref_lon: float, imperial: bool
) -> str:
    """Return relative N/E offset from reference point using lat/lon approximation."""
    dn = (lat - ref_lat) * M_PER_DEG_LAT
    de = (lon - ref_lon) * M_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    if imperial:
        dn *= M_TO_FT
        de *= M_TO_FT
        unit = "ft"
    else:
        unit = "m"
    return f"Relative: {dn:+.1f}{unit} N, {de:+.1f}{unit} E"


def quat_to_euler_deg(w: float, x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert quaternion (w,x,y,z) to roll, pitch, yaw in degrees."""
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def haversine_m(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    """Horizontal distance in meters between two WGS84 points."""
    R = 6371000.0  # Earth radius in m
    a = math.radians(lat1_deg)
    b = math.radians(lat2_deg)
    dlat = math.radians(lat2_deg - lat1_deg)
    dlon = math.radians(lon2_deg - lon1_deg)
    x = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(1.0, x)))


def parse_srt_block(block: str) -> dict | None:
    """Parse one SRT subtitle block; return dict with start, end, and telemetry."""
    lines = block.strip().split("\n")
    if len(lines) < 5:
        return None
    match = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})", lines[1])
    if not match:
        return None
    h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
    start_s = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
    end_s = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
    timestamp_str = lines[3].strip()
    data_line = lines[4]

    def get(key: str) -> str:
        m = re.search(rf"\[{re.escape(key)}:\s*([^\]]+)\]", data_line)
        return m.group(1).strip() if m else ""

    # abs_alt and rel_alt are in the same bracket: [rel_alt: 0.000 abs_alt: 265.118]
    abs_alt = ""
    m = re.search(r"abs_alt:\s*([\d.]+)", data_line)
    if m:
        abs_alt = m.group(1)
    rel_alt = ""
    m = re.search(r"rel_alt:\s*([\d.]+)", data_line)
    if m:
        rel_alt = m.group(1)
    if not rel_alt:
        rel_alt = "0"

    lat = get("latitude")
    lon = get("longitude")
    iso = get("iso")
    shutter = get("shutter")
    fnum = get("fnum")
    ev = get("ev")

    # Gimbal: use pp_current (actual pose), fallback to pp_target; pp_limit_ratio
    pp_current = get("pp_current")
    pp_target = get("pp_target")  # e.g. "0.159, -0.000, -0.000, -0.987"
    pp_limit_ratio = get("pp_limit_ratio")
    pp_quat = pp_current or pp_target

    quat_w = quat_x = quat_y = quat_z = None
    if pp_quat:
        parts = [p.strip() for p in pp_quat.split(",")]
        if len(parts) == 4:
            try:
                quat_w, quat_x, quat_y, quat_z = (float(p) for p in parts)
            except ValueError:
                pass

    return {
        "start": start_s,
        "end": end_s,
        "timestamp": timestamp_str,
        "lat": lat,
        "lon": lon,
        "abs_alt": abs_alt,
        "rel_alt": rel_alt,
        "iso": iso,
        "shutter": shutter,
        "fnum": fnum,
        "ev": ev,
        "pp_limit_ratio": pp_limit_ratio,
        "quat_w": quat_w,
        "quat_x": quat_x,
        "quat_y": quat_y,
        "quat_z": quat_z,
    }


def sec_to_ass_time(sec: float) -> str:
    """Convert seconds to ASS time H:MM:SS.cc."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(
    srt_path: Path,
    out_path: Path,
    imperial: bool = False,
    velocity_window: int = 15,
    dheading: float = 0.0,
) -> None:
    content = srt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\n+", content)

    records: list[dict] = []
    for block in blocks:
        if not block.strip():
            continue
        rec = parse_srt_block(block)
        if rec:
            records.append(rec)

    ass = """[Script Info]
Title: DJI Telemetry HUD
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HUD,DejaVu Sans Mono,30,&H0000FF00,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,7,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    if velocity_window > 0:
        # Speed from current frame vs N frames back (~1 s for N=30).
        spd_h_filtered = [None] * len(records)
        spd_v_filtered = [None] * len(records)
        for i in range(len(records)):
            j = max(0, i - velocity_window)
            if j == i:
                continue
            dt = records[i]["start"] - records[j]["start"]
            if dt <= 0:
                continue
            try:
                lat_i = float(records[i]["lat"])
                lon_i = float(records[i]["lon"])
                alt_i = float(records[i]["abs_alt"]) if records[i].get("abs_alt") else 0.0
                lat_j = float(records[j]["lat"])
                lon_j = float(records[j]["lon"])
                alt_j = float(records[j]["abs_alt"]) if records[j].get("abs_alt") else 0.0
                spd_h_filtered[i] = haversine_m(lat_j, lon_j, lat_i, lon_i) / dt
                spd_v_filtered[i] = (alt_i - alt_j) / dt
            except (ValueError, TypeError):
                pass
    else:
        # Compute raw speed per frame using symmetric derivative (prev, next) when possible.
        raw_spd_h: list[float | None] = [None] * len(records)
        raw_spd_v: list[float | None] = [None] * len(records)
        for i in range(len(records)):
            rec = records[i]
            prev = records[i - 1] if i > 0 else None
            next_rec = records[i + 1] if i + 1 < len(records) else None
            if prev is not None and next_rec is not None:
                dt = next_rec["start"] - prev["start"]
                if dt <= 0:
                    continue
                try:
                    lat_p = float(prev["lat"])
                    lon_p = float(prev["lon"])
                    alt_p = float(prev["abs_alt"]) if prev["abs_alt"] else 0.0
                    lat_n = float(next_rec["lat"])
                    lon_n = float(next_rec["lon"])
                    alt_n = float(next_rec["abs_alt"]) if next_rec["abs_alt"] else 0.0
                    raw_spd_h[i] = haversine_m(lat_p, lon_p, lat_n, lon_n) / dt
                    raw_spd_v[i] = (alt_n - alt_p) / dt
                except (ValueError, TypeError):
                    pass
            elif prev is not None:
                dt = rec["start"] - prev["start"]
                if dt <= 0:
                    continue
                try:
                    lat_p = float(prev["lat"])
                    lon_p = float(prev["lon"])
                    alt_p = float(prev["abs_alt"]) if prev["abs_alt"] else 0.0
                    lat_f = float(rec["lat"])
                    lon_f = float(rec["lon"])
                    alt_f = float(rec["abs_alt"]) if rec["abs_alt"] else 0.0
                    raw_spd_h[i] = haversine_m(lat_p, lon_p, lat_f, lon_f) / dt
                    raw_spd_v[i] = (alt_f - alt_p) / dt
                except (ValueError, TypeError):
                    pass
            elif next_rec is not None:
                dt = next_rec["start"] - rec["start"]
                if dt <= 0:
                    continue
                try:
                    lat_f = float(rec["lat"])
                    lon_f = float(rec["lon"])
                    alt_f = float(rec["abs_alt"]) if rec["abs_alt"] else 0.0
                    lat_n = float(next_rec["lat"])
                    lon_n = float(next_rec["lon"])
                    alt_n = float(next_rec["abs_alt"]) if next_rec["abs_alt"] else 0.0
                    raw_spd_h[i] = haversine_m(lat_f, lon_f, lat_n, lon_n) / dt
                    raw_spd_v[i] = (alt_n - alt_f) / dt
                except (ValueError, TypeError):
                    pass

        spd_h_filtered = apply_velocity_filter(raw_spd_h)
        spd_v_filtered = apply_vertical_velocity_filter(raw_spd_v)

    ref_lat = ref_lon = None
    ref_index = -1
    for idx, rec in enumerate(records):
        if not rec.get("lat") or not rec.get("lon"):
            continue
        try:
            lat_f = float(rec["lat"])
            lon_f = float(rec["lon"])
            if lat_f != 0.0 and lon_f != 0.0:
                ref_lat, ref_lon = lat_f, lon_f
                ref_index = idx
                break
        except (ValueError, TypeError):
            pass

    for i, rec in enumerate(records):
        start = sec_to_ass_time(rec["start"])
        end = sec_to_ass_time(rec["end"])

        spd_h = spd_h_filtered[i]
        spd_v = spd_v_filtered[i]
        if imperial:
            spd_h = spd_h * MPS_TO_MPH if spd_h is not None else None
            spd_v_fts = spd_v * M_TO_FT if spd_v is not None else None
            spd_h_s = f"{spd_h:6.1f} mph" if spd_h is not None else "  —    mph"
            spd_v_s = f"{spd_v_fts:+6.1f} ft/s" if spd_v_fts is not None else "  —    ft/s"
        else:
            spd_h_s = f"{spd_h:6.1f} m/s" if spd_h is not None else "  —    m/s"
            spd_v_s = f"{spd_v:+6.1f} m/s" if spd_v is not None else "  —    m/s"

        # Orientation from quaternion (roll, pitch, yaw degrees); heading 0-360 (fixed width)
        # Heading comes from magnetometer, so show it always. Roll ambiguous when gimbal down.
        orient_s = "—"
        if rec["quat_w"] is not None:
            roll, pitch, yaw = quat_to_euler_deg(
                rec["quat_w"], rec["quat_x"], rec["quat_y"], rec["quat_z"]
            )
            # Snap near-zero to 0 to avoid -0/0 sign flicker
            if abs(roll) < 0.5:
                roll = 0.0
            if abs(pitch) < 0.5:
                pitch = 0.0
            hdg = (int(round(yaw)) + 360 + int(round(dheading))) % 360
            gimbal_down = abs(pitch + 90) < 5
            if gimbal_down:
                # Yaw from quaternion is degenerate at pitch=-90° (gimbal lock), so don't show it
                orient_s = f"Roll  ---°  Pitch {pitch:4.0f}°  Hdg  ---°"
            else:
                orient_s = f"Roll {roll:4.0f}°  Pitch {pitch:4.0f}°  Hdg {hdg:3d}°"

        # Time with seconds to one decimal place (tenths)
        ts = rec["timestamp"]
        try:
            if " " in ts:
                date_part, time_part = ts.split(" ", 1)
                parts = time_part.split(":")
                if len(parts) == 3:
                    sec = round(float(parts[-1]), 1)
                    ts = f"{date_part} {parts[0]}:{parts[1]}:{sec:.1f}"
        except (ValueError, IndexError):
            pass

        lat_s = f"{float(rec['lat']):10.6f}" if rec["lat"] else "—"
        lon_s = f"{float(rec['lon']):11.6f}" if rec["lon"] else "—"
        if imperial:
            alt_s = f"{float(rec['abs_alt']) * M_TO_FT:6.0f}ft" if rec["abs_alt"] else "   —  ft"
            agl_s = f"{float(rec['rel_alt']) * M_TO_FT:5.0f}ft" if rec.get("rel_alt") else "  —  ft"
        else:
            alt_s = f"{float(rec['abs_alt']):6.0f}m" if rec["abs_alt"] else "   —  m"
            agl_s = f"{float(rec['rel_alt']):5.0f}m" if rec.get("rel_alt") else "  —  m"

        shutter_s = f"{rec['shutter']:>8}"
        fnum_s = f"{rec['fnum']:>4}"
        iso_s = f"{rec['iso']:>4}"
        ev_s = f"EV {rec['ev']:>3}" if rec.get("ev") else ""
        pos_line = f"{lat_s}, {lon_s}"
        if i < ref_index or ref_lat is None or ref_lon is None:
            pos_line += "\\NRelative: ---"
        elif rec["lat"] and rec["lon"]:
            pos_line += f"\\N{latlon_to_relative_str(float(rec['lat']), float(rec['lon']), ref_lat, ref_lon, imperial)}"
        cam_part = f"{shutter_s}  f/{fnum_s}  ISO {iso_s}"
        if ev_s:
            cam_part += f"  {ev_s}"
        line1 = f"{ts}\\N{pos_line}\\NALT {alt_s}  AGL {agl_s}  |  {cam_part}"

        line2 = f"Spd {spd_h_s}  Climb {spd_v_s}\\N{orient_s}"
        text = f"{line1}\\N{line2}"
        ass += f"Dialogue: 0,{start},{end},HUD,,0,0,0,,{text}\n"

    out_path.write_text(ass, encoding="utf-8")
    print(f"Wrote {len(records)} HUD cues to {out_path}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description="Build DJI telemetry HUD overlay (ASS) from SRT.")
    p.add_argument("-i", "--imperial", action="store_true", help="Use feet and mph instead of meters and m/s")
    p.add_argument(
        "--velocity-window",
        type=int,
        default=15,
        metavar="N",
        help="Compute speed from frame vs N frames back (default 15); use 0 for frame-to-frame + filter",
    )
    p.add_argument(
        "--dheading",
        type=float,
        default=0.0,
        metavar="DEG",
        help="Add DEG degrees to heading (corrected value shown as 0–360°)",
    )
    p.add_argument("base", type=str, help="Base name for clip (script appends .srt for input, _HUD.ass for output)")
    args = p.parse_args()
    base = Path(args.base)
    srt_path = base.with_suffix(".srt")
    if not srt_path.exists():
        srt_path = base.with_suffix(".SRT")
    if not srt_path.exists():
        raise SystemExit(f"SRT file not found: {base.with_suffix('.srt')} or {base.with_suffix('.SRT')}")
    out_path = base.with_name(base.stem + "_HUD.ass")
    build_ass(
        srt_path,
        out_path,
        imperial=args.imperial,
        velocity_window=args.velocity_window,
        dheading=args.dheading,
    )


if __name__ == "__main__":
    main()
