#!/usr/bin/env python3
"""Inventory Apple-specific Swift framework usage before Skip Android build.
Reports all imported modules in the staged original Signal sources; never
silently drops a source file or pretends a replacement exists.
"""
import argparse, csv, json, re
from pathlib import Path
from collections import Counter

RISK = {
 "UIKit":"Compose/SkipFuseUI and Android Views",
 "AVFoundation":"Media3/ExoPlayer and Android media extractors",
 "AVKit":"Media3 PlayerView",
 "AetherEngine":"Android media playback implementation",
 "TVServices":"Android TV recommendations",
 "Security":"Android Keystore / encrypted credential storage",
 "Kingfisher":"Coil Android artwork loader",
 "ImageIO":"Android ImageDecoder",
 "CoreImage":"Android RenderEffect / GPU shaders",
 "CoreVideo":"Android MediaCodec and ImageReader",
 "QuartzCore":"Android animation",
 "MediaPlayer":"Media3 MediaSession",
 "UserNotifications":"Android NotificationManager",
 "CryptoKit":"Portable crypto or Android JCA",
 "Network":"Android ConnectivityManager / OkHttp",
 "Darwin":"Android libc / native API adapters",
 "TVVLCKit":"libVLC Android",
 "SQLite3":"Android SQLite / Room",
 "Combine":"Verify Skip support / Kotlin Flow adapter",
}
MUST_REVIEW = set(RISK)
rx = re.compile(r"(?m)^\s*(?:(?:@_implementationOnly|@_exported|@preconcurrency)\s+)?import\s+([A-Za-z_][A-Za-z_0-9]*)")
p = argparse.ArgumentParser()
p.add_argument("--source-root",required=True,type=Path)
p.add_argument("--report-dir",required=True,type=Path)
args = p.parse_args()
root=args.source_root.resolve()
files=sorted(root.rglob("*.swift"))
if len(files)<100: p.error(f"Unexpectedly few production Swift files: {len(files)}")
out=args.report_dir
out.mkdir(parents=True,exist_ok=True)
rows=[]; modules=Counter()
for file in files:
    source=file.read_text(encoding="utf-8",errors="replace")
    for module in sorted(set(rx.findall(source))):
        modules[module]+=1
        if module in MUST_REVIEW:
            rows.append({"source":str(file.relative_to(root)),"module":module,
            "android_replacement_candidate":RISK[module],
            "status":"REVIEW: do not disable app feature or discard source"})
with (out/"platform-import-inventory.csv").open("w",newline="",encoding="utf-8") as f:
    writer=csv.DictWriter(f,fieldnames=("source","module","android_replacement_candidate","status"))
    writer.writeheader();writer.writerows(rows)
result={
 "production_swift_files":len(files),
 "files_requiring_platform_review":len({r["source"] for r in rows}),
 "flagged_imports":len(rows),
 "module_file_counts":dict(sorted(modules.items())),
 "android_build_passed":False,
 "feature_parity_verified":False,
 "next_action":"Use adapters and availability guards by API rather than removing production source"
}
(out/"platform-import-summary.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps(result,indent=2))
