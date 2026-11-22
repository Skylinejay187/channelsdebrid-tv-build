#!/usr/bin/env python3
"""Connect Skip Android ContentView to F143's original Unity RootView.

Edits apply only to staged copies inside the GitHub runner. The F143 archive
remains unchanged. Fail closed if the entry point cannot be identified.
"""
import argparse
import json
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument("--skip-project", type=Path, required=True)
p.add_argument("--report", type=Path, required=True)
a = p.parse_args()
module = a.skip_project / "Sources" / "SignalF143Fuse"
original = module / "F143Original" / "DebridChannelsTVOSApp.swift"
content_view = module / "ContentView.swift"
app = module / "SignalF143FuseApp.swift"
for file in (original, content_view, app):
    if not file.is_file():
        sys.exit(f"Missing Skip Fuse original or app entry: {file}")

swift = original.read_text(encoding="utf-8")
anchor = "@main\nstruct DebridChannelsTVOSApp: App {"
closing = "\n}\n\nprivate enum BluetoothVODMediaCommand"
if swift.count(anchor) != 1 or swift.count(closing) != 1:
    sys.exit("Could not safely identify original tvOS-only app entry")
if "struct RootView: View" not in swift or "RootView()" not in swift:
    sys.exit("Cannot find original Signal Unity RootView hierarchy")
if "ContentView()" not in app.read_text(encoding="utf-8"):
    sys.exit("Generated Skip Fuse app template changed; refusing placeholder integration")

swift = swift.replace(anchor, "#if os(tvOS)\n" + anchor, 1)
swift = swift.replace(
    closing,
    "\n}\n#endif // Original tvOS-specific app entry\n\nprivate enum BluetoothVODMediaCommand",
    1
)
original.write_text(swift, encoding="utf-8")

content_view.write_text("""import SwiftUI

// Android entry for Signal's ORIGINAL F143 Unity composition.
// Never replace with a newly designed screen or the generated sample.
struct ContentView: View {
    @StateObject var store = CatalogStore()
    @StateObject var unityCore = UnityAppCore.shared

    var body: some View {
        RootView()
            .environmentObject(store)
            .environmentObject(unityCore)
    }
}
""", encoding="utf-8")
result = {
    "real_app_root": "RootView()",
    "runtime_state": ["CatalogStore", "UnityAppCore.shared"],
    "android_entry": str(content_view),
    "original_tvos_entry": "Preserved under #if os(tvOS) in staged copy",
    "original_source_archive": "unchanged",
    "actual_compilation": "not yet verified"
}
a.report.parent.mkdir(parents=True, exist_ok=True)
a.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
