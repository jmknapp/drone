# DJI Drone Telemetry Overlay Scripts

Scripts to overlay telemetry from DJI SRT files onto drone video as a **green HUD** burn-in.

## Prerequisites

- **Python 3** (standard library for HUD/export; optional `folium` for flight map)
- **FFmpeg** (with libx264, libass, AAC support)

## Setup

Optional but recommended: use a virtual environment so the flight-map script can install `folium` without touching the system Python.

```bash
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
# or:  venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

(`requirements.txt` only adds **folium** for `srt_to_map.py`; the HUD and CSV scripts need no extra packages.)

## Input Files and Base Name or Directory

You pass either a **base name** or a **directory** (no default):

- **Base name** (e.g. `DJI_20260217162018_0009_D`): the scripts **append** `.srt`, `.mp4`, `.m4a` for inputs and create `BASE_HUD.ass` and `BASE_HUD.mp4`.
- **Directory**: the scripts look in that directory for **one** file with extension `.srt`, **one** with `.mp4`, and **one** with `.m4a`. The three files must share the same base name (e.g. `DJI_20260217162018_0009_D.srt`, `.mp4`, `.m4a`). Extensions are matched case-insensitively (`.srt`/`.SRT`, etc.). Use `--no-audio` to skip the `.m4a` requirement and use audio from the MP4 instead.

| Extension | Used for |
|-----------|----------|
| `.srt` | Telemetry input (per-frame GPS, orientation, exposure, etc.) |
| `.mp4` | Video input and HUD output |
| `.m4a` | Audio input (optional with `--no-audio`; uses MP4 audio when skipped) |

Example with base name `DJI_20260217162018_0009_D`:

- Inputs: `DJI_20260217162018_0009_D.srt`, `.mp4`, `.m4a`
- Outputs: `DJI_20260217162018_0009_D_HUD.ass`, `DJI_20260217162018_0009_D_HUD.mp4`

Example with directory: `./render_hud.sh /path/to/my_clips` uses the single `.srt` in that folder to get the stem, then expects matching `.mp4` and `.m4a` there.

---

## Green HUD Overlay

Burns a green, text-based HUD into the video (timestamp, position, altitude, speed, climb, attitude, heading).

### Quick start

```bash
# Make the script executable once
chmod +x render_hud.sh

# Base name (scripts append .srt, .mp4, .m4a)
./render_hud.sh DJI_20260217162018_0009_D

# Or a directory that contains one .srt, .mp4, .m4a with the same stem
./render_hud.sh /path/to/clips (e.g. ./render_hud.sh ./altitude_test)

# Imperial (feet, mph)
./render_hud.sh DJI_20260217162018_0009_D --imperial
# or
./render_hud.sh /path/to/clips -i

# Skip external .m4a and use MP4 audio (when MP4 already has audio)
./render_hud.sh DJI_20260217162018_0009_D --no-audio
# or
./render_hud.sh /path/to/clips -n
```

Output: **`BASE_HUD.mp4`** (e.g. `DJI_20260217162018_0009_D_HUD.mp4`).

### HUD contents

- Time (seconds to one decimal)
- Latitude, longitude; relative N/E from start (feet or meters)
- Altitude (MSL) and AGL (above ground level)
- Camera: shutter, f-number, ISO
- Speed (horizontal, smoothed) and climb rate (vertical speed, smoothed)
- Roll, pitch, heading (0–360°)

---

## Flight path map

Creates an interactive HTML map of the flight from the SRT’s GPS track (OpenStreetMap + optional satellite layer). Requires the venv and `pip install -r requirements.txt` (folium).

### Quick start

```bash
source venv/bin/activate   # or venv\Scripts\activate on Windows

python srt_to_map.py altitude_test/DJI_20260217162018_0009_D
# → altitude_test/DJI_20260217162018_0009_D_flight_map.html

# Custom output path
python srt_to_map.py BASE -O my_flight.html

# Long flights: use every 30th point (~1 per second at 30 fps)
python srt_to_map.py BASE --downsample 30
```

Open the `.html` file in a browser (double-click, or File → Open file in Chrome).

### Map contents

- **Blue line** – flight path
- **Green marker** – start
- **Red marker** – end
- **Layers** – switch in the top-right between **OpenStreetMap** (streets) and **Satellite** (Esri World Imagery)

---

## Summary

All commands take **BASE_OR_DIR**: base name (scripts append `.srt`, `.mp4`, `.m4a`) or a directory that contains one `.srt`, one `.mp4`, and one `.m4a` with the same stem.

| Goal | Command |
|------|--------|
| HUD video (metric) | `./render_hud.sh BASE_OR_DIR` |
| HUD video (imperial) | `./render_hud.sh BASE_OR_DIR --imperial` |
| HUD video (MP4 audio only, no .m4a) | `./render_hud.sh BASE_OR_DIR --no-audio` |
| Flight path map (OSM + satellite HTML) | `python srt_to_map.py BASE_OR_DIR` (requires venv + folium, see Setup) |
