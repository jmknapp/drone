#!/usr/bin/env python3
"""
Export vertical velocity (m/s) vs timestamp to CSV from DJI SRT telemetry.
One row per frame. Output: timestamp, raw_velocity, filtered_velocity (seconds from start, m/s).
"""
import argparse
import csv
import re
import sys
from pathlib import Path

from build_hud_overlay import parse_srt_block
from velocity_filters import apply_vertical_velocity_filter


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


def vertical_velocity_mps(rec: dict, prev: dict | None, next_rec: dict | None) -> float | None:
    """Compute vertical velocity (m/s) using symmetric derivative when possible."""
    try:
        alt = float(rec["abs_alt"]) if rec.get("abs_alt") else 0.0
    except (ValueError, TypeError):
        return None

    if prev is not None and next_rec is not None:
        dt = next_rec["start"] - prev["start"]
        if dt <= 0:
            return None
        try:
            alt_next = float(next_rec["abs_alt"]) if next_rec.get("abs_alt") else 0.0
            alt_prev = float(prev["abs_alt"]) if prev.get("abs_alt") else 0.0
        except (ValueError, TypeError):
            return None
        return (alt_next - alt_prev) / dt
    elif prev is not None:
        dt = rec["start"] - prev["start"]
        if dt <= 0:
            return None
        try:
            alt_prev = float(prev["abs_alt"]) if prev.get("abs_alt") else 0.0
        except (ValueError, TypeError):
            return None
        return (alt - alt_prev) / dt
    elif next_rec is not None:
        dt = next_rec["start"] - rec["start"]
        if dt <= 0:
            return None
        try:
            alt_next = float(next_rec["abs_alt"]) if next_rec.get("abs_alt") else 0.0
        except (ValueError, TypeError):
            return None
        return (alt_next - alt) / dt
    return None


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export vertical velocity (m/s) per frame to CSV from DJI SRT.",
    )
    p.add_argument(
        "base",
        type=str,
        help="Base name (script uses .srt); output: BASE_vertical_velocity.csv",
    )
    p.add_argument("-o", "-O", "--output", type=str, dest="output", help="Output CSV path")
    p.add_argument(
        "--velocity-window",
        type=int,
        default=0,
        metavar="N",
        help="If N>0, add column: vertical velocity from N frames back to N forward (~1 s for N=15 at 30 fps)",
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
    raw_velocities = []
    for i, rec in enumerate(records):
        prev = records[i - 1] if i > 0 else None
        next_rec = records[i + 1] if i + 1 < len(records) else None
        raw_velocities.append(vertical_velocity_mps(rec, prev, next_rec))
    filtered_velocities = apply_vertical_velocity_filter(raw_velocities)

    window_velocities: list[float | None] = [None] * len(records)
    if args.velocity_window > 0:
        for i in range(len(records)):
            j_back = max(0, i - args.velocity_window)
            j_forward = min(len(records) - 1, i + args.velocity_window)
            if j_back == j_forward:
                continue
            dt = records[j_forward]["start"] - records[j_back]["start"]
            if dt <= 0:
                continue
            try:
                alt_b = float(records[j_back]["abs_alt"]) if records[j_back].get("abs_alt") else 0.0
                alt_f = float(records[j_forward]["abs_alt"]) if records[j_forward].get("abs_alt") else 0.0
                window_velocities[i] = (alt_f - alt_b) / dt
            except (ValueError, TypeError):
                pass

    out_path = Path(args.output) if args.output else base.with_name(base.stem + "_vertical_velocity.csv")

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        headers = ["timestamp", "raw_velocity", "filtered_velocity"]
        if args.velocity_window > 0:
            headers.append("window_velocity")
        w.writerow(headers)
        for i, rec in enumerate(records):
            timestamp = rec["start"] - t0
            row = [
                f"{timestamp:.3f}",
                f"{raw_velocities[i]:.4f}" if raw_velocities[i] is not None else "",
                f"{filtered_velocities[i]:.4f}" if filtered_velocities[i] is not None else "",
            ]
            if args.velocity_window > 0:
                wv = window_velocities[i]
                row.append(f"{wv:.4f}" if wv is not None else "")
            w.writerow(row)

    print(f"Wrote {len(records)} rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
