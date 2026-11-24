#!/usr/bin/env python3
"""Stage Android TV remote compatibility for tvOS SwiftUI-only View APIs.

Default D-pad focus movement remains managed by SkipUI/Jetpack Compose.
This build compatibility path does NOT reproduce Signal's custom tvOS focus
routing, Back, or Play/Pause callbacks. Those need a native KeyEvent bridge.
Never claim full TV remote feature parity from compilation alone.
"""
import argparse,json,re
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--source-root",required=True,type=Path)
p.add_argument("--report",required=True,type=Path)
a=p.parse_args()
root=a.source_root
files=sorted(root.rglob("*.swift"))
if len(files)<100:p.error("Original staged Signal source count unexpectedly small")
symbols={
 ".onMoveCommand":".signalAndroidMoveCommand",
 ".onExitCommand":".signalAndroidExitCommand",
 ".onPlayPauseCommand":".signalAndroidPlayPauseCommand",
 ".focusSection()":".signalAndroidFocusSection()",
 "MoveCommandDirection":"SignalAndroidMoveCommandDirection",
}
counts={k:0 for k in symbols}
for src in files:
    old=src.read_text(encoding="utf-8")
    new=old
    for target,replacement in symbols.items():
        n=new.count(target)
        counts[target]+=n
        new=new.replace(target,replacement)
    if new!=old:src.write_text(new,encoding="utf-8")
if counts[".onMoveCommand"]<30 or counts["MoveCommandDirection"]<15:
    p.error(f"Unexpectedly few tvOS remote API migrations: {counts}")
compat=root/"SignalAndroidTVRemoteCompatibility.swift"
if compat.exists():p.error("Remote compatibility file already exists")
compat.write_text(r"""import Foundation
import SwiftUI

// On Android the Compose focus system handles baseline D-pad movement
// between focusable views. Signal's custom Unity tvOS routing remains
// unimplemented until a scoped KeyEvent -> focused Swift handler bridge exists.
enum SignalAndroidMoveCommandDirection: Hashable, Sendable {
    case up, down, left, right
}

extension View {
    // Preserve source-level modifier and closure shapes without using APIs
    // marked unavailable on the Android SwiftUI compatibility surface.
    // Deliberately do not redirect Select taps as D-pad events.
    @MainActor
    func signalAndroidMoveCommand(
        perform action: ((SignalAndroidMoveCommandDirection) -> Void)?
    ) -> some View {
        self
    }

    @MainActor
    func signalAndroidExitCommand(perform action: (() -> Void)?) -> some View {
        self
    }

    @MainActor
    func signalAndroidPlayPauseCommand(perform action: (() -> Void)?) -> some View {
        self
    }

    @MainActor
    func signalAndroidFocusSection() -> some View {
        self
    }
}
""",encoding="utf-8")
a.report.parent.mkdir(parents=True,exist_ok=True)
report={
 "production_files_staged":len(files),
 "rewrites":counts,
 "standard_android_dpad_focus":"delegated to native Compose",
 "custom_unity_directional_navigation_implemented":False,
 "scoped_android_back_callback_implemented":False,
 "android_playpause_callback_implemented":False,
 "new_compat_source":compat.name,
 "source_archive_modified":False,
}
a.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
print(json.dumps(report,indent=2))
