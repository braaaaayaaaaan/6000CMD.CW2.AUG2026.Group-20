#!/usr/bin/env python3
"""Prepare local security-test inputs; never contact the DAM or its database."""

import argparse
import copy
import csv
import hashlib
import json
import random
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "generated"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def corrupt_png(source, destination):
    """Damage the zlib Adler-32 checksum while preserving every PNG chunk CRC."""
    raw = source.read_bytes()
    if not raw.startswith(PNG_SIGNATURE):
        raise ValueError("Source is not a PNG")
    chunks, compressed = [], bytearray()
    offset = len(PNG_SIGNATURE)
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack_from(">I", raw, offset)[0]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError("Truncated PNG data")
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:end - 4]
        chunks.append((kind, data))
        if kind == b"IDAT":
            compressed.extend(data)
        offset = end
    if len(compressed) < 6:
        raise ValueError("PNG has no complete zlib stream")
    compressed[-1] ^= 1
    result, inserted = bytearray(PNG_SIGNATURE), False
    for kind, data in chunks:
        if kind == b"IDAT":
            if inserted:
                continue
            data, inserted = bytes(compressed), True
        result.extend(png_chunk(kind, data))
    destination.write_bytes(result)


def write_glb(destination, document, binary):
    metadata = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    metadata += b" " * (-len(metadata) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    chunks = (
        struct.pack("<I4s", len(metadata), b"JSON") + metadata
        + struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    )
    destination.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


def make_images(output):
    image = Image.new("RGB", (640, 360), "#12334d")
    ImageDraw.Draw(image).text((24, 24), "DAM security test: valid image", fill="white")
    image.save(output / "IMG01_valid.jpg", quality=90)
    (output / "IMG02_valid.jpeg").write_bytes((output / "IMG01_valid.jpg").read_bytes())
    image.save(output / "IMG03_valid.png")
    (output / "IMG04_fake.png").write_text("This is plain text, not a PNG.\n")
    corrupt_png(output / "IMG03_valid.png", output / "IMG05_corrupted.png")
    Image.new("RGB", (5000, 2000), "#197c80").save(output / "IMG06_wide.png")
    # Seeded noise resists compression without creating an oversized pixel image.
    noise = random.Random(2026).randbytes(800 * 800 * 3)
    Image.frombytes("RGB", (800, 800), noise).save(output / "SHR01_over1MiB.png")
    if (output / "SHR01_over1MiB.png").stat().st_size <= 1024 * 1024:
        raise ValueError("Optional size-limit fixture must exceed 1 MiB")


def make_glbs(output):
    # Three float32 positions followed by three uint16 indices. No external files.
    binary = struct.pack("<9f3H", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
    document = {
        "asset": {"version": "2.0", "generator": "DAM security fixture script"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36, "target": 34962},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6, "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3,
             "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    write_glb(output / "GLB01_valid.glb", document, binary)
    broken = bytearray((output / "GLB01_valid.glb").read_bytes())
    struct.pack_into("<I", broken, 8, len(broken) + 4)
    (output / "GLB02_broken.glb").write_bytes(broken)
    external = copy.deepcopy(document)
    external["extras"] = {"uri": "https://example.invalid/fixture.bin"}
    write_glb(output / "GLB03_external.glb", external, binary)
    invalid = bytearray(binary)
    struct.pack_into("<I", invalid, 0, 0x7FC00000)  # A quiet NaN vertex coordinate.
    write_glb(output / "GLB04_invalid_accessor.glb", document, bytes(invalid))


def write_manifest(output):
    """Inventory existing known inputs, including videos if already generated."""
    descriptions = {
        "IMG01_valid.jpg": ("Ready / approved", "Genuine JPEG"),
        "IMG02_valid.jpeg": ("Ready / approved", "Identical JPEG bytes with .jpeg suffix"),
        "IMG03_valid.png": ("Ready / approved", "Genuine PNG"),
        "IMG04_fake.png": ("HTTP 400", "Plain text with .png suffix"),
        "IMG05_corrupted.png": ("Worker rejection", "Bad zlib checksum; valid PNG chunk CRCs"),
        "IMG06_wide.png": ("Ready / approved", "5000 x 2000 pixels"),
        "SHR01_over1MiB.png": ("HTTP 400 only with 1 MiB limit", "Valid PNG exceeding 1 MiB"),
        "GLB01_valid.glb": ("Ready / approved", "Self-contained triangle"),
        "GLB02_broken.glb": ("HTTP 400", "Declared length exceeds actual length by 4 bytes"),
        "GLB03_external.glb": ("HTTP 400", "URI in extras tests recursive DAM policy"),
        "GLB04_invalid_accessor.glb": ("Worker rejection", "NaN in POSITION accessor"),
        "VID01_valid.mp4": ("Ready / approved", "640 x 360; 2 seconds"),
        "VID02_fake.mp4": ("HTTP 400", "Plain text with .mp4 suffix"),
        "VID03_broken.mp4": ("HTTP 400", "Impossible first MP4 box length"),
        "VID04_over4k.mp4": ("Worker rejection", "4096 x 2160; 1 frame"),
    }
    with (output / "manifest.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["filename", "bytes", "sha256", "expected_application_result", "construction"])
        for name, (expected, description) in descriptions.items():
            fixture = output / name
            if fixture.is_file():
                content = fixture.read_bytes()
                writer.writerow([name, len(content), hashlib.sha256(content).hexdigest(), expected, description])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    make_images(args.output)
    make_glbs(args.output)
    write_manifest(args.output)
    print(f"Created 7 images, 4 GLBs and manifest.csv in {args.output.resolve()}")
    print("No uploads or application tests were performed.")


if __name__ == "__main__":
    main()
