#!/bin/bash
# Build HUD overlay and render MP4 with telemetry burn-in and audio.
# Usage: ./render_hud.sh [--imperial | -i] [--no-audio | -n] BASE_OR_DIR
#   BASE_OR_DIR = base name (script appends .srt, .mp4, .m4a), or directory containing one .srt, .mp4, .m4a
#   --no-audio = use audio from MP4 only (skip external .m4a; use when MP4 already has audio)
set -e
cd "$(dirname "$0")"

IMPERIAL=()
NO_AUDIO=false
while [[ "$1" == "--imperial" || "$1" == "-i" || "$1" == "--no-audio" || "$1" == "-n" ]]; do
  if [[ "$1" == "--no-audio" || "$1" == "-n" ]]; then
    NO_AUDIO=true
  else
    IMPERIAL=("$1")
  fi
  shift
done
if [[ -z "$1" ]]; then
  echo "Usage: $0 [--imperial | -i] [--no-audio | -n] BASE_OR_DIR" >&2
  echo "  BASE_OR_DIR = base name or directory containing one .srt, .mp4, .m4a" >&2
  echo "  --no-audio, -n = use MP4 audio only (skip external .m4a)" >&2
  exit 1
fi
ARG="$1"
shift
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
python3 build_hud_overlay.py "${IMPERIAL[@]}" "$BASE"

if [[ "$NO_AUDIO" == "true" || -z "$M4A" ]]; then
  echo "Rendering video with HUD (using MP4 audio if present)..."
  ffmpeg -y \
    -i "$MP4" \
    -vf "ass=$ASS" \
    -map 0:v -map 0:a? \
    -c:v libx264 -preset medium -crf 23 \
    -profile:v main -level 4.0 \
    -c:a copy \
    -movflags +faststart \
    "$OUT"
else
  echo "Rendering video with HUD and audio (Main profile for wide compatibility)..."
  ffmpeg -y \
    -i "$MP4" \
    -i "$M4A" \
    -map 0:0 -map 1:0 \
    -vf "ass=$ASS" \
    -c:v libx264 -preset medium -crf 23 \
    -profile:v main -level 4.0 \
    -c:a aac -b:a 128k -ar 44100 \
    -movflags +faststart \
    "$OUT"
fi

echo "Done: $OUT"
