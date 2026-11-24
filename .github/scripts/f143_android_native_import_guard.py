#!/usr/bin/env python3
"""Guard native Apple framework imports in staged Signal source.

This compilation bridge does not implement Android Aether playback or
encrypted Android credential storage. It preserves the Apple implementations
and fails closed for Android credential writes until a secure bridge exists.
"""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--source-root", type=Path, required=True)
p.add_argument("--report", type=Path, required=True)
a = p.parse_args()
root = a.source_root.resolve()
aether = root / "AetherPlaybackBridge/AetherPlaybackBridge.swift"
backup = root / "BackupStreamingClient.swift"
for src in (aether, backup):
    if not src.is_file():
        p.error("Required original Swift source absent: " + str(src))

original_aether = aether.read_text(encoding="utf-8")
prefix = "#if !TARGET_OS_ANDROID\n"
suffix = "\n#endif // !TARGET_OS_ANDROID — Apple AetherPlaybackBridge\n"
if not original_aether.startswith(prefix) or not original_aether.rstrip().endswith(suffix.strip()):
    p.error("Unexpected Aether guard shape; source changed: " + str(aether))
# The host Swift phase also compiles a bridged target. Check the actual
# availability of the native dependency, not only a compile-time platform flag.
aether.write_text(
    "#if canImport(AetherEngine) && canImport(UIKit) && canImport(AVFoundation)\n"
    + original_aether[len(prefix):].removesuffix(suffix)
    + "\n#endif // Native Aether and UIKit available\n",
    encoding="utf-8"
)

original = backup.read_text(encoding="utf-8")
expected_import = "import Foundation\nimport Security\n#if canImport(FoundationNetworking)"
if not original.startswith(expected_import):
    p.error("BackupStreamingClient import layout changed")
original = original.replace(
    "import Foundation\nimport Security\n",
    "import Foundation\n#if canImport(Security)\nimport Security\n#endif\n", 1
)
start = original.find("enum BackupStreamingCredentialStore {")
end = original.find("\nstruct BackupStreamingAccountStatus:", start)
if start < 0 or end < 0:
    p.error("Could not isolate BackupStreamingCredentialStore safely")
credential = original[start:end]
if "SecItemCopyMatching" not in credential or "normalizedCookieValue" not in credential:
    p.error("Unexpected Keychain implementation, refusing change")

fallback = r"""#else
// Android compile fallback: NOT a substitute for Android Keystore.
// Never store a credential unencrypted or pretend persistence succeeded.
enum BackupStreamingCredentialStore {
    static func readFebBoxCookie() -> String { "" }

    @discardableResult
    static func saveFebBoxCookie(_ raw: String) -> Bool { false }

    @discardableResult
    static func purgeForFreshInstall() -> Bool { true }

    static func normalizedCookieValue(_ raw: String) -> String {
        var clean = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if clean.lowercased().hasPrefix("ui=") { clean.removeFirst(3) }
        if let semicolon = clean.firstIndex(of: ";") {
            clean = String(clean[..<semicolon])
        }
        return clean.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
#endif // canImport(Security)
"""
original = original[:start] + "#if canImport(Security)\n" + credential + "\n" + fallback + original[end:]
backup.write_text(original, encoding="utf-8")
a.report.parent.mkdir(parents=True, exist_ok=True)
result = {
    "aether_native_dependency_guard": "canImport(AetherEngine) && canImport(UIKit) && canImport(AVFoundation)",
    "backup_keychain_guard": "canImport(Security)",
    "android_secure_storage_implemented": False,
    "android_playback_implemented": False,
    "original_zip_modified": False,
}
a.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
