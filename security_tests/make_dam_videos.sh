#!/usr/bin/env bash
# Generate four local MP4 inputs only. Does not upload or contact the application.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo "Usage: bash make_dam_videos.sh [output-directory]"
    exit 0
fi
if [[ $# -gt 1 ]]; then
    echo "Usage: bash make_dam_videos.sh [output-directory]" >&2
    exit 2
fi
OUT="${1:-$SCRIPT_DIR/generated}"
PYTHON="${PYTHON:-python3}"
for required in ffmpeg ffprobe "$PYTHON"; do
    if ! command -v "$required" >/dev/null 2>&1; then
        echo "Missing tool: $required" >&2
        exit 1
    fi
done
mkdir -p "$OUT"
cd "$OUT"

# Consume all encoder output to avoid SIGPIPE under pipefail.
ENCODERS="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
if [[ "$ENCODERS" == *libx264* ]]; then
    CODEC=libx264
else
    CODEC=mpeg4
fi
echo "Creating video fixtures with $CODEC in $PWD"
ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i 'testsrc2=size=640x360:rate=24' -t 2 -an \
    -c:v "$CODEC" -threads 2 -pix_fmt yuv420p -movflags +faststart VID01_valid.mp4

printf 'This is not a real video.\n' > VID02_fake.mp4
"$PYTHON" - <<'PY'
from pathlib import Path

data = bytearray(Path("VID01_valid.mp4").read_bytes())
if data[4:8] != b"ftyp":
    raise ValueError("Unexpected MP4 structure")
data[:4] = (0x7FFFFFFF).to_bytes(4, "big")
Path("VID03_broken.mp4").write_bytes(data)
PY

ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i 'color=c=black:size=4096x2160:rate=1' -frames:v 1 -an \
    -c:v "$CODEC" -threads 2 -pix_fmt yuv420p -movflags +faststart VID04_over4k.mp4

# Verify positive controls; an unexpected decoder failure must stop the script.
for fixture in VID01_valid.mp4 VID04_over4k.mp4; do
    echo "Inspecting $fixture"
    ffprobe -v error -show_entries stream=codec_name,width,height:format=duration \
        -of default=noprint_wrappers=1 "$fixture"
done
for fixture in VID02_fake.mp4 VID03_broken.mp4; do
    if ffprobe -v error "$fixture"; then
        echo "Unexpected FFprobe success for $fixture" >&2
        exit 1
    fi
    echo "Expected FFprobe failure: $fixture"
done
echo "Created four MP4s. Run verify_fixtures.py for dimensions, manifest and checksums."
