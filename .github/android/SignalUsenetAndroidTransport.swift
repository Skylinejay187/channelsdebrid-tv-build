#if os(Android)
import Foundation
import NIOCore
import NIOPosix
import NIOSSL

// SKIP @nobridge
final class SignalUsenetTLSInbox: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = ByteBuffer
    private var queued = [Data]()
    private var waiting: EventLoopPromise<Data>?
    private var ended = false
    func channelRead(context: ChannelHandlerContext, data: NIOAny) {
        var buffer = unwrapInboundIn(data)
        guard let bytes = buffer.readBytes(length: buffer.readableBytes), !bytes.isEmpty else {
            if waiting != nil { context.read() }
            return
        }
        let data = Data(bytes)
        if let pending = waiting { waiting = nil; pending.succeed(data) }
        else { queued.append(data) }
    }
    func next(_ channel: Channel) -> EventLoopFuture<Data> {
        let promise = channel.eventLoop.makePromise(of: Data.self)
        channel.eventLoop.execute {
            if !self.queued.isEmpty { promise.succeed(self.queued.removeFirst()) }
            else if self.ended || self.waiting != nil { promise.fail(SignalNativeUsenetError.network) }
            else { self.waiting = promise; channel.read() }
        }
        return promise.futureResult
    }
    func channelInactive(context: ChannelHandlerContext) {
        ended = true
        let pending = waiting; waiting = nil
        pending?.fail(SignalNativeUsenetError.network)
        context.fireChannelInactive()
    }
    func errorCaught(context: ChannelHandlerContext, error: Error) {
        ended = true
        let pending = waiting; waiting = nil
        pending?.fail(error)
        context.close(promise: nil)
    }
}

// SKIP @nobridge
final class SignalUsenetTLSConnection: @unchecked Sendable {
    private static let group = MultiThreadedEventLoopGroup(numberOfThreads: 2)
    private let lock = NSLock()
    private let inbox = SignalUsenetTLSInbox()
    private let host: String
    private let port: Int
    private var channel: Channel?
    private var closed = false
    init(host: String, port: Int) { self.host = host; self.port = port }
    private func install(_ next: Channel) -> Bool {
        lock.lock(); defer { lock.unlock() }
        if closed { return false }
        channel = next
        return true
    }
    private func existing() throws -> Channel? {
        lock.lock(); defer { lock.unlock() }
        if closed { throw SignalNativeUsenetError.network }
        return channel
    }
    private static func trust() throws -> NIOSSLContext {
        let directory = "/system/etc/security/cacerts"
        let apex = "/apex/com.android.conscrypt/cacerts"
        let root = FileManager.default.fileExists(atPath: apex) ? apex : directory
        var certificates: [NIOSSLCertificate] = []
        for name in try FileManager.default.contentsOfDirectory(atPath: root) {
            let path = root + "/" + name
            if let certs = try? NIOSSLCertificate.fromPEMFile(path) { certificates += certs }
            else if let cert = try? NIOSSLCertificate(file: path, format: .der) { certificates.append(cert) }
        }
        guard !certificates.isEmpty else { throw SignalNativeUsenetError.network }
        var config = TLSConfiguration.makeClientConfiguration()
        config.certificateVerification = .fullVerification
        config.minimumTLSVersion = .tlsv12
        config.trustRoots = .certificates(certificates)
        return try NIOSSLContext(configuration: config)
    }
    private func connected() async throws -> Channel {
        if let current = try existing() { return current }
        let context = try Self.trust()
        let next = try await ClientBootstrap(group: Self.group)
            .connectTimeout(.seconds(12))
            .channelOption(ChannelOptions.autoRead, value: false)
            .channelInitializer { channel in
                do {
                    let tls = try NIOSSLClientHandler(context: context, serverHostname: self.host)
                    return channel.pipeline.addHandler(tls).flatMap { channel.pipeline.addHandler(self.inbox) }
                } catch { return channel.eventLoop.makeFailedFuture(error) }
            }
            .connect(host: host, port: port).get()
        guard install(next) else { next.close(promise: nil); throw SignalNativeUsenetError.network }
        return next
    }
    func cancel() {
        lock.lock(); closed = true; let current = channel; channel = nil; lock.unlock()
        current?.close(promise: nil)
    }
    deinit { cancel() }
    func send(_ data: Data) async throws {
        let channel = try await connected()
        var buffer = channel.allocator.buffer(capacity: data.count)
        buffer.writeBytes(data)
        try await channel.writeAndFlush(buffer).get()
    }
    func read() async throws -> Data {
        let channel = try await connected()
        return try await inbox.next(channel).get()
    }
}

// SKIP @nobridge
final class SignalUsenetAndroidSocket: @unchecked Sendable {
    private let tls: SignalUsenetTLSConnection?
    private let local: SignalLANConnection?
    private static let queue = DispatchQueue(label: "signal.usenet.android")
    private var buffer = Data()
    private var consumed = 0
    init(host: String, port: Int) { tls = SignalUsenetTLSConnection(host: host, port: port); local = nil }
    init(_ local: SignalLANConnection) { self.local = local; tls = nil }
    var connection: SignalUsenetAndroidSocket { self }
    func start() { local?.start(queue: Self.queue) }
    func cancel() { tls?.cancel(); local?.cancel() }
    deinit { cancel() }
    private func timed<T>(_ operation: () async throws -> T) async throws -> T {
        let timeout = DispatchWorkItem { [weak self] in self?.cancel() }
        Self.queue.asyncAfter(deadline: .now() + 12, execute: timeout)
        defer { timeout.cancel() }
        return try await withTaskCancellationHandler(operation: {
            try Task.checkCancellation()
            return try await operation()
        }, onCancel: { self.cancel() })
    }
    func send(_ data: Data) async throws {
        try await timed {
            if let tls = self.tls { try await tls.send(data); return }
            guard let local = self.local else { throw SignalNativeUsenetError.network }
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                local.send(content: data, completion: .contentProcessed { error in
                    if let error { continuation.resume(throwing: error) } else { continuation.resume() }
                })
            }
        }
    }
    private func read() async throws -> Data {
        try await timed {
            if let tls = self.tls { return try await tls.read() }
            guard let local = self.local else { throw SignalNativeUsenetError.network }
            return try await withCheckedThrowingContinuation { continuation in
                local.receive(minimumIncompleteLength: 1, maximumLength: 65536) { data, _, _, error in
                    if let data, !data.isEmpty { continuation.resume(returning: data) }
                    else { continuation.resume(throwing: error ?? SignalNativeUsenetError.network) }
                }
            }
        }
    }
    func line() async throws -> Data {
        let crlf = Data([13, 10])
        while true {
            let start = buffer.startIndex + consumed
            if let separator = buffer.range(of: crlf, in: start..<buffer.endIndex) {
                let line = buffer.subdata(in: start..<separator.lowerBound)
                consumed = separator.upperBound - buffer.startIndex
                return line
            }
            if consumed > 0 { buffer = buffer.subdata(in: start..<buffer.endIndex); consumed = 0 }
            guard buffer.count < 65536 else { throw SignalNativeUsenetError.invalid }
            buffer.append(try await read())
        }
    }
}
#endif
