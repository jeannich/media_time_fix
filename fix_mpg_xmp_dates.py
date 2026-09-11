#!/usr/bin/env python3
"""
fix_mpg_xmp_dates.py — Fix wrong dates in XMP sidecar files for MPG videos.

Extracts the correct date from the parent folder name (format: "YYYY MM DD ...")
and rewrites DateTimeOriginal / CreateDate in each .MPG.xmp sidecar.
Time defaults to 15:00:00 when unknown.

Also creates missing XMP sidecars for MPG files that have none.

Exiftool cannot write to MPG files directly — the XMP sidecar is the
authoritative metadata source for tools like Immich.

Usage:
  python3 fix_mpg_xmp_dates.py <media_dir> [--dry-run] [--time HH:MM:SS]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

FOLDER_DATE_RE = re.compile(r"^(\d{4})\D(\d{2})\D(\d{2})\b")
DEFAULT_TIME = "15:00:00"


def date_from_folder(folder_name: str) -> str | None:
    """Return 'YYYY:MM:DD' extracted from a folder name, or None."""
    m = FOLDER_DATE_RE.match(folder_name)
    return f"{m.group(1)}:{m.group(2)}:{m.group(3)}" if m else None


def exiftool_write_xmp(path: Path, dt: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    r = subprocess.run(
        ["exiftool", "-overwrite_original", "-m",
         f"-DateTimeOriginal={dt}",
         f"-CreateDate={dt}",
         str(path)],
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
    ap.add_argument("--time", default=DEFAULT_TIME, metavar="HH:MM:SS",
                    help=f"Default time when unknown (default: {DEFAULT_TIME})")
    args = ap.parse_args()

    media_dir = Path(args.media_dir).resolve()
    if not media_dir.is_dir():
        sys.exit(f"ERROR: not a directory: {media_dir}")

    # Collect all MPG files (with or without an existing sidecar)
    mpg_files = sorted(
        p for p in media_dir.rglob("*")
        if p.is_file() and p.suffix.upper() in {".MPG", ".MPEG"}
    )

    changed = skipped = created = errors = 0

    for mpg in mpg_files:
        xmp = mpg.parent / (mpg.name + ".xmp")
        date_str = date_from_folder(mpg.parent.name)

        if not date_str:
            print(f"SKIP (no date in folder name '{mpg.parent.name}'): {mpg.relative_to(media_dir)}")
            skipped += 1
            continue

        dt = f"{date_str} {args.time}"
        rel = xmp.relative_to(media_dir)

        if xmp.exists():
            print(f"{'[DRY-RUN] ' if args.dry_run else ''}UPDATE  {rel}  →  {dt}")
            ok = exiftool_write_xmp(xmp, dt, args.dry_run)
            if ok:
                changed += 1
            else:
                errors += 1
        else:
            # Create a minimal XMP sidecar from scratch
            print(f"{'[DRY-RUN] ' if args.dry_run else ''}CREATE  {rel}  →  {dt}")
            if not args.dry_run:
                # Write a bare file first so exiftool can populate it
                xmp.write_text("")
                ok = exiftool_write_xmp(xmp, dt, dry_run=False)
                if ok:
                    created += 1
                else:
                    xmp.unlink(missing_ok=True)
                    errors += 1
            else:
                created += 1

    label = "Would " if args.dry_run else ""
    print(f"\nDone. {label}updated: {changed}, {label}created: {created}, "
          f"skipped: {skipped}, errors: {errors}")


if __name__ == "__main__":
    main()
