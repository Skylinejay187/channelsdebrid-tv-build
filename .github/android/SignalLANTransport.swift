#if !canImport(Network)
import Foundation
#if canImport(Android)
import Android
#elseif canImport(Glibc)
import Glibc
#endif

// SKIP @nobridge
final class SignalLANConnection: @unchecked Sendable {
    enum Completion { case contentProcessed((Error?) -> Void) }
    enum Failure: Error { case closed, io }
    let peer: String
    private let lock = NSLock()
    private var fd: Int32
    private let onClose: () -> Void
    private var callback = DispatchQueue.main
    private let io = DispatchQueue(label: "signal.lan.connection")
    init(fd: Int32, peer: String, onClose: @escaping () -> Void) { self.fd = fd; self.peer = peer; self.onClose = onClose }
    func start(queue: DispatchQueue) { callback = queue }
    private func descriptor() -> Int32 { lock.lock(); defer { lock.unlock() }; return fd < 0 ? -1 : dup(fd) }
    func cancel() {
        lock.lock(); let old = fd; fd = -1; lock.unlock()
        if old >= 0 { _ = shutdown(old, Int32(SHUT_RDWR)); _ = close(old); onClose() }
    }
    deinit { cancel() }
    func receive(minimumIncompleteLength: Int, maximumLength: Int, completion: @escaping (Data?, Bool?, Bool, Error?) -> Void) {
        io.async {
            let d = self.descriptor()
            guard d >= 0 else { self.callback.async { completion(nil, nil, true, Failure.closed) }; return }
            defer { _ = close(d) }
            var bytes = [UInt8](repeating: 0, count: max(1, min(maximumLength, 65536)))
            let count = bytes.withUnsafeMutableBytes { recv(d, $0.baseAddress, $0.count, 0) }
            let data = count > 0 ? Data(bytes.prefix(count)) : nil
            self.callback.async { completion(data, nil, count <= 0, count < 0 ? Failure.io : nil) }
        }
    }
    func send(content: Data, completion: Completion) {
        io.async {
            let d = self.descriptor()
            var failure: Error? = nil
            if d < 0 { failure = Failure.closed }
            else {
                defer { _ = close(d) }
                let ok = content.withUnsafeBytes { buf -> Bool in
                    var offset = 0
                    while offset < buf.count {
                        let n = GlibcOrAndroidSend(d, buf.baseAddress!.advanced(by: offset), buf.count - offset)
                        if n <= 0 { return false }; offset += n
                    }
                    return true
                }
                if !ok { failure = Failure.io }
            }
            let result = failure
            self.callback.async { if case .contentProcessed(let done) = completion { done(result) } }
        }
    }
}

private func GlibcOrAndroidSend(_ fd: Int32, _ bytes: UnsafeRawPointer, _ count: Int) -> Int {
#if canImport(Android)
    return Android.send(fd, bytes, count, Int32(MSG_NOSIGNAL))
#else
    return Glibc.send(fd, bytes, count, Int32(MSG_NOSIGNAL))
#endif
}

// SKIP @nobridge
final class SignalLANListener: @unchecked Sendable {
    struct Port { let rawValue: UInt16 }
    enum State { case ready, failed, waiting, cancelled }
    enum Failure: Error { case bindFailed }
    let port: Port?
    var stateUpdateHandler: ((State) -> Void)?
    var newConnectionHandler: ((SignalLANConnection) -> Void)?
    private let lock = NSLock()
    private var fd: Int32
    private var activePeers = 0
    private let worker = DispatchQueue(label: "signal.lan.listener")
    init(host: String) throws {
        guard SignalLANListener.privateIPv4(host) else { throw Failure.bindFailed }
#if canImport(Android)
        let d = socket(AF_INET, Int32(SOCK_STREAM) | Int32(SOCK_NONBLOCK), 0)
#else
        let d = socket(AF_INET, Int32(SOCK_STREAM.rawValue | SOCK_NONBLOCK.rawValue), 0)
#endif
        guard d >= 0 else { throw Failure.bindFailed }
        var addr = sockaddr_in(); addr.sin_family = sa_family_t(AF_INET); addr.sin_port = 0
        let valid = host.withCString { inet_pton(AF_INET, $0, &addr.sin_addr) }
        let bound = withUnsafePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(d, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) } }
        guard valid == 1, bound == 0, listen(d, 6) == 0 else { _ = close(d); throw Failure.bindFailed }
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let got = withUnsafeMutablePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(d, $0, &len) } }
        guard got == 0 else { _ = close(d); throw Failure.bindFailed }
        self.fd = d; self.port = Port(rawValue: UInt16(bigEndian: addr.sin_port))
    }
    private var active: Bool { lock.lock(); defer { lock.unlock() }; return fd >= 0 }
    func start(queue: DispatchQueue) {
        lock.lock(); let d = fd >= 0 ? dup(fd) : -1; lock.unlock()
        guard d >= 0 else { queue.async { self.stateUpdateHandler?(.failed) }; return }
        queue.async { if self.active { self.stateUpdateHandler?(.ready) } }
        worker.async {
            defer { _ = close(d) }
            while self.active {
                var event = pollfd(fd: d, events: Int16(POLLIN), revents: 0)
                let result = poll(&event, 1, 200)
                if result < 0 && errno != EINTR { break }
                if result <= 0 { continue }
                var addr = sockaddr_in(), len = socklen_t(MemoryLayout<sockaddr_in>.size)
                let client = withUnsafeMutablePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { accept(d, $0, &len) } }
                if client < 0 { continue }
                var host = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                guard inet_ntop(AF_INET, &addr.sin_addr, &host, socklen_t(host.count)) != nil else { _ = close(client); continue }
                let peer = String(cString: host)
                guard Self.privateIPv4(peer) else { _ = close(client); continue }
                var timeout = timeval(tv_sec: 8, tv_usec: 0)
                _ = setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
                _ = setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
                self.lock.lock()
                let allowed = self.fd >= 0 && self.activePeers < 8
                if allowed { self.activePeers += 1 }
                self.lock.unlock()
                guard allowed else { _ = close(client); continue }
                let connection = SignalLANConnection(fd: client, peer: peer) { [weak self] in
                    guard let self else { return }; self.lock.lock(); self.activePeers -= 1; self.lock.unlock()
                }
                queue.async { if self.active, let handler = self.newConnectionHandler { handler(connection) } else { connection.cancel() } }
            }
            if self.active { queue.async { self.stateUpdateHandler?(.failed) }; self.cancel() }
        }
    }
    func cancel() { lock.lock(); let old = fd; fd = -1; lock.unlock(); if old >= 0 { _ = shutdown(old, Int32(SHUT_RDWR)); _ = close(old) } }
    deinit { cancel() }
    static func privateIPv4(_ host: String) -> Bool {
        let o = host.split(separator: ".", omittingEmptySubsequences: false).compactMap { UInt8($0) }
        guard o.count == 4 else { return false }
        return o[0] == 10 || (o[0] == 172 && (16...31).contains(o[1])) || (o[0] == 192 && o[1] == 168) || (o[0] == 169 && o[1] == 254)
    }
    static func localAddress() -> String? {
        var list: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&list) == 0, let first = list else { return nil }; defer { freeifaddrs(list) }
        var node: UnsafeMutablePointer<ifaddrs>? = first
        while let current = node {
            defer { node = current.pointee.ifa_next }
            let iface = current.pointee
            let name = String(cString: iface.ifa_name)
            guard name.hasPrefix("wlan") || name.hasPrefix("eth") || name.hasPrefix("en"),
                  iface.ifa_flags & UInt32(IFF_UP) != 0, iface.ifa_flags & UInt32(IFF_RUNNING) != 0,
                  iface.ifa_flags & UInt32(IFF_LOOPBACK) == 0, let addr = iface.ifa_addr,
                  Int32(addr.pointee.sa_family) == AF_INET else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            guard getnameinfo(addr, socklen_t(MemoryLayout<sockaddr_in>.size), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 else { continue }
            let ip = String(cString: host); if privateIPv4(ip) { return ip }
        }
        return nil
    }
}
#endif
