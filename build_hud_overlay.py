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
        unit = "feet"
    else:
        unit = "m"
    return f"Relative {unit}: {dn:+6.1f} N  {de:+6.1f} E"


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

    # Gimbal: pp_target quaternion (w,x,y,z) and pp_limit_ratio
    pp_target = get("pp_target")  # e.g. "0.159, -0.000, -0.000, -0.987"
    pp_limit_ratio = get("pp_limit_ratio")

    quat_w = quat_x = quat_y = quat_z = None
    if pp_target:
        parts = [p.strip() for p in pp_target.split(",")]
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


def build_ass(srt_path: Path, out_path: Path, imperial: bool = False) -> None:
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

    # Compute raw instantaneous speed per frame (from previous frame)
    raw_spd_h: list[float | None] = [None] * len(records)
    raw_spd_v: list[float | None] = [None] * len(records)
    for i in range(1, len(records)):
        rec, prev = records[i], records[i - 1]
        dt = rec["start"] - prev["start"]
        if dt <= 0:
            continue
        try:
            lat_f = float(rec["lat"])
            lon_f = float(rec["lon"])
            alt_f = float(rec["abs_alt"]) if rec["abs_alt"] else 0.0
            plat = float(prev["lat"])
            plon = float(prev["lon"])
            palt = float(prev["abs_alt"]) if prev["abs_alt"] else 0.0
            raw_spd_h[i] = haversine_m(plat, plon, lat_f, lon_f) / dt
            raw_spd_v[i] = (alt_f - palt) / dt
        except (ValueError, TypeError):
            pass

    # Centered moving average to smooth speed (window ~0.5 s at 30 fps)
    SMOOTH_WINDOW = 15
    half = SMOOTH_WINDOW // 2

    def smooth(values: list[float | None], i: int) -> float | None:
        start = max(0, i - half)
        end = min(len(values), i + half + 1)
        window = [v for v in values[start:end] if v is not None]
        if not window:
            return None
        return sum(window) / len(window)

    ref_lat = ref_lon = None
    if records and records[0].get("lat") and records[0].get("lon"):
        try:
            ref_lat = float(records[0]["lat"])
            ref_lon = float(records[0]["lon"])
        except (ValueError, TypeError):
            pass

    for i, rec in enumerate(records):
        start = sec_to_ass_time(rec["start"])
        end = sec_to_ass_time(rec["end"])

        spd_h = smooth(raw_spd_h, i)
        spd_v = smooth(raw_spd_v, i)
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
            hdg = (int(round(yaw)) + 360) % 360
            gimbal_down = abs(pitch + 90) < 5
            if gimbal_down:
                orient_s = f"Roll  ---°  Pitch {pitch:4.0f}°  Hdg {hdg:3d}°"
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
        pos_line = f"{lat_s}, {lon_s}"
        if ref_lat is not None and ref_lon is not None and rec["lat"] and rec["lon"]:
            pos_line += f"\\N{latlon_to_relative_str(float(rec['lat']), float(rec['lon']), ref_lat, ref_lon, imperial)}"
        line1 = f"{ts}\\N{pos_line}\\NALT {alt_s}  AGL {agl_s}  |  {shutter_s}  f/{fnum_s}  ISO {iso_s}"

        line2 = f"Spd {spd_h_s}  Climb {spd_v_s}\\N{orient_s}"
        text = f"{line1}\\N{line2}"
        ass += f"Dialogue: 0,{start},{end},HUD,,0,0,0,,{text}\n"

    out_path.write_text(ass, encoding="utf-8")
    print(f"Wrote {len(records)} HUD cues to {out_path}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description="Build DJI telemetry HUD overlay (ASS) from SRT.")
    p.add_argument("-i", "--imperial", action="store_true", help="Use feet and mph instead of meters and m/s")
    p.add_argument("base", type=str, help="Base name for clip (script appends .srt for input, _HUD.ass for output)")
    args = p.parse_args()
    base = Path(args.base)
    srt_path = base.with_suffix(".srt")
    if not srt_path.exists():
        srt_path = base.with_suffix(".SRT")
    if not srt_path.exists():
        raise SystemExit(f"SRT file not found: {base.with_suffix('.srt')} or {base.with_suffix('.SRT')}")
    out_path = base.with_name(base.stem + "_HUD.ass")
    build_ass(srt_path, out_path, imperial=args.imperial)


if __name__ == "__main__":
    main()
