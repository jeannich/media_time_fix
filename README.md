Commands sample:


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
```
