#!/usr/bin/env python3
"""
avi_to_mov.py — Losslessly remux AVI files to MOV (stream copy, no re-encoding).

Usage:
  python3 avi_to_mov.py <media_dir>

Converts all .avi / .AVI files found recursively under <media_dir>.
Metadata (dates, camera tags) is copied from the source AVI to the new MOV via exiftool.
Original AVI files are kept — delete them manually after verifying the MOV output.

Useful to support metadata editing as AVI files cannot have their metadata easily modified.
"""

import json
import subprocess
import sys
from pathlib import Path

COPY_TAGS = ["DateTimeOriginal", "CreateDate", "Make", "Model", "Software", "Information"]


def exiftool_read(path: Path) -> dict:
    r = subprocess.run(
        ["exiftool", "-json", "-s"] + [f"-{t}" for t in COPY_TAGS] + [str(path)],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    return json.loads(r.stdout)[0]


def exiftool_write(path: Path, tags: dict):
    if not tags:
        return
    args = ["exiftool", "-overwrite_original", "-P"]
    for tag, val in tags.items():
        args.append(f"-{tag}={val}")
    args.append(str(path))
    subprocess.run(args, capture_output=True)


def main():
    if len(sys.argv) < 2:
        sys.exit(f"Usage: {sys.argv[0]} <media_dir>")

    media_dir = Path(sys.argv[1])
    if not media_dir.is_dir():
        sys.exit(f"ERROR: {media_dir} is not a directory")

    avi_files = sorted(media_dir.rglob("*.avi")) + sorted(media_dir.rglob("*.AVI"))
    if not avi_files:
        print("No AVI files found.")
        return

    print(f"Found {len(avi_files)} AVI file(s) in {media_dir}\n")
    ok = skipped = fail = 0

    for src in avi_files:
        dst = src.with_suffix(".mov")
        if dst.exists():
            print(f"SKIP (already exists): {dst.relative_to(media_dir)}")
            skipped += 1
            continue

        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(src), "-c", "copy", str(dst)],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"FAIL {src.relative_to(media_dir)}: {r.stderr.strip()}", file=sys.stderr)
            dst.unlink(missing_ok=True)
            fail += 1
            continue

        # Copy metadata tags from source AVI that ffmpeg doesn't carry over
        src_meta = exiftool_read(src)
        tags_to_write = {t: v for t, v in src_meta.items() if t in COPY_TAGS and v}
        tags_to_write.pop("SourceFile", None)
        exiftool_write(dst, tags_to_write)

        copied = ", ".join(tags_to_write.keys()) or "none"
        print(f"OK   {src.relative_to(media_dir)}  →  {dst.name}  (copied: {copied})")
        ok += 1

    print(f"\nDone. converted: {ok}, skipped: {skipped}, failed: {fail}")
    if ok:
        print("Originals kept. Delete with:  find <media_dir> -iname '*.avi' -delete")


if __name__ == "__main__":
    main()
