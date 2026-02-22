#!/usr/bin/env python3
"""
Export vertical velocity (m/s) vs timestamp to CSV from DJI SRT telemetry.
One row per frame. Output: timestamp,vertical_velocity (seconds from start, m/s).
"""
import argparse
import csv
import re
import sys
from pathlib import Path

from build_hud_overlay import parse_srt_block


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
    p.add_argument("-o", "--output", type=str, help="Output CSV path")
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
    out_path = Path(args.output) if args.output else base.with_name(base.stem + "_vertical_velocity.csv")

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "vertical_velocity"])
        for i, rec in enumerate(records):
            prev = records[i - 1] if i > 0 else None
            next_rec = records[i + 1] if i + 1 < len(records) else None
            timestamp = rec["start"] - t0
            vel_v = vertical_velocity_mps(rec, prev, next_rec)
            w.writerow([f"{timestamp:.3f}", f"{vel_v:.4f}" if vel_v is not None else ""])

    print(f"Wrote {len(records)} rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
