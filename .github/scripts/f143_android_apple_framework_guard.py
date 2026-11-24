#!/usr/bin/env python3
"""Guard the tvOS-only Aether UIView host in the staged Android Swift build.

AetherPlaybackHostView subclasses UIKit.UIView and embeds AetherEngine.
Neither is an Android implementation. This guard does NOT provide video
playback; Android Media3/ExoPlayer integration remains required.
The original uploaded source archive is never modified.
"""
from pathlib import Path
import argparse, json, sys

parser = argparse.ArgumentParser()
parser.add_argument("--source-root", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
a = parser.parse_args()
root = a.source_root.resolve()
source = root / "AetherPlaybackBridge" / "AetherPlaybackBridge.swift"
if not source.is_file():
    sys.exit(f"Missing expected Aether bridge: {source}")
data = source.read_text(encoding="utf-8")
expected = ("import Foundation\nimport UIKit\nimport AVFoundation\n"
            "import Combine\n@_implementationOnly import AetherEngine")
if not data.startswith(expected):
    sys.exit("Aether bridge imports changed: refusing unchecked transformation")
if not all(x in data for x in ("class AetherPlaybackHostView: UIView", "AetherEngine")):
    sys.exit("Aether bridge implementation changed: refusing unchecked transformation")
if data.startswith("#if !os(Android)"):
    sys.exit("Android platform guard already applied unexpectedly")
# Swift for Android does not provide UIKit, AVFoundation, or AetherEngine.
# Retain the entire original Apple-only source for tvOS builds.
source.write_text("#if !os(Android)\n" + data.rstrip("\n") + "\n#endif // !os(Android) — Apple AetherPlaybackBridge\n", encoding="utf-8")
report = {
    "file": str(source.relative_to(root)),
    "action": "Apple-only file excluded from Android Swift compilation",
    "reason": "UIKit UIView subclass and unavailable AetherEngine/AVFoundation",
    "original_bytes": len(data.encode("utf-8")),
    "original_archive_changed": False,
    "android_playback_implemented": False,
}
a.report.parent.mkdir(parents=True, exist_ok=True)
a.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
