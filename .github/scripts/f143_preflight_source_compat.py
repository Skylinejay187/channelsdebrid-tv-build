#!/usr/bin/env python3
"""Dry-run the Android source transformation pipeline before installing Skip.

Applies the same source compatibility scripts to a disposable copy of the
uploaded ORIGINAL Swift sources. No GitHub archive or tvOS source is mutated.
Swift syntax parsing is NOT typechecking or evidence of a working Android APK.
"""
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--original-source", type=Path, required=True)
p.add_argument("--scripts-dir", type=Path, required=True)
p.add_argument("--report-dir", type=Path, required=True)
a = p.parse_args()
original = a.original_source.resolve()
scripts = a.scripts_dir.resolve()
report = a.report_dir.resolve()
report.mkdir(parents=True, exist_ok=True)
source_files = sorted(original.rglob("*.swift"))
if len(source_files) < 100:
    p.error(f"Expected complete Signal source, got {len(source_files)} Swift files")
stages = [
    "f143_android_coil_artwork_bridge.py",
    "f143_android_artwork_runtime_batch.py",
    "f143_android_tv_remote_compat.py",
    "f143_android_apple_framework_guard.py",
    "f143_android_native_import_guard.py",
    "f143_android_catalog_framework_bridge.py",
    "f143_android_final_source_fixes.py",
]
results = []
with tempfile.TemporaryDirectory(prefix="f143-android-preflight-") as tmp:
    dst = Path(tmp) / "F143Original"
    shutil.copytree(original, dst)
    for index, script_name in enumerate(stages, 1):
        tool = scripts / script_name
        if not tool.is_file():
            raise SystemExit(f"Missing required compatibility script {tool}")
        diagnostic = report / f"preflight-stage-{index:02}-{tool.stem}.json"
        completed = subprocess.run(
            [sys.executable, str(tool), "--source-root", str(dst),
             "--report", str(diagnostic)],
            capture_output=True, text=True
        )
        results.append({
            "stage": script_name,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-3000:],
            "stderr": completed.stderr[-3000:],
        })
        (report / "source-patch-preflight.json").write_text(
            json.dumps({"original_source_count":len(source_files),"stages":results,
                        "all_passed":False}, indent=2) + "\n",
            encoding="utf-8"
        )
        if completed.returncode:
            print(f"::error::Android source preflight failed at {script_name}")
            print(completed.stderr[-3000:] or completed.stdout[-3000:])
            raise SystemExit(completed.returncode)
    transformed = sorted(dst.rglob("*.swift"))
    if len(transformed) < len(source_files):
        raise SystemExit("Android patch pipeline lost original Swift source files")
    parse = subprocess.run(["swiftc", "-frontend", "-parse", *map(str, transformed)],
                           capture_output=True, text=True)
    (report / "source-patch-preflight-swift-parse.txt").write_text(
        parse.stdout + parse.stderr, encoding="utf-8")
    if parse.returncode:
        print("::error::Source transformations produced invalid Swift syntax")
        print(parse.stderr[-5000:])
        raise SystemExit(parse.returncode)
    # Test manifest compatibility separately; Skip initialization has not
    # happened yet. Use realistic Swift 5 and Swift 6 package manifests.
    mode_tool = scripts / "f143_android_swift_language_mode.py"
    for tools_version in ("5.9", "6.0"):
        project = Path(tmp) / ("Package-" + tools_version)
        project.mkdir()
        (project / "Package.swift").write_text(
            f'// swift-tools-version: {tools_version}\nimport PackageDescription\n'
            'let package = Package(name: "Preflight", targets: [])\n',
            encoding="utf-8"
        )
        mode = subprocess.run([sys.executable, str(mode_tool),
                               "--project-root", str(project),
                               "--report", str(report / f"manifest-{tools_version}.json")],
                              capture_output=True, text=True)
        if mode.returncode:
            print("::error::Swift package language-mode fixture failed",
                  tools_version, mode.stderr)
            raise SystemExit(mode.returncode)
        expected = "swiftLanguageModes" if tools_version.startswith("6") else "swiftLanguageVersions"
        if expected not in (project/"Package.swift").read_text():
            raise SystemExit(f"Language-mode fixture didn't set {expected}")
result = {
    "original_source_count":len(source_files),
    "transformed_source_count":len(transformed),
    "stages":results,
    "swift_parse_passed":True,
    "language_mode_fixtures_passed":["5.9","6.0"],
    "all_passed":True,
    "full_swift_typecheck_completed":False,
    "android_apk_verified":False,
    "original_zip_modified":False,
}
(report/"source-patch-preflight.json").write_text(json.dumps(result,indent=2)+"\n",
                                                  encoding="utf-8")
print(f"All {len(stages)} source patches and {len(transformed)} Swift syntax checks passed")
