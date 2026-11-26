#!/usr/bin/env python3
"""Narrow F143 Android guards for Apple-only catalog and Top Shelf APIs.

Only alters staged runner source. Does not implement Android media validation,
trailers, playback or Apple Top Shelf equivalents.
"""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--source-root", type=Path, required=True)
p.add_argument("--report", type=Path, required=True)
a = p.parse_args()
root = a.source_root.resolve()
catalog = root / "CatalogStore.swift"
app = root / "DebridChannelsTVOSApp.swift"
for path in (catalog, app):
    if not path.is_file():
        p.error(f"Missing staged source file {path}")

cs = catalog.read_text(encoding="utf-8")
app_source = app.read_text(encoding="utf-8")

def one(source, before, after, label):
    if source.count(before) != 1:
        p.error(f"{label} expected exactly once, got {source.count(before)}")
    return source.replace(before, after, 1)

cs = one(cs, "import AVFoundation\n", "#if canImport(AVFoundation)\nimport AVFoundation\n#endif\n", "AVFoundation import")
cs = one(
    cs,
    "import UserNotifications\n",
    "#if canImport(UserNotifications)\nimport UserNotifications\n#endif\n",
    "UserNotifications import"
)
# The episode alert branch is tvOS-only already, but Android also lacks
# UserNotifications. Reuse its in-app alert/log path, not an insecure shim
# that pretends an Android notification was scheduled.
episode_anchor = "        #if os(tvOS)\n        // tvOS does not expose UNMutableNotificationContent.title/body/sound"
episode_replacement = "        #if os(tvOS) || !canImport(UserNotifications)\n        // tvOS does not expose UNMutableNotificationContent.title/body/sound"
cs = one(cs, episode_anchor, episode_replacement, "episode notification platform guard")

original_fn = """    private func trailerFileHasCompleteAudio(_ fileURL: URL) async -> Bool {
        await Task.detached(priority: .utility) {
            let asset = AVURLAsset(url: fileURL)"""
replacement_fn = """    private func trailerFileHasCompleteAudio(_ fileURL: URL) async -> Bool {
        #if canImport(AVFoundation)
        await Task.detached(priority: .utility) {
            let asset = AVURLAsset(url: fileURL)"""
cs = one(cs, original_fn, replacement_fn, "trailer audio validation start")
end_fn = """            return coverage >= 0.98 && audioEnd >= requiredEnd - 1.25
        }.value
    }"""
replacement_end = """            return coverage >= 0.98 && audioEnd >= requiredEnd - 1.25
        }.value
        #else
        // Android: never claim trailer audio is complete without an actual
        // Android Media3-based media validator.
        return false
        #endif
    }"""
cs = one(cs, end_fn, replacement_end, "trailer audio validation end")
app_source = one(
    app_source,
    "import AVKit\n",
    "#if canImport(AVKit)\nimport AVKit\n#endif\n",
    "Apple AVKit import"
)
app_source = one(
    app_source,
    "import TVServices\n",
    "#if canImport(TVServices)\nimport TVServices\n#endif\n",
    "tvOS Top Shelf import")
app_source = one(
    app_source,
    "        TVTopShelfContentProvider.topShelfContentDidChange()\n",
    "        #if canImport(TVServices)\n        TVTopShelfContentProvider.topShelfContentDidChange()\n        #endif\n",
    "tvOS Top Shelf invalidation"
)
catalog.write_text(cs, encoding="utf-8")
app.write_text(app_source, encoding="utf-8")
a.report.parent.mkdir(parents=True, exist_ok=True)
report = {
    "status": "staged Swift compatibility patch applied",
    "catalog_avfoundation_import_guarded": True,
    "trailer_audio_android_validated": False,
    "android_trailer_fallback": "reject until Android media validator exists",
    "tvos_top_shelf_guarded": True,
    "app_avkit_import_guarded": True,
    "android_notifications_implemented": False,
    "usernotifications_import_guarded": True,
    "original_f143_zip_modified": False,
}
a.report.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
print(json.dumps(report, indent=2))
