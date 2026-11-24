#!/usr/bin/env python3
"""Temporary, narrowly scoped SkipFuseUI Button Swift 6 actor bridge workaround.

Only edits SwiftPM's local checkout of skip-fuse-ui, not Signal F143 originals
or upstream GitHub. Uses a read-only, Sendable holder for the bridge's existing
Java view reference to avoid @MainActor-isolated View stored properties in the
nonisolated SkipUIBridging interface. @unchecked Sendable is an explicit safety
assumption made by the existing JNI bridge, not proof of thread safety.

Refuses unknown/upstream changed source layouts.
"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--project-root", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
src = (args.project_root / ".build/checkouts/skip-fuse-ui/Sources/SkipSwiftUI/Controls/Button.swift")
if not src.is_file():
    parser.error(f"SkipFuseUI checkout missing: {src}")
original = src.read_text(encoding="utf-8")
old = """        nonisolated(unsafe) let Java_label: any SkipUI.View

        nonisolated init(Java_label: any SkipUI.View) {
            self.Java_label = Java_label
        }"""
new = """        // Android Swift 6.1: keep the JNI view reference in a nonactor holder.
        // The SkipUI bridge is responsible for all cross-thread usage.
        nonisolated let Java_labelBridge: _SignalButtonLabelBridge

        nonisolated init(Java_label: any SkipUI.View) {
            self.Java_labelBridge = _SignalButtonLabelBridge(Java_label)
        }"""
old_return = """    public var Java_view: any SkipUI.View {
        return Java_label
    }"""
new_return = """    public var Java_view: any SkipUI.View {
        return Java_labelBridge.value
    }"""
if original.count(old) != 2 or original.count(old_return) != 2:
    parser.error("Unexpected SkipFuseUI Button.swift revision; refusing unreviewed patch")
marker = "public struct ButtonStyleConfiguration {"
if original.count(marker) != 1:
    parser.error("Expected ButtonStyleConfiguration marker not found exactly once")
holder = """// Nonactor holder for a JNI-provided view reference. This mirrors the
// upstream nonisolated(unsafe) bridge contract; do not expose to app code.
// Actor/thread safety must be validated in the Android runtime.
internal final class _SignalButtonLabelBridge: @unchecked Sendable {
    nonisolated let value: any SkipUI.View
    nonisolated init(_ value: any SkipUI.View) { self.value = value }
}

"""
patched = original.replace(marker,holder + marker,1)
patched = patched.replace(old,new)
patched = patched.replace(old_return,new_return)
if patched.count("Java_labelBridge.value") != 2:
    parser.error("Bridge getter patch did not resolve both label views")
src.write_text(patched,encoding="utf-8")
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({
    "dependency":"skip-fuse-ui",
    "file":str(src),
    "old_label_definitions":2,
    "old_getters":2,
    "patched_label_definitions":patched.count("Java_labelBridge: _SignalButtonLabelBridge"),
    "patched_getters":patched.count("Java_labelBridge.value"),
    "original_signal_source_changed":False,
    "runtime_thread_safety_verified":False,
    "status":"compile workaround pending GitHub Swift Android validation"
},indent=2)+"\n",encoding="utf-8")
print("Patched 2 SkipFuseUI Button label holders (runtime validation outstanding)")
