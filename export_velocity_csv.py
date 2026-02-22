#!/usr/bin/env python3
"""
Export drone 3D velocity (m/s) vs timestamp to CSV from DJI SRT telemetry.
Output: timestamp,velocity (timestamp in seconds from video start, velocity in m/s).
"""
import argparse
import csv
import math
import re
import sys
from pathlib import Path

from build_hud_overlay import parse_srt_block, haversine_m
from velocity_filters import median_filter, trimmed_mean_filter


def load_srt_records(srt_path: Path) -> list[dict]:
    """Parse SRT file into list of telemetry records."""
    content = srt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\n+", content)
    records: list[dict] = []
    for block in blocks:
        if not block.strip():
            continue
        rec = parse_srt_block(block)
        if rec:
            records.append(rec)
    return records


def moving_average_filter(values: list[float | None], window: int) -> list[float | None]:
    """
    Apply moving average to smooth high-frequency jitter.
    Uses only valid values in each window; output None if window has no valid values.
    """
    if window < 1:
        return list(values)
    half = window // 2
    out: list[float | None] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        win = [v for v in values[lo:hi] if v is not None]
        if win:
            out.append(sum(win) / len(win))
        else:
            out.append(None)
    return out


def velocity_3d_mps(rec: dict, prev: dict | None, next_rec: dict | None) -> float | None:
    """
    Compute 3D velocity magnitude in m/s using symmetric derivative where possible.
    """
    try:
        lat = float(rec["lat"])
        lon = float(rec["lon"])
        alt = float(rec["abs_alt"]) if rec.get("abs_alt") else 0.0
    except (ValueError, TypeError):
        return None

    if prev is not None and next_rec is not None:
        dt = next_rec["start"] - prev["start"]
        if dt <= 0:
            return None
        try:
            lat_next = float(next_rec["lat"])
            lon_next = float(next_rec["lon"])
            alt_next = float(next_rec["abs_alt"]) if next_rec.get("abs_alt") else 0.0
            lat_prev = float(prev["lat"])
            lon_prev = float(prev["lon"])
            alt_prev = float(prev["abs_alt"]) if prev.get("abs_alt") else 0.0
        except (ValueError, TypeError):
            return None
        dist_h = haversine_m(lat_prev, lon_prev, lat_next, lon_next)
        dist_v = alt_next - alt_prev
    elif prev is not None:
        dt = rec["start"] - prev["start"]
        if dt <= 0:
            return None
        try:
            lat_prev = float(prev["lat"])
            lon_prev = float(prev["lon"])
            alt_prev = float(prev["abs_alt"]) if prev.get("abs_alt") else 0.0
        except (ValueError, TypeError):
            return None
        dist_h = haversine_m(lat_prev, lon_prev, lat, lon)
        dist_v = alt - alt_prev
    elif next_rec is not None:
        dt = next_rec["start"] - rec["start"]
        if dt <= 0:
            return None
        try:
            lat_next = float(next_rec["lat"])
            lon_next = float(next_rec["lon"])
            alt_next = float(next_rec["abs_alt"]) if next_rec.get("abs_alt") else 0.0
        except (ValueError, TypeError):
            return None
        dist_h = haversine_m(lat, lon, lat_next, lon_next)
        dist_v = alt_next - alt
    else:
        return None

    vel_3d = math.sqrt(dist_h * dist_h + dist_v * dist_v) / dt
    return vel_3d


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export drone 3D velocity (m/s) vs timestamp to CSV from DJI SRT.",
    )
    p.add_argument(
        "base",
        type=str,
        help="Base name (script uses .srt); output: BASE_velocity.csv",
    )
    p.add_argument("-o", "--output", type=str, help="Output CSV path")
    p.add_argument(
        "--median-window",
        type=int,
        default=7,
        metavar="N",
        help="Median filter window to remove spikes and short zero runs (0=off)",
    )
    p.add_argument(
        "--smooth-window",
        type=int,
        default=0,
        metavar="N",
        help="Moving average window (e.g. 5–9) to reduce high-freq jitter",
    )
    p.add_argument(
        "--trimmed-window",
        type=int,
        default=21,
        metavar="N",
        help="Trimmed-mean window for nearly constant output (0=off)",
    )
    p.add_argument(
        "--trim",
        type=int,
        default=0,
        metavar="K",
        help="With --trimmed-window: drop K highest and K lowest per window (default: N//5)",
    )
    args = p.parse_args()

    base = Path(args.base)
    srt_path = base.with_suffix(".srt")
    if not srt_path.exists():
        srt_path = base.with_suffix(".SRT")
    if not srt_path.exists():
        raise SystemExit(f"SRT not found: {base.with_suffix('.srt')}")

    records = load_srt_records(srt_path)
    if not records:
        raise SystemExit(f"No records in {srt_path}")

    t0 = records[0]["start"]

    velocities: list[float | None] = []
    for i, rec in enumerate(records):
        prev = records[i - 1] if i > 0 else None
        next_rec = records[i + 1] if i + 1 < len(records) else None
        velocities.append(velocity_3d_mps(rec, prev, next_rec))

    if args.median_window > 0:
        velocities = median_filter(velocities, args.median_window)
    if args.smooth_window > 0:
        velocities = moving_average_filter(velocities, args.smooth_window)
    if args.trimmed_window > 0:
        k = args.trim if args.trim > 0 else max(1, args.trimmed_window // 5)
        velocities = trimmed_mean_filter(velocities, args.trimmed_window, k)

    out_path = Path(args.output) if args.output else base.with_name(base.stem + "_velocity.csv")

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "velocity"])
        for i, rec in enumerate(records):
            timestamp = rec["start"] - t0
            vel = velocities[i]
            w.writerow([f"{timestamp:.3f}", f"{vel:.4f}" if vel is not None else ""])

    print(f"Wrote {len(records)} rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
