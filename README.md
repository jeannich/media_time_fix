# media_time_fix

Fixes incorrect timestamps on photos and videos by applying time deltas to EXIF/metadata tags.
All changes are reversible — original values are preserved in sidecar files.

## Requirements

```
brew install exiftool
```

## Commands

```
python3 media_time_fix.py scan   <media_dir> --delta-dir <delta_dir>
python3 media_time_fix.py apply  <media_dir> --delta-dir <delta_dir>
python3 media_time_fix.py revert <media_dir> --delta-dir <delta_dir>
```

- **scan** — show detected cameras, matched rules, and files without a rule. Writes `scan_report.csv`.
- **apply** — write corrected timestamps to files, save originals in `.timedelta.json` sidecars.
  Running apply again after editing a spec re-applies the new delta from the original — no stacking.
  Add `--rename` to also prefix filenames with `YYYYMMDD_hhmmss_` so Finder/file managers sort by corrected time.
  Revert restores original filenames.
- **revert** — restore original timestamps from sidecars and delete them.

Add `--dry-run` / `-n` to any command to preview without writing.

## Delta spec files

Rules live in `delta_spec.json` files inside `<delta_dir>`, mirroring the media folder structure.
The root spec applies globally; a subfolder spec overrides it for files in that folder.

```json
{
  "cameras": {
    "Canon IXY DIGITAL 400": { "owner": "JP", "delta": "+08:04:50" },
    "DSC-T1":                 { "owner": "CJ", "delta": "-00:30:00" }
  },
  "files": {
    "DSC00042.JPG": { "delta": "+01:30:00" }
  },
  "patterns": [
    { "pattern": "MVI_*.AVI", "delta": "+08:04:50" }
  ]
}
```

**Priority** (highest wins): per-file `files` > glob `patterns` > `cameras`.
Within each type, the deepest (most specific) spec file wins.

**Delta format:** `+HH:MM:SS` or `-HH:MM:SS` or `+D HH:MM:SS` (D = whole days).

## Iterative delta tuning

1. Edit the `delta` value in the relevant `delta_spec.json`
2. Run `apply --rename` — files get corrected timestamps and sortable prefixed names
3. Browse in Finder (sort by name) using arrow keys
4. Repeat until timestamps look right — each re-apply adjusts from the original, never stacks







## Some command samples:
* Scan all files:
```
py media_time_fix.py     scan     JapanTrip                --delta-dir 'Japan_Trip time_delta'
```

* Scan only a subfolder files:
```
py media_time_fix.py    scan      JapanTrip/040131_Depart  --delta-dir 'Japan_Trip time_delta/040131_Depart'
```

* Apply changes:
```
py media_time_fix.py    apply    JapanTrip/040131_Depart   --delta-dir 'Japan_Trip time_delta/040131_Depart'
```

* Revert:
```
py media_time_fix.py    revert    JapanTrip/040131_Depart  --delta-dir 'Japan_Trip time_delta/040131_Depart'
```

Some debug commands:
-------------------------
```
brew install exiftool
brew install mediainfo

exiftool -s "JapanTrip/040131_Depart/100_0416.JPG"
mediainfo "JapanTrip/040719_HanabiOsakako/P1000381.MOV"






#BRICO commands:
exiftool -overwrite_original -DateTimeOriginal="2004:02:14 03:44:11" -CreateDate="2004:02:14 03:44:11" -Make="Canon" -Model="Canon IXY DIGITAL 400" '/home/chris/Desktop/japan_trip/JapanTrip/040226_Ikoma/PhotosJP 067.jpg'



exiftool -overwrite_original -DateTimeOriginal="2004:02:28 00:28:04" -CreateDate="2004:02:28 00:28:04" -Make="SONY" -Model="DSC-T1" '/home/chris/Desktop/japan_trip/JapanTrip/040227_karaoke/MOV00151.mp4'




ffmpeg -i  /home/chris/Desktop/japan_trip/JapanTrip/040502_GoldenWeek/MOV00309.MPG  -c copy   /home/chris/Desktop/japan_trip/JapanTrip/040502_GoldenWeek/MOV00309.mp4

exiftool -overwrite_original -DateTimeOriginal="2004:05:03 08:09:14+02:00" -CreateDate="2004:05:03 08:09:14+02:00" -Make="SONY" -Model="DSC-T1" /home/chris/Desktop/japan_trip/JapanTrip/040502_GoldenWeek/MOV00309.mp4





source_video="$HOME/Downloads/japan_trip/photos/040717_Hanabi/BouquetFinal.mpg"
ffmpeg -i  "$source_video"  -c copy   "$source_video".mp4

exiftool -overwrite_original \
  -DateTimeOriginal-="0:00:00 07:00:00" \
  -CreateDate-="0:00:00 07:00:00" \
  "$source_video" 2>&1
echo "--- After ---"
exiftool -s3 -DateTimeOriginal "$file"


exiftool -overwrite_original -Make="Canon" -Model="CanonMVI01" '/home/chris/Desktop/japan_trip/JapanTrip/040226_Ikoma/PhotosJP 067.jpg'
```
