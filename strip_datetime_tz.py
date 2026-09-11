#!/usr/bin/env python3
"""
strip_datetime_tz.py — Strip timezone offset from UserData:DateTimeOriginal in video files.

Only acts on files where:
  - UserData:DateTimeOriginal ends with a timezone offset (+HH:MM or -HH:MM)
  - AND at least one other date field (CreateDate, MediaCreateDate, TrackCreateDate,
    or XMP DateTimeOriginal) holds the identical datetime WITHOUT the offset

This confirms the offset is a spurious annotation, not a real UTC vs local difference.

Usage:
  python3 strip_datetime_tz.py <media_dir> [--dry-run] [--report FILE]

Options:
  --dry-run     Show what would change without writing anything
  --report FILE Write list of affected file paths to FILE
                (default: strip_datetime_tz_report.txt next to media_dir)
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = [
    "mov", "mp4", "mpg", "mpeg", "avi", "mkv", "mts", "m2ts", "3gp", "wmv",
]

TZ_RE = re.compile(r"^(.*)[+-]\d{2}:\d{2}$")


def exiftool_read_batch(paths: list[Path], chunk_size: int = 200) -> list[dict]:
    tags = [
        "-UserData:DateTimeOriginal",
        "-XMP-exif:DateTimeOriginal",
        "-QuickTime:CreateDate",
        "-QuickTime:MediaCreateDate",
        "-QuickTime:TrackCreateDate",
    ]
    results = []
    for i in range(0, len(paths), chunk_size):
        chunk = paths[i : i + chunk_size]
        r = subprocess.run(
            ["exiftool", "-j", "-a", "-G1", "-m"] + tags + [str(p) for p in chunk],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            results.extend(json.loads(r.stdout))
    return results


def find_media_files(media_dir: Path) -> list[Path]:
    files = []
    for p in sorted(media_dir.rglob("*")):
        if p.is_file() and p.suffix.lower().lstrip(".") in VIDEO_EXTENSIONS:
            files.append(p)
    return files


def check_file(entry: dict) -> tuple[str | None, str | None]:
    """
    Return (filepath, stripped_datetime) if the file qualifies, else (None, None).
    """
    filepath = entry.get("SourceFile", "")
    dto = entry.get("UserData:DateTimeOriginal", "")
    if not dto:
        return None, None

    m = TZ_RE.match(dto)
    if not m:
        return None, None

    stripped = m.group(1)

    reference_tags = [
        "QuickTime:CreateDate",
        "QuickTime:MediaCreateDate",
        "QuickTime:TrackCreateDate",
        "XMP-exif:DateTimeOriginal",
    ]
    for tag in reference_tags:
        val = entry.get(tag, "")
        if val and val == stripped:
            return filepath, stripped

    return None, None


def fix_file(filepath: str, stripped_dt: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [DRY-RUN] would set UserData:DateTimeOriginal → {stripped_dt}")
        return True
    r = subprocess.run(
        ["exiftool", "-overwrite_original", "-m",
         f"-UserData:DateTimeOriginal={stripped_dt}", filepath],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr.strip()}", file=sys.stderr)
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media_dir", help="Root folder to scan recursively")
    ap.add_argument("--dry-run", "-n", action="store_true")
    ap.add_argument("--report", default=None, metavar="FILE",
                    help="Path for the file-list report (default: next to media_dir)")
    args = ap.parse_args()

    media_dir = Path(args.media_dir).resolve()
    if not media_dir.is_dir():
        sys.exit(f"ERROR: not a directory: {media_dir}")

    report_path = Path(args.report) if args.report else media_dir.parent / "strip_datetime_tz_report.txt"

    print(f"Scanning: {media_dir}")
    files = find_media_files(media_dir)
    print(f"Found {len(files)} video file(s) — reading metadata…")

    entries = exiftool_read_batch(files)

    affected: list[tuple[str, str]] = []
    for entry in entries:
        fp, stripped = check_file(entry)
        if fp:
            affected.append((fp, stripped))

    print(f"Qualifying files: {len(affected)}")
    if not affected:
        print("Nothing to do.")
        return

    report_path.write_text("\n".join(fp for fp, _ in affected) + "\n")
    print(f"Report → {report_path}")

    changed = errors = 0
    for fp, stripped in affected:
        old_dto = next(
            e.get("UserData:DateTimeOriginal", "")
            for e in entries if e.get("SourceFile") == fp
        )
        print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}{Path(fp).name}")
        print(f"  {old_dto}  →  {stripped}")
        ok = fix_file(fp, stripped, args.dry_run)
        if ok:
            changed += 1
        else:
            errors += 1

    label = "Would change" if args.dry_run else "Changed"
    print(f"\nDone. {label}: {changed}, errors: {errors}")


if __name__ == "__main__":
    main()
