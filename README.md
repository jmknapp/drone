# DJI Drone Telemetry Overlay Scripts

Scripts to overlay telemetry from DJI SRT files onto drone video as a **green HUD** burn-in.

## Prerequisites

- **Python 3** (standard library)
- **FFmpeg** (with libx264, libass, AAC support)
- **utm** (optional, for UTM coordinates on HUD): `pip install utm`

## Input Files and Base Name or Directory

You pass either a **base name** or a **directory** (no default):

- **Base name** (e.g. `DJI_20260217162018_0009_D`): the scripts **append** `.srt`, `.mp4`, `.m4a` for inputs and create `BASE_HUD.ass` and `BASE_HUD.mp4`.
- **Directory**: the scripts look in that directory for **one** file with extension `.srt`, **one** with `.mp4`, and **one** with `.m4a`. The three files must share the same base name (e.g. `DJI_20260217162018_0009_D.srt`, `.mp4`, `.m4a`). Extensions are matched case-insensitively (`.srt`/`.SRT`, etc.).

| Extension | Used for |
|-----------|----------|
| `.srt` | Telemetry input (per-frame GPS, orientation, exposure, etc.) |
| `.mp4` | Video input and HUD output |
| `.m4a` | Audio input |

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
./render_hud.sh /path/to/clips

# Imperial (feet, mph)
./render_hud.sh DJI_20260217162018_0009_D --imperial
# or
./render_hud.sh /path/to/clips -i
```

Output: **`BASE_HUD.mp4`** (e.g. `DJI_20260217162018_0009_D_HUD.mp4`).

### HUD contents

- Time (seconds to one decimal)
- Latitude, longitude (and UTM zone/easting/northing when `utm` is installed)
- Altitude (MSL) and AGL (above ground level)
- Camera: shutter, f-number, ISO
- Speed (horizontal, smoothed) and climb rate (vertical speed, smoothed)
- Roll, pitch, heading (0–360°)

---

## UTM Grid Overlay

Overlays a **perspective-correct UTM grid** (100 ft / ~30.5 m intervals) on the video, projected onto the ground plane using camera pose from SRT telemetry.

### Prerequisites

- **Python 3** with `opencv-python`, `numpy`, and `utm`
- Video resolution typically 1920×1080 (camera intrinsics tuned for DJI NEO2)

### Usage

```bash
source venv/bin/activate
python3 build_utm_grid_overlay.py altitude_test/DJI_20260217162018_0009_D
```

Output: `BASE_utm_grid.mp4`.

### Options

| Option | Description |
|--------|-------------|
| `-o FILE` | Output path (default: BASE_utm_grid.mp4) |
| `--ground-alt M` | Ground plane altitude in meters (default: first frame AGL=0) |
| `--extent M` | Half extent of grid in meters (default: 200) |
| `--fx`, `--fy` | Camera focal length (default: ~637 for NEO2 119.8° FOV) |
| `--thickness N` | Line thickness (default: 1) |
| `-q` | Quiet (no progress) |

---

## Summary

All commands take **BASE_OR_DIR**: base name (scripts append `.srt`, `.mp4`, `.m4a`) or a directory that contains one `.srt`, one `.mp4`, and one `.m4a` with the same stem.

| Goal | Command |
|------|--------|
| HUD video (metric) | `./render_hud.sh BASE_OR_DIR` |
| HUD video (imperial) | `./render_hud.sh BASE_OR_DIR --imperial` |
| UTM grid overlay | `python3 build_utm_grid_overlay.py BASE` |
