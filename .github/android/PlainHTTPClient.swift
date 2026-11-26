import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class PlainHTTPClient {
    enum PlainHTTPError: Error {
        case invalidURL, missingHost, connectionFailed, badResponse, timeout
    }
    private final class RequestState: NSObject, URLSessionDataDelegate, @unchecked Sendable {
        typealias Output = (data: Data, statusCode: Int)
        let lock = NSLock()
        let maxBytes: Int
        var continuation: CheckedContinuation<Output, Error>?
        var session: URLSession?
        var finished = false
        var buffer = Data()
        var statusCode = 0
        init(maxBytes: Int) { self.maxBytes = maxBytes }
        func start(_ request: URLRequest, timeout: TimeInterval, continuation: CheckedContinuation<Output, Error>) {
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = timeout
            config.timeoutIntervalForResource = timeout
            config.urlCache = nil
            config.httpCookieStorage = nil
            config.urlCredentialStorage = nil
            let queue = OperationQueue()
            queue.maxConcurrentOperationCount = 1
            let session = URLSession(configuration: config, delegate: self, delegateQueue: queue)
            lock.lock()
            if finished {
                lock.unlock()
                session.invalidateAndCancel()
                continuation.resume(throwing: CancellationError())
                return
            }
            self.session = session
            self.continuation = continuation
            let task = session.dataTask(with: request)
            lock.unlock()
            task.resume()
        }
        func finish(_ result: Result<Output, Error>) {
            lock.lock()
            guard !finished else { lock.unlock(); return }
            finished = true
            let continuation = self.continuation
            let session = self.session
            self.continuation = nil
            self.session = nil
            lock.unlock()
            session?.invalidateAndCancel()
            continuation?.resume(with: result)
        }
        func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
            completionHandler(nil)
        }
        func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse, completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
            guard let http = response as? HTTPURLResponse else {
                completionHandler(.cancel)
                finish(.failure(PlainHTTPError.badResponse))
                return
            }
            statusCode = http.statusCode
            completionHandler(.allow)
        }
        func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
            let remaining = maxBytes - buffer.count
            if remaining > 0 { buffer.append(contentsOf: data.prefix(remaining)) }
            if data.count > remaining {
                finish(.success((data: buffer, statusCode: statusCode)))
            }
        }
        func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
            if let error {
                if (error as? URLError)?.code == .timedOut { finish(.failure(PlainHTTPError.timeout)) }
                else { finish(.failure(error)) }
            } else if statusCode == 0 {
                finish(.failure(PlainHTTPError.badResponse))
            } else {
                finish(.success((data: buffer, statusCode: statusCode)))
            }
        }
    }
    static func fetchData(from url: URL, accept: String = "*/*", userAgent: String = "DebridChannels-tvOS/325", maxBytes: Int = 4 * 1024 * 1024, timeout: TimeInterval = 30) async throws -> (data: Data, statusCode: Int) {
        guard url.scheme?.lowercased() == "http", maxBytes >= 0, timeout.isFinite, timeout > 0 else { throw PlainHTTPError.invalidURL }
        guard let host = url.host, !host.isEmpty else { throw PlainHTTPError.missingHost }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.httpMethod = "GET"
        request.setValue(accept, forHTTPHeaderField: "Accept")
        request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        let state = RequestState(maxBytes: maxBytes)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                state.start(request, timeout: timeout, continuation: continuation)
            }
        } onCancel: {
            state.finish(.failure(CancellationError()))
        }
    }
}
