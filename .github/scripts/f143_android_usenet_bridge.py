#!/usr/bin/env python3
"""Stage native Android Usenet TLS, encrypted credentials and loopback HTTP."""
import hashlib, sys
from pathlib import Path
root=Path(sys.argv[1])
original=Path(sys.argv[2])/"SignalNativeUsenet.swift"
assert hashlib.sha256(original.read_bytes()).hexdigest()=="60b14757e12298b7f73da156dccf2c790db6a38fb1acc6009fc9bdf073521c8f"
p=root/"SignalNativeUsenet.swift"
s=p.read_text()
def one(old,new):
    global s
    assert s.count(old)==1, (old[:100],s.count(old))
    s=s.replace(old,new,1)
one("import Network\nimport Security", "#if os(Android)\nimport FoundationXML\nimport SkipKeychain\n#else\nimport Network\nimport Security\n#endif")
one("    private static let query:", """#if os(Android)
    static func read() -> Self {
        guard let encoded = try? Keychain.shared.string(forKey: "Signal.NativeUsenet.news-server"),
              let data = Data(base64Encoded: encoded),
              let value = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        return value
    }
    func save() -> Bool {
        do {
            let data = try JSONEncoder().encode(self)
            try Keychain.shared.set(data.base64EncodedString(), forKey: "Signal.NativeUsenet.news-server")
            return true
        } catch { return false }
    }
#else
    private static let query:""")
one("    var configured:", "#endif\n    var configured:")
one("    func endpoint() throws -> (NWEndpoint.Host, NWEndpoint.Port) {", """#if os(Android)
    func endpoint() throws -> (String, UInt16) {
        let server = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty,
              server.utf8.allSatisfy({ (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 46 || $0 == 45 }),
              let value = UInt16(port.trimmingCharacters(in: .whitespacesAndNewlines)), value > 0,
              !username.isEmpty, !password.isEmpty,
              !username.utf8.contains(where: { $0 < 32 || $0 == 127 }),
              !password.utf8.contains(where: { $0 < 32 || $0 == 127 }) else { throw SignalNativeUsenetError.configuration }
        return (server, value)
    }
#else
    func endpoint() throws -> (NWEndpoint.Host, NWEndpoint.Port) {""")
one("        return (NWEndpoint.Host(server), endpointPort)\n    }", "        return (NWEndpoint.Host(server), endpointPort)\n    }\n#endif")
one("private final class SignalUsenetSocket {", "#if os(Android)\nprivate typealias SignalUsenetSocket = SignalUsenetAndroidSocket\nprivate typealias SignalUsenetListener = SignalLANListener\nprivate typealias SignalUsenetPeer = SignalLANConnection\n#else\nprivate typealias SignalUsenetListener = NWListener\nprivate typealias SignalUsenetPeer = NWConnection\nprivate final class SignalUsenetSocket {")
one("private final class SignalNNTPReader {", "#endif\nprivate final class SignalNNTPReader {")
one("        let tls = NWProtocolTLS.Options()", "#if os(Android)\n        socket = SignalUsenetSocket(host: host, port: Int(port))\n#else\n        let tls = NWProtocolTLS.Options()")
one("        socket.start()\n    }\n\n    func login", "#endif\n        socket.start()\n    }\n\n    func login")
one("        let listener: NWListener", "        let listener: SignalUsenetListener")
one("            let parameters = NWParameters.tcp", "#if os(Android)\n            listener = try SignalLANListener(host: \"127.0.0.1\", loopbackOnly: true)\n#else\n            let parameters = NWParameters.tcp")
one("            listener = try NWListener(using: parameters)", "            listener = try NWListener(using: parameters)\n#endif")
one("private func accept(_ connection: NWConnection)", "private func accept(_ connection: SignalUsenetPeer)")
p.write_text(s)
# Extend existing listener without opening private LAN services to the loopback mode.
p=root/"SignalLANTransport.swift"
s=p.read_text()
one("    private var activePeers = 0", "    private var activePeers = 0\n    private let loopbackOnly: Bool")
one("    init(host: String) throws {\n        guard SignalLANListener.privateIPv4(host) else", "    init(host: String, loopbackOnly: Bool = false) throws {\n        self.loopbackOnly = loopbackOnly\n        guard loopbackOnly ? host == \"127.0.0.1\" : SignalLANListener.privateIPv4(host) else")
one("guard Self.privateIPv4(peer) else", "guard self.loopbackOnly ? peer == \"127.0.0.1\" : Self.privateIPv4(peer) else")
p.write_text(s)
(root/"SignalUsenetAndroidTransport.swift").write_bytes(Path(".github/android/SignalUsenetAndroidTransport.swift").read_bytes())
package=Path(sys.argv[3])
s=package.read_text()
s+='\npackage.dependencies.append(.package(url: "https://github.com/apple/swift-nio.git", from: "2.80.0"))\n'
s+='package.dependencies.append(.package(url: "https://github.com/apple/swift-nio-ssl.git", exact: "2.36.0"))\n'
s+='package.dependencies.append(.package(url: "https://github.com/skiptools/skip-keychain.git", branch: "main"))\n'
for name, pkg in [("NIOCore","swift-nio"),("NIOPosix","swift-nio"),("NIOSSL","swift-nio-ssl"),("SkipKeychain","skip-keychain")]:
    s+=f'package.targets.first(where: {{ $0.name == "SignalF143Fuse" }})!.dependencies.append(.product(name: "{name}", package: "{pkg}"))\n'
package.write_text(s)
print("Staged Android NNTP TLS, encrypted credential store, and loopback-only HTTP listener; original unchanged.")
