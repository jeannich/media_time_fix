#!/usr/bin/env python3
"""
media_time_fix.py — Reversible time-delta corrections for photo/video metadata.

Commands:
  scan   <media_dir>               Show camera models, timestamps, and active spec chain
  apply  <media_dir>               Apply time deltas (writes sidecar files)
  revert <media_dir>               Restore original timestamps from sidecars

Options:
  --dry-run, -n          Show what would happen without making changes
  --global-spec FILE     Global spec JSON applied to all files (lowest priority)
  --local-spec-name NAME Filename auto-discovered in each subdirectory (default: delta_spec.json)
  --delta-dir DIR        Where to store sidecar files, mirroring media_dir structure
                         (default: <media_dir>/.time_deltas/)
  --ext LIST             Comma-separated extensions to process

Spec files and priority:
  Rules are resolved per file using a chain of specs, from lowest to highest priority:
    1. --global-spec file (if given)
    2. delta_spec.json in media_dir root (if present)
    3. delta_spec.json in each subdirectory down to the file's directory

  Within each rule type the most-specific (closest) spec wins:
    per-file override  >  glob pattern  >  camera model

Spec file format (JSON):
  {
    "cameras": {
      "Canon IXY DIGITAL 400": { "owner": "JP",   "delta": "+08:04:50" },
      "DSC-T1":                 { "owner": "CJ",   "delta": "-00:30:00" }
    },
    "files": {
      "DSCF0042.jpg": { "delta": "+01:30:00", "note": "per-file override" }
    },
    "patterns": [
      { "pattern": "VID_*.mp4", "delta": "+08:00:00" }
    ]
  }

Delta format: +HH:MM:SS  or  -HH:MM:SS  or  +D HH:MM:SS  (D = whole days)
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_EXTENSIONS = {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff",
    ".mov", ".mp4", ".avi", ".mts", ".m2ts", ".3gp", ".mkv", ".wmv",
}

SIDECAR_SUFFIX = ".timedelta.json"
LOCAL_SPEC_NAME = "delta_spec.json"

# exiftool date tags to read/write, in priority order
DATE_READ_TAGS = ["DateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate"]
DATE_WRITE_TAGS = ["DateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate"]


# ---------------------------------------------------------------------------
# exiftool helpers
# ---------------------------------------------------------------------------

def check_exiftool():
    r = subprocess.run(["exiftool", "-ver"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ERROR: exiftool not found. Install with:  brew install exiftool")


def exiftool_read(file_path):
    """Return the exiftool JSON dict for a single file."""
    return exiftool_read_batch([file_path]).get(str(file_path), {})


def exiftool_read_batch(file_paths: list[Path], chunk_size: int = 200) -> dict[str, dict]:
    """Read metadata for many files in one exiftool call. Returns {str(path): meta_dict}."""
    tags = [f"-{t}" for t in DATE_READ_TAGS] + ["-Model", "-Make", "-Information", "-Software", "-MIMEType"]
    results = {}
    for i in range(0, len(file_paths), chunk_size):
        chunk = file_paths[i:i + chunk_size]
        r = subprocess.run(
            ["exiftool", "-json", "-s"] + tags + [str(p) for p in chunk],
            capture_output=True, text=True
        )
        if r.returncode != 0 or not r.stdout.strip():
            continue
        for entry in json.loads(r.stdout):
            src = entry.get("SourceFile", "")
            if src:
                results[src] = entry
    return results


def exiftool_write(file_path, tag_values: dict) -> bool:
    """Write date tags to a file. Returns True on success, False on failure."""
    args = ["exiftool", "-overwrite_original", "-P"]
    for tag, val in tag_values.items():
        args.append(f"-{tag}={val}")
    args.append(str(file_path))
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  WARN: exiftool cannot write {file_path.suffix.upper()} metadata: {r.stderr.strip()}", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Date / delta helpers
# ---------------------------------------------------------------------------

EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"


def parse_exif_date(s: str) -> datetime | None:
    if not s:
        return None
    # strip trailing timezone offset if present (+09:00 etc.)
    s = re.sub(r"[+-]\d{2}:\d{2}$", "", s.strip())
    try:
        return datetime.strptime(s, EXIF_DATE_FMT)
    except ValueError:
        return None


def fmt_exif_date(dt: datetime) -> str:
    return dt.strftime(EXIF_DATE_FMT)


def parse_delta(s: str) -> timedelta:
    """Parse '+08:04:50', '-1 02:00:00', etc. into a timedelta."""
    s = s.strip()
    sign = -1 if s.startswith("-") else 1
    s = s.lstrip("+-")
    parts = s.split(" ")
    days = int(parts[0]) if len(parts) == 2 else 0
    h, m, sec = map(int, parts[-1].split(":"))
    return timedelta(seconds=sign * (days * 86400 + h * 3600 + m * 60 + sec))


def fmt_delta(td: timedelta) -> str:
    sign = "-" if td.total_seconds() < 0 else "+"
    total = int(abs(td.total_seconds()))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Sidecar helpers
# ---------------------------------------------------------------------------

def sidecar_path(file_path: Path, media_dir: Path, delta_dir: Path) -> Path:
    rel = file_path.relative_to(media_dir)
    return delta_dir / (str(rel) + SIDECAR_SUFFIX)


def get_camera_model(meta: dict) -> str:
    """Return the best available camera model string from exiftool metadata."""
    return (meta.get("Model") or meta.get("Make") or meta.get("Information") or meta.get("Software") or "").strip()


def get_original_date(meta: dict) -> tuple[str | None, str | None]:
    """Return (tag_name, value) for the first date tag found in meta."""
    for tag in DATE_READ_TAGS:
        val = meta.get(tag)
        if val:
            return tag, val
    return None, None


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_media_files(media_dir: Path, extensions: set) -> list[Path]:
    files = []
    for p in sorted(media_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in extensions:
            # skip anything inside a .time_deltas directory
            if ".time_deltas" not in p.parts:
                files.append(p)
    return files


# ---------------------------------------------------------------------------
# Spec chain — global → root-local → … → file-dir-local
# ---------------------------------------------------------------------------

def load_spec(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def build_spec_chain(
    file_path: Path,
    media_dir: Path,
    delta_dir: Path,
    global_spec: dict | None,
    local_spec_name: str,
) -> list[dict]:
    """
    Return specs ordered lowest → highest priority.
    Walks the delta tree from root down to the file's corresponding directory.
    A spec at delta_dir/X/ applies to all files under media_dir/X/ unless a
    deeper delta_dir/X/Y/ spec exists for those files.

    Example:
      delta_dir/delta_spec.json           → applies to everything
      delta_dir/folder_a/delta_spec.json  → overrides root for folder_a files only
    """
    chain = []
    if global_spec:
        chain.append(global_spec)

    rel = file_path.relative_to(media_dir)
    # Walk delta_dir root → file's parent directory (rel.parts[-1] is the filename)
    for i in range(len(rel.parts)):
        candidate = delta_dir.joinpath(*rel.parts[:i]) / local_spec_name
        if candidate.is_file():
            spec = load_spec(candidate)
            spec.setdefault("_source", str(candidate.relative_to(delta_dir.parent)))
            chain.append(spec)

    return chain


_PREFIX_RE = re.compile(r'^\d{8}_\d{6}_(.+)$')


def canonical_filename(name: str) -> str:
    """Strip YYYYMMDD_hhmmss_ prefix if present, so spec rules still match renamed files."""
    m = _PREFIX_RE.match(name)
    return m.group(1) if m else name


def prefixed_filename(dt: datetime, original_name: str) -> str:
    """Build YYYYMMDD_hhmmss_<original_name>, stripping any existing prefix first."""
    return dt.strftime("%Y%m%d_%H%M%S_") + canonical_filename(original_name)


def find_delta_for_file(
    file_path: Path,
    meta: dict,
    spec_chain: list[dict],
) -> tuple[str | None, str | None]:
    """
    Return (delta_str, source_label) using priority cascade.
    Within each rule type, the most-specific spec (last in chain) wins.
    Priority across types: per-file > glob pattern > camera model.
    """
    name = canonical_filename(file_path.name)   # strip date prefix before matching
    model = get_camera_model(meta)

    # Search from most-specific to least-specific for each rule type in order
    for spec in reversed(spec_chain):
        if name in spec.get("files", {}):
            return spec["files"][name]["delta"], f"file override in {_spec_label(spec)}"

    for spec in reversed(spec_chain):
        for pat in spec.get("patterns", []):
            if fnmatch.fnmatch(name, pat["pattern"]):
                return pat["delta"], f"pattern {pat['pattern']!r} in {_spec_label(spec)}"

    if model:
        for spec in reversed(spec_chain):
            entry = spec.get("cameras", {}).get(model)
            if entry and entry.get("delta"):
                return entry["delta"], f"camera {model!r} in {_spec_label(spec)}"

    return None, None


def _spec_label(spec: dict) -> str:
    return spec.get("_source", "spec")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scan(
    media_dir: Path,
    delta_dir: Path,
    extensions: set,
    global_spec: dict | None,
    local_spec_name: str,
):
    import csv

    files = find_media_files(media_dir, extensions)
    print(f"Scanning {len(files)} files in {media_dir}")

    local_specs = sorted(delta_dir.rglob(local_spec_name))
    if global_spec or local_specs:
        parts = []
        if global_spec:
            parts.append(f"global spec: {global_spec.get('_source', '--global-spec')}")
        if local_specs:
            parts.append(f"{len(local_specs)} spec file(s) in delta tree")
        print(f"Config: {', '.join(parts)}")
    print()

    # Group files by directory first so we can read and print folder by folder
    by_dir: dict[Path, list[Path]] = {}
    for f in files:
        dir_rel = f.parent.relative_to(media_dir) if f.parent != media_dir else Path(".")
        by_dir.setdefault(dir_rel, []).append(f)

    all_rows: list[dict] = []

    for dir_rel, dir_files in sorted(by_dir.items()):
        # Read metadata for this folder in one exiftool call
        folder_meta = exiftool_read_batch(dir_files)

        entries = []
        for f in dir_files:
            meta = folder_meta.get(str(f), {})
            model = get_camera_model(meta) or ""
            _, dt_val = get_original_date(meta)
            sc = sidecar_path(f, media_dir, delta_dir)
            chain = build_spec_chain(f, media_dir, delta_dir, global_spec, local_spec_name)
            delta_str, source = find_delta_for_file(f, meta, chain)
            entry = {
                "dir": dir_rel, "rel": f.relative_to(media_dir),
                "model": model, "dt": dt_val or "",
                "delta": delta_str or "", "source": source or "",
                "applied": sc.exists(),
            }
            entries.append(entry)
            all_rows.append(entry)

        # Print this folder immediately
        total = len(entries)
        n_applied = sum(1 for e in entries if e["applied"])
        n_no_rule = sum(1 for e in entries if not e["delta"] and not e["applied"])
        n_no_cam  = sum(1 for e in entries if not e["model"])

        chain = build_spec_chain(dir_files[0], media_dir, delta_dir, global_spec, local_spec_name)
        active_spec = chain[-1].get("_source", "?") if chain else None

        header = f"  {dir_rel}/  ({total} file(s)"
        if n_applied:
            header += f", {n_applied} already applied"
        header += f")  spec: {active_spec}" if active_spec else ")  NO SPEC"
        flags = []
        if n_no_rule:
            flags.append(f"{n_no_rule} without rule")
        if n_no_cam:
            flags.append(f"{n_no_cam} no camera detected")
        if flags:
            header += f"  [{', '.join(flags)}]"
        print(header)

        summary: dict[tuple, int] = {}
        for e in entries:
            key = (e["model"], e["delta"])          # raw model — "" when absent
            summary[key] = summary.get(key, 0) + 1

        for (model, delta), count in sorted(summary.items(), key=lambda x: (not x[0][1], x[0][0])):
            marker = "  " if delta else "!"
            display_model = model or "(no camera info)"
            print(f"    {marker}  {display_model:<50s}  {delta or 'no rule':>12}   {count} file(s)")
            if not model:
                for e in entries:
                    if not e["model"]:
                        print(f"           {e['rel']}")
        print()

    # # Write full per-file CSV report
    # report_path = delta_dir / "scan_report.csv"
    # delta_dir.mkdir(parents=True, exist_ok=True)
    # with open(report_path, "w", newline="", encoding="utf-8") as fh:
    #     writer = csv.DictWriter(fh, fieldnames=[
    #         "path", "camera", "recorded_date", "delta", "delta_source", "already_applied"
    #     ])
    #     writer.writeheader()
    #     for r in all_rows:
    #         writer.writerow({
    #             "path": str(r["rel"]),
    #             "camera": r["model"],
    #             "recorded_date": r["dt"],
    #             "delta": r["delta"],
    #             "delta_source": r["source"],
    #             "already_applied": "yes" if r["applied"] else "no",
    #         })
    # print(f"Full report: {report_path}  ({len(all_rows)} rows)")

    # Write camera log: files grouped by camera model
    by_camera: dict[tuple, list] = {}
    for r in all_rows:
        key = (r["model"] or "", r["delta"] or "")
        by_camera.setdefault(key, []).append(r["rel"])

    log_path = delta_dir / "scan_cameras.log"
    delta_dir.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        for (model, delta), files in sorted(by_camera.items(), key=lambda x: (not x[0][0], x[0][0])):
            display = model or "(no camera info)"
            fh.write(f"{display}  [delta: {delta or 'no rule'}]\n")
            for rel in files:
                fh.write(f"  {rel}\n")
            fh.write("\n")
    print(f"Camera log:  {log_path}")


def cmd_apply(
    media_dir: Path,
    delta_dir: Path,
    extensions: set,
    dry_run: bool,
    global_spec: dict | None,
    local_spec_name: str,
    rename: bool = False,
):
    files = find_media_files(media_dir, extensions)
    changed = skipped = errors = 0

    print("Reading metadata…")
    all_meta = exiftool_read_batch(files)

    for file_path in files:
        rel = file_path.relative_to(media_dir)
        sc = sidecar_path(file_path, media_dir, delta_dir)

        meta = all_meta.get(str(file_path), {})
        chain = build_spec_chain(file_path, media_dir, delta_dir, global_spec, local_spec_name)
        delta_str, source = find_delta_for_file(file_path, meta, chain)

        if not delta_str:
            continue

        # Sidecar exists → use stored originals; re-apply only if delta changed.
        original_tags = None
        original_filename = None
        if sc.exists():
            sidecar_data = json.loads(sc.read_text())
            prev_delta = sidecar_data.get("applied_delta")
            original_filename = sidecar_data.get("original_filename")
            if prev_delta == delta_str:
                skipped += 1
                continue
            original_tags = sidecar_data.get("original_tags", {})
            dt_raw = next((v for v in original_tags.values() if v), None)
            action = f"Re-apply (was {prev_delta})"
        else:
            original_filename = canonical_filename(file_path.name)
            _, dt_raw = get_original_date(meta)
            action = "Apply"

        if not dt_raw:
            print(f"SKIP (no date metadata): {rel}")
            skipped += 1
            continue

        dt_orig = parse_exif_date(dt_raw)
        if not dt_orig:
            print(f"SKIP (unparseable date '{dt_raw}'): {rel}")
            skipped += 1
            continue

        dt_new = dt_orig + parse_delta(delta_str)

        new_file_path = file_path
        if rename:
            new_name = prefixed_filename(dt_new, original_filename)
            new_file_path = file_path.parent / new_name

        suffix = f"  →  {new_file_path.name}" if rename and new_file_path != file_path else ""
        print(f"{'[DRY-RUN] ' if dry_run else ''}{action} {delta_str:>12s}  {rel}  ({source}){suffix}")
        print(f"  {fmt_exif_date(dt_orig)}  →  {fmt_exif_date(dt_new)}")

        if not dry_run:
            if original_tags is None:
                original_tags = {t: meta[t] for t in DATE_READ_TAGS if t in meta}
            new_dt_str = fmt_exif_date(dt_new)
            ok = exiftool_write(file_path, {t: new_dt_str for t in DATE_WRITE_TAGS})
            if not ok:
                errors += 1
                continue
            if rename and new_file_path != file_path:
                file_path.rename(new_file_path)
                if sc.exists():
                    sc.unlink()
                sc = sidecar_path(new_file_path, media_dir, delta_dir)
            sc.parent.mkdir(parents=True, exist_ok=True)
            sc.write_text(json.dumps({
                "file": str(new_file_path.relative_to(media_dir)),
                "original_filename": original_filename,
                "applied_delta": delta_str,
                "applied_from": source,
                "original_tags": original_tags,
                "applied_at": datetime.now().isoformat(),
            }, indent=2))

        changed += 1

    print(f"\nDone. {'Would change' if dry_run else 'Changed'}: {changed}, skipped: {skipped}, errors: {errors}")


def cmd_revert(media_dir: Path, delta_dir: Path, extensions: set, dry_run: bool):
    sidecars = list(delta_dir.rglob(f"*{SIDECAR_SUFFIX}"))
    if not sidecars:
        sys.exit(f"No sidecar files found in {delta_dir}")

    reverted = missing = 0
    for sc in sorted(sidecars):
        data = json.loads(sc.read_text())
        file_path = media_dir / data["file"]
        rel = Path(data["file"])

        if not file_path.exists():
            print(f"MISSING: {file_path}")
            missing += 1
            continue

        orig_tags = data.get("original_tags", {})
        if not orig_tags:
            print(f"SKIP (sidecar has no original tags): {rel}")
            continue

        original_filename = data.get("original_filename")
        restore_path = file_path.parent / original_filename if original_filename else None

        print(f"{'[DRY-RUN] ' if dry_run else ''}Revert  {rel}")
        for tag, val in orig_tags.items():
            print(f"  restore {tag} = {val}")
        if restore_path and restore_path != file_path:
            print(f"  rename  {file_path.name}  →  {restore_path.name}")

        if not dry_run:
            exiftool_write(file_path, orig_tags)
            if restore_path and restore_path != file_path:
                file_path.rename(restore_path)
            sc.unlink()

        reverted += 1

    print(f"\nDone. {'Would revert' if dry_run else 'Reverted'}: {reverted}, missing: {missing}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Reversible time-delta corrections for photo/video metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("command", choices=["scan", "apply", "revert"])
    p.add_argument("media_dir", help="Root folder containing media files")
    p.add_argument("--global-spec", default=None, metavar="FILE",
                   help="Global delta spec JSON (lowest priority, optional)")
    p.add_argument("--local-spec-name", default=LOCAL_SPEC_NAME, metavar="NAME",
                   help=f"Filename auto-discovered in each subdirectory (default: {LOCAL_SPEC_NAME})")
    p.add_argument("--dry-run", "-n", action="store_true", help="Print actions, make no changes")
    p.add_argument("--delta-dir", default=None, metavar="DIR",
                   help="Sidecar directory (default: <media_dir>/.time_deltas/)")
    p.add_argument("--ext", default=None, metavar="LIST",
                   help="Comma-separated file extensions to process")
    p.add_argument("--rename", action="store_true",
                   help="Prefix filenames with YYYYMMDD_hhmmss_ so Finder sorts by corrected time")

    args = p.parse_args()

    check_exiftool()

    media_dir = Path(args.media_dir).resolve()
    if not media_dir.is_dir():
        sys.exit(f"ERROR: {media_dir} is not a directory")

    delta_dir = Path(args.delta_dir).resolve() if args.delta_dir else media_dir / ".time_deltas"

    extensions = (
        {"." + e.strip().lstrip(".").lower() for e in args.ext.split(",")}
        if args.ext else DEFAULT_EXTENSIONS
    )

    global_spec = None
    if args.global_spec:
        global_spec = load_spec(Path(args.global_spec))
        global_spec["_source"] = args.global_spec  # for display in scan

    if args.command == "scan":
        cmd_scan(media_dir, delta_dir, extensions, global_spec, args.local_spec_name)

    elif args.command == "apply":
        if not global_spec and not list(delta_dir.rglob(args.local_spec_name)):
            sys.exit(
                f"ERROR: no spec found. Provide --global-spec or place a "
                f"{args.local_spec_name!r} file in the media directory tree."
            )
        cmd_apply(media_dir, delta_dir, extensions, args.dry_run, global_spec, args.local_spec_name, rename=args.rename)

    elif args.command == "revert":
        cmd_revert(media_dir, delta_dir, extensions, args.dry_run)


if __name__ == "__main__":
    main()
