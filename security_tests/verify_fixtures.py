#!/usr/bin/env python3
"""Check local fixture properties and record hashes; does not test the DAM."""

import argparse
import hashlib
import json
import math
import struct
import subprocess
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from make_dam_images_glb import DEFAULT_OUTPUT, write_manifest


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_images(directory):
    for filename, image_format, dimensions in (
        ("IMG01_valid.jpg", "JPEG", (640, 360)),
        ("IMG02_valid.jpeg", "JPEG", (640, 360)),
        ("IMG03_valid.png", "PNG", (640, 360)),
        ("IMG06_wide.png", "PNG", (5000, 2000)),
        ("SHR01_over1MiB.png", "PNG", (800, 800)),
    ):
        with Image.open(directory / filename) as image:
            image.load()
            require((image.format, image.size) == (image_format, dimensions), f"Unexpected properties: {filename}")
        print(f"PASS {filename}: {image_format} {dimensions}")
    require((directory / "IMG01_valid.jpg").read_bytes() == (directory / "IMG02_valid.jpeg").read_bytes(), "JPEG copies differ")
    require((directory / "SHR01_over1MiB.png").stat().st_size > 1024 * 1024, "Size fixture must exceed 1 MiB")
    try:
        with Image.open(directory / "IMG04_fake.png") as image:
            image.load()
    except UnidentifiedImageError:
        print("PASS IMG04_fake.png: not recognised as an image")
    else:
        raise ValueError("Fake PNG unexpectedly opened")
    with Image.open(directory / "IMG05_corrupted.png") as image:
        image.verify()
    try:
        with Image.open(directory / "IMG05_corrupted.png") as image:
            image.load()
    except OSError as error:
        print(f"PASS IMG05_corrupted.png: verify passed; full decode failed ({error})")
    else:
        raise ValueError("Corrupted PNG unexpectedly decoded")


def verify_glb_construction(directory):
    for filename in ("GLB01_valid.glb", "GLB02_broken.glb", "GLB03_external.glb", "GLB04_invalid_accessor.glb"):
        data = (directory / filename).read_bytes()
        magic, version, length = struct.unpack_from("<4sII", data)
        require(magic == b"glTF" and version == 2, f"Unexpected GLB header: {filename}")
        expected_length = len(data) + (4 if filename == "GLB02_broken.glb" else 0)
        require(length == expected_length, f"Unexpected declared GLB length: {filename}")
        json_length, kind = struct.unpack_from("<I4s", data, 12)
        require(kind == b"JSON", "Missing JSON chunk")
        document = json.loads(data[20:20 + json_length])
        if filename == "GLB03_external.glb":
            require("uri" in document.get("extras", {}), "Missing metadata URI")
        if filename == "GLB04_invalid_accessor.glb":
            coordinate = struct.unpack_from("<f", data, 20 + json_length + 8)[0]
            require(math.isnan(coordinate), "Missing NaN vertex")
        print(f"PASS {filename}: expected construction (not a Khronos validation result)")


def verify_videos(directory):
    for filename, dimensions, duration in (
        ("VID01_valid.mp4", (640, 360), 2.0),
        ("VID04_over4k.mp4", (4096, 2160), 1.0),
    ):
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name,width,height:format=duration", "-of", "json",
            str(directory / filename),
        ], check=True, capture_output=True, text=True, timeout=30)
        report = json.loads(result.stdout)
        streams = [item for item in report["streams"] if item.get("codec_type") == "video"]
        require(len(streams) == 1, f"Expected one video stream: {filename}")
        stream = streams[0]
        require((stream["width"], stream["height"]) == dimensions, f"Unexpected resolution: {filename}")
        require(abs(float(report["format"]["duration"]) - duration) < 0.1, f"Unexpected duration: {filename}")
        print(f"PASS {filename}: {dimensions}, {report['format']['duration']} seconds")
    for filename in ("VID02_fake.mp4", "VID03_broken.mp4"):
        require((directory / filename).is_file(), f"Missing fixture: {filename}")
        result = subprocess.run(["ffprobe", "-v", "error", str(directory / filename)], capture_output=True, text=True, timeout=30)
        require(result.returncode != 0, f"Invalid video unexpectedly recognised: {filename}")
        print(f"PASS {filename}: FFprobe rejected fixture")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-videos", action="store_true", help="Verify images/GLBs before generating videos")
    parser.add_argument("--skip-khronos", action="store_true", help="Skip independent GLB validation; construction checks still run")
    args = parser.parse_args()
    verify_images(args.output)
    verify_glb_construction(args.output)
    if args.skip_khronos:
        print("SKIPPED Khronos validation; GLB validity has not been independently established.")
    else:
        subprocess.run(["node", str(Path(__file__).with_name("verify_glbs.cjs")), str(args.output.resolve())], check=True, timeout=120)
    if args.skip_videos:
        print("SKIPPED video verification.")
    else:
        verify_videos(args.output)
    write_manifest(args.output)
    files = sorted(fixture for fixture in args.output.iterdir() if fixture.suffix in {".jpg", ".jpeg", ".png", ".glb", ".mp4"})
    with (args.output / "checksums.sha256").open("w") as stream:
        for fixture in files:
            digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
            stream.write(f"{digest}  {fixture.name}\n")
    print("Recorded manifest.csv and checksums.sha256 for current files.")
    print("Requested fixture checks passed. Application tests remain manual; skipped checks remain unverified.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, struct.error, subprocess.SubprocessError) as error:
        raise SystemExit(f"Fixture verification failed: {error}") from error
