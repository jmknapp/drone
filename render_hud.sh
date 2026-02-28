#!/bin/bash
# Build HUD overlay and render MP4 with telemetry burn-in and audio.
# Usage: ./render_hud.sh [--imperial | -i] [--no-audio | -n] [--dheading DEG] [-x] BASE_OR_DIR
#   BASE_OR_DIR = base name (script appends .srt, .mp4, .m4a), or directory containing one .srt, .mp4, .m4a
#   --no-audio = use audio from MP4 only (skip external .m4a; use when MP4 already has audio)
#   --dheading DEG = add DEG degrees to HUD heading (corrected to 0-360)
#   -x = hide lat/lon from HUD (privacy)
set -e
cd "$(dirname "$0")"

IMPERIAL=()
NO_AUDIO=false
DHEADING=()
HIDE_LOCATION=()
ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --imperial|-i) IMPERIAL=("$1"); shift ;;
    --no-audio|-n) NO_AUDIO=true; shift ;;
    -x|--hide-location) HIDE_LOCATION=("-x"); shift ;;
    --dheading|-dheading)
      shift
      [[ -z "${1:-}" ]] && { echo "Missing value for --dheading" >&2; exit 1; }
      DHEADING=("--dheading" "$1")
      shift
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      [[ -n "$ARG" ]] && { echo "Multiple paths given: $ARG and $1" >&2; exit 1; }
      ARG="$1"
      shift
      ;;
  esac
done
if [[ -z "$ARG" ]]; then
  echo "Usage: $0 [--imperial | -i] [--no-audio | -n] [--dheading DEG] [-x] BASE_OR_DIR" >&2
  echo "  BASE_OR_DIR = base name or directory containing one .srt, .mp4, .m4a" >&2
  echo "  --no-audio, -n = use MP4 audio only (skip external .m4a)" >&2
  echo "  --dheading DEG = add DEG degrees to HUD heading" >&2
  echo "  -x = hide lat/lon from HUD (privacy)" >&2
  exit 1
fi
if [[ -d "$ARG" ]]; then
  SRT_FILE=$(find "$ARG" -maxdepth 1 -type f \( -iname "*.srt" \) | head -1)
  if [[ -z "$SRT_FILE" ]]; then
    echo "No .srt file in directory: $ARG" >&2
    exit 1
  fi
  DIR="$ARG"
  STEM=$(basename "${SRT_FILE%.*}")
  BASE="${DIR}/${STEM}"
  SRT="" MP4="" M4A=""
  for ext in srt SRT; do [[ -f "${BASE}.${ext}" ]] && SRT="${BASE}.${ext}" && break; done
  for ext in mp4 MP4; do [[ -f "${BASE}.${ext}" ]] && MP4="${BASE}.${ext}" && break; done
  for ext in m4a M4A; do [[ -f "${BASE}.${ext}" ]] && M4A="${BASE}.${ext}" && break; done
  if [[ -z "$SRT" || -z "$MP4" ]]; then
    echo "Need one .srt and one .mp4 with same base name in: $ARG" >&2
    exit 1
  fi
  if [[ "$NO_AUDIO" != "true" && -z "$M4A" ]]; then
    echo "Need one .m4a with same base name in: $ARG (or use --no-audio to use MP4 audio only)" >&2
    exit 1
  fi
else
  BASE="$ARG"
  SRT="${BASE}.srt"
  MP4="${BASE}.mp4"
  M4A=""
  for ext in m4a M4A; do [[ -f "${BASE}.${ext}" ]] && M4A="${BASE}.${ext}" && break; done
  if [[ "$NO_AUDIO" != "true" && -z "$M4A" ]]; then
    echo "Need ${BASE}.m4a (or use --no-audio to use MP4 audio only)" >&2
    exit 1
  fi
fi
ASS="${BASE}_HUD.ass"
OUT="${BASE}_HUD.mp4"

echo "Building HUD overlay from ${SRT}..."
python3 build_hud_overlay.py "${IMPERIAL[@]}" "${DHEADING[@]}" "${HIDE_LOCATION[@]}" "$BASE"

# Get total frame count for progress
duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$MP4" 2>/dev/null || echo 0)
fps=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$MP4" 2>/dev/null || echo "30/1")
fps_val=$(awk "BEGIN {print $fps}")
total_frames=$(awk "BEGIN {printf \"%.0f\", $duration * $fps_val}")

show_progress() {
  while IFS= read -r line; do
    case "$line" in
      frame=*) frame="${line#frame=}" ;;
      progress=end) echo ""; return ;;
    esac
    if [[ -n "${frame:-}" && -n "$total_frames" && "$total_frames" -gt 0 ]]; then
      pct=$((frame * 100 / total_frames))
      printf "\rFrame %s of %s (%d%%)" "$frame" "$total_frames" "$pct"
    fi
  done
}

if [[ "$NO_AUDIO" == "true" || -z "$M4A" ]]; then
  echo "Rendering video with HUD (using MP4 audio if present)..."
  ffmpeg -hide_banner -loglevel error -y -progress pipe:1 \
    -i "$MP4" \
    -vf "ass=$ASS" \
    -map 0:v:0 -map 0:a? \
    -c:v libx264 -preset medium -crf 23 \
    -profile:v main -level 4.0 \
    -c:a copy \
    -movflags +faststart \
    "$OUT" 2>/dev/null | show_progress
else
  echo "Rendering video with HUD and audio (Main profile for wide compatibility)..."
  ffmpeg -hide_banner -loglevel error -y -progress pipe:1 \
    -i "$MP4" \
    -i "$M4A" \
    -map 0:0 -map 1:0 \
    -vf "ass=$ASS" \
    -c:v libx264 -preset medium -crf 23 \
    -profile:v main -level 4.0 \
    -c:a aac -b:a 128k -ar 44100 \
    -movflags +faststart \
    "$OUT" 2>/dev/null | show_progress
fi

echo "Done: $OUT"
