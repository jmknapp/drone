# DJI Drone Telemetry Overlay Scripts

Scripts to overlay telemetry from DJI SRT files onto drone video as a **green HUD** burn-in.

## Prerequisites

- **Python 3** (standard library)
- **FFmpeg** (with libx264, libass, AAC support)

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
./render_hud.sh /path/to/clips (e.g. ./render_hud.sh ./altitude_test)

# Imperial (feet, mph)
./render_hud.sh DJI_20260217162018_0009_D --imperial
# or
./render_hud.sh /path/to/clips -i
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

## Summary

All commands take **BASE_OR_DIR**: base name (scripts append `.srt`, `.mp4`, `.m4a`) or a directory that contains one `.srt`, one `.mp4`, and one `.m4a` with the same stem.

| Goal | Command |
|------|--------|
| HUD video (metric) | `./render_hud.sh BASE_OR_DIR` |
| HUD video (imperial) | `./render_hud.sh BASE_OR_DIR --imperial` |
