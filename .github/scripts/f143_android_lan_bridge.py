#!/usr/bin/env python3
"""Port only the two TCP LAN services to the tested native socket transport."""
import argparse
import hashlib
import json
import re
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--original-source', type=Path, required=True)
p.add_argument('--source-root', type=Path, required=True)
p.add_argument('--transport', type=Path, required=True)
p.add_argument('--report', type=Path, required=True)
a = p.parse_args()
root = a.source_root
expected = {
    'SignalDiagnosticCenter.swift': '1532f929ec0e64620b77bd1832835a4d150f2d98900bf05c4d8f7d160b219315',
    'SignalPhoneSetupServer.swift': '90e4e97b87706d207bfcce3c8da00ac4d59d747cbceb0d1bdf7593746a36afbf',
    'SignalProtectedNetworkState.swift': '56969bbb818d4a0b4d48a681a0cd6a0aaf97f7767a38eb68452f12377db5dca4',
}
for filename, digest in expected.items():
    assert hashlib.sha256((a.original_source / filename).read_bytes()).hexdigest() == digest, f'Unaudited original source: {filename}'
assert hashlib.sha256(a.transport.read_bytes()).hexdigest() == '639cf0344819b59fbf7b3c215fcb3909d3ab596129111efebc5aa37bdaf3593a', 'Unaudited LAN transport'

def one(s, old, new):
    assert s.count(old) == 1, f'Expected one source anchor: {old[:100]!r}, got {s.count(old)}'
    return s.replace(old, new, 1)

def pattern(s, rx, new):
    out, count = re.subn(rx, lambda _: new, s, flags=re.S | re.M)
    assert count == 1, f'Expected one source region: {rx!r}, got {count}'
    return out

def lan_imports(s):
    s = one(s, 'import Network\n', '')
    if 'import SwiftUI\n' not in s:
        s = one(s, 'import Foundation\n', 'import Foundation\nimport SwiftUI\n')
    return s.replace('NWListener', 'SignalLANListener').replace('NWConnection', 'SignalLANConnection')

name = 'SignalDiagnosticCenter.swift'
s = lan_imports((root / name).read_text())
s = one(s, 'import os.signpost\n', '#if canImport(os.signpost)\nimport os.signpost\n#endif\n')
s = pattern(s, r'^            let parameters = NWParameters\.tcp\n.*?^            let next = try SignalLANListener\(using: parameters\)\n', '            let next = try SignalLANListener(host: ip)\n')
s = pattern(s, r'^    private func localAddress\(\) -> String \{\n.*?(?=^    private func serve\()', '    private func localAddress() -> String {\n        SignalLANListener.localAddress() ?? "127.0.0.1"\n    }\n\n')
s = one(s, 'No trusted LAN interface detected. Connect Apple TV to Wi-Fi or Ethernet.', 'No trusted LAN interface detected. Connect the TV to Wi-Fi or Ethernet.')
s = pattern(s, r'^    private static let performanceLog = OSLog[^\n]*\n', '#if canImport(os.signpost)\n    private static let performanceLog = OSLog(subsystem: "Signal", category: "Diagnostics")\n#endif\n')
s = pattern(s, r'^        monitoringTokens\.append\(center\.addObserver\(forName: UIApplication\.didReceiveMemoryWarningNotification.*?^        \}\)\n', '''#if canImport(UIKit)
        monitoringTokens.append(center.addObserver(forName: UIApplication.didReceiveMemoryWarningNotification, object: nil, queue: nil) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.metric("performance", "memory_warning_count", 1, state: "error")
#if canImport(os.signpost)
                os_signpost(.event, log: Self.performanceLog, name: "SignalMemoryWarning")
#endif
            }
        })
#endif
''')
s = one(s, '        os_signpost(.event, log: Self.performanceLog, name: "SignalCacheFrontierStall")\n', '#if canImport(os.signpost)\n        os_signpost(.event, log: Self.performanceLog, name: "SignalCacheFrontierStall")\n#endif\n')
s = pattern(s, r'^        metric\("performance", "thermal_level".*?^        metric\("performance", "low_power_mode"[^\n]*\n', '''#if canImport(Darwin)
        metric("performance", "thermal_level", Double(ProcessInfo.processInfo.thermalState.rawValue))
        metric("performance", "low_power_mode", ProcessInfo.processInfo.isLowPowerModeEnabled ? 1 : 0)
#endif
''')
assert not re.search(r'\bNW(?:Listener|Connection|Endpoint|Parameters)\b', s)
outputs = {name: s}

name = 'SignalPhoneSetupServer.swift'
s = lan_imports((root / name).read_text())
s = pattern(s, r'^            let parameters = NWParameters\.tcp\n.*?^            let next = try SignalLANListener\(using: parameters\)\n', '            let next = try SignalLANListener(host: host)\n')
s = one(s, 'Self.isLocalPeer(connection.endpoint)', 'Self.isLocalPeer(connection.peer)')
s = pattern(s, r'^    private static func isLocalPeer\(_ endpoint: NWEndpoint\) -> Bool \{\n.*?(?=^    deinit \{)', '''    private static func isLocalPeer(_ peer: String) -> Bool {
        SignalPhoneSetupHTTP.isPrivateIPv4(peer)
    }

    private static func localAddress() -> String? {
        guard let host = SignalLANListener.localAddress(), SignalPhoneSetupHTTP.isPrivateIPv4(host) else { return nil }
        return host
    }

''')
s = one(s, 'Connect Apple TV to your home Wi-Fi or Ethernet, then try again.', 'Connect the TV to your home Wi-Fi or Ethernet, then try again.')
assert not re.search(r'\bNW(?:Listener|Connection|Endpoint|Parameters)\b', s)
outputs[name] = s

name = 'SignalProtectedNetworkState.swift'
s = (root / name).read_text()
s = one(s, 'import Foundation\n', '''import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if canImport(Android)
import Android
#endif
''')
s = one(s, '    static func authorizeHome(_ ip: String, config: MediaFlowProxySnapshot, light: Bool, epoch: UInt64) -> Bool {\n', '''    static func authorizeHome(_ ip: String, config: MediaFlowProxySnapshot, light: Bool, epoch: UInt64) -> Bool {
#if os(Android)
        // Fail closed until a real Android connectivity-change monitor can revoke active routes.
        return false
#else
''')
s = one(s, '        homeVerifiedInEpoch = true\n        return true\n    }', '        homeVerifiedInEpoch = true\n        return true\n#endif\n    }')
outputs[name] = s

for name, source in outputs.items():
    (root / name).write_text(source)
(root / 'SignalLANTransport.swift').write_bytes(a.transport.read_bytes())
a.report.write_text(json.dumps({
    'staged_sources': sorted(outputs),
    'native_tcp_adapter': 'SignalLANTransport.swift',
    'diagnostic_report_protocol_preserved': True,
    'phone_setup_protocol_preserved': True,
    'android_lan_device_tested': False,
    'android_direct_home_route': 'fail closed until connectivity monitor is implemented',
    'android_native_usenet_tls': 'not implemented; original retained and still requires port',
    'original_archive_modified': False,
}, indent=2) + '\n')
