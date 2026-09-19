# Ghidra project scripts — Tsukorok S3 v4 firmware 5.5.12

Reproduces the named Ghidra project used for `research/briefs/tsukorok-firmware-5.5.12-rf-extraction.md`
(the firmware image itself is not in the repo). Tested with Ghidra 11.4.2 (bundled Xtensa module), Java 21.

```bash
G=/path/to/ghidra_11.4.2_PUBLIC/support/analyzeHeadless
D=tools/ghidra/tsukorok
$G proj tsukor -import tsukor_s3v4_5.5.12_en.bin -loader BinaryLoader -processor "Xtensa:LE:32:default" \
   -preScript LoadEsp.py -scriptPath $D -analysisTimeoutPerFile 3000
$G proj tsukor -process tsukor_s3v4_5.5.12_en.bin -noanalysis -postScript FixFuncs.py  -scriptPath $D
$G proj tsukor -process tsukor_s3v4_5.5.12_en.bin -noanalysis -postScript FixFuncs2.py -scriptPath $D
$G proj tsukor -process tsukor_s3v4_5.5.12_en.bin -noanalysis -postScript ApplyNames.py $D/symbols.csv -scriptPath $D
$G proj tsukor -process tsukor_s3v4_5.5.12_en.bin -noanalysis -readOnly -postScript PackGzf.py out.gzf -scriptPath $D
```

* `LoadEsp.py` — pre-script: rebuilds the memory map from the ESP32-S3 image header (DROM 0x3C0E0020,
  DRAM 0x3FC98370, IRAM 0x40374000 / 0x40377FE0, IROM 0x42000020, RTC 0x600FE000) and disassembles the entry point.
* `FixFuncs.py`, `FixFuncs2.py` — recover functions the auto-analysis misses by scanning for `entry a1,N`
  prologues (0x36 with low nibble 1) in the app and IRAM ranges (~190 functions).
* `ApplyNames.py` — applies `symbols.csv` (address, name, plate comment) as user-defined function names.
* `PackGzf.py` — packs the program into a `.gzf` archive (File > Import File in the GUI).
* `DumpAsm.py OUT addr…` — dumps the disassembly of the functions containing the given addresses.
* `ExportAll.py` — exports function list, string cross-references and decompiled C (edit the `OUT/` paths).

Ghidra names are `Class_method` style guesses from behaviour; the brief marks what is CONFIRMED vs INFERRED.
