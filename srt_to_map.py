#!/usr/bin/env python3
"""
Create an OpenStreetMap flight path map from a DJI SRT file.
Output: interactive HTML map (e.g. BASE_flight_map.html).
Requires: folium (pip install folium)
"""
import argparse
import re
import sys
from pathlib import Path

from build_hud_overlay import parse_srt_block


def load_srt_records(srt_path: Path) -> list[dict]:
    """Parse SRT file into list of telemetry records."""
    content = srt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\n+", content)
    records = []
    for block in blocks:
        if not block.strip():
            continue
        rec = parse_srt_block(block)
        if rec:
            records.append(rec)
    return records


def main() -> None:
    p = argparse.ArgumentParser(
        description="Create an OpenStreetMap flight path map from a DJI SRT file.",
    )
    p.add_argument(
        "base",
        type=str,
        help="Base name (script uses .srt); output: BASE_flight_map.html",
    )
    p.add_argument("-o", "-O", "--output", type=str, dest="output", help="Output HTML path")
    p.add_argument(
        "--downsample",
        type=int,
        default=1,
        metavar="N",
        help="Use every Nth point (default 1); use e.g. 30 for ~1 point/sec at 30 fps",
    )
    args = p.parse_args()

    try:
        import folium
    except ImportError:
        raise SystemExit("This script requires folium. Install with: pip install folium")

    base = Path(args.base)
    srt_path = base.with_suffix(".srt")
    if not srt_path.exists():
        srt_path = base.with_suffix(".SRT")
    if not srt_path.exists():
        raise SystemExit(f"SRT not found: {base.with_suffix('.srt')}")

    records = load_srt_records(srt_path)
    if not records:
        raise SystemExit(f"No records in {srt_path}")

    # Extract (lat, lon), skip invalid/zero (no GPS lock)
    points = []
    for rec in records:
        if not rec.get("lat") or not rec.get("lon"):
            continue
        try:
            lat = float(rec["lat"])
            lon = float(rec["lon"])
            if lat == 0.0 and lon == 0.0:
                continue
            points.append((lat, lon))
        except (ValueError, TypeError):
            continue

    if len(points) < 2:
        raise SystemExit("Not enough valid GPS points to draw a path.")

    # Downsample
    points = points[:: args.downsample]
    if len(points) < 2:
        points = points[:: max(1, args.downsample // 2)]  # fallback
    if len(points) < 2:
        raise SystemExit("Not enough points after downsampling.")

    # Center and bounds
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    center_lat = (min(lats) + max(lats)) / 2
    center_lon = (min(lons) + max(lons)) / 2

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
        overlay=False,
        control=True,
    ).add_to(m)
    folium.LayerControl().add_to(m)
    folium.PolyLine(
        points,
        color="blue",
        weight=4,
        opacity=0.8,
        popup="Flight path",
    ).add_to(m)
    folium.Marker(
        points[0],
        popup="Start",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(m)
    folium.Marker(
        points[-1],
        popup="End",
        icon=folium.Icon(color="red", icon="stop"),
    ).add_to(m)

    out_path = Path(args.output) if args.output else base.with_name(base.stem + "_flight_map.html")
    m.save(str(out_path))
    print(f"Wrote {out_path} ({len(points)} points)", file=sys.stderr)


if __name__ == "__main__":
    main()
