#!/usr/bin/env python3
"""Fill missing Android artwork runtime APIs in staged Coil-backed Signal branch.

The Android Swift source still uses the SkipFuseUI AsyncImage (Coil) for
poster views. Other callers use a disk-backed source cache and an async image
loader. This does not implement Kingfisher's advanced prefetch/eviction policy.
"""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--source-root",type=Path,required=True)
p.add_argument("--report",type=Path,required=True)
a=p.parse_args()
src=a.source_root/"RemoteImageFit.swift"
if not src.is_file():p.error("Staged artwork source missing")
text=src.read_text(encoding="utf-8")
if "#endif // Apple Kingfisher vs Android Coil-backed AsyncImage" not in text:
    p.error("Coil artwork stage must run first")
head="struct RemoteImageFit: View {"
if text.count(head)!=2:p.error("Expected exactly two RemoteImageFit branches")
if text.count("static func prewarm(_ url: URL?, maxPixelSize: Int? = nil) {}")!=1:
    p.error("Existing Android prewarm adapter changed")
text=text.replace(
    "static func prewarm(_ url: URL?, maxPixelSize: Int? = nil) {}",
    "static func prewarm(_ url: URL?, maxPixelSize: Int? = nil, cacheDomain: PremiumArtworkCacheDomain = .persistent) {\n"
    "        guard let url else { return }\n"
    "        Task.detached(priority: .utility) {\n"
    "            if await PersistentArtworkSourceCache.data(for: url) != nil { return }\n"
    "            if let (bytes, _) = try? await URLSession.shared.data(from: url) {\n"
    "                PersistentArtworkSourceCache.write(bytes, for: url)\n"
    "            }\n"
    "        }\n"
    "    }",
    1
)
runtime = r"""
// The Android-only disk cache retains actual downloaded source bytes, not
// decoded platform image objects. Coil remains responsible for poster display.
enum PersistentArtworkSourceCache {
    private static let queue = DispatchQueue(label: "signal.android.artwork.source", qos: .utility)

    private static func file(for url: URL) -> URL? {
        guard let base = FileManager.default.urls(for: .cachesDirectory,
                                  in: .userDomainMask).first else { return nil }
        let folder = base.appendingPathComponent("SignalAndroidArtworkSource-v1",
                                                 isDirectory: true)
        try? FileManager.default.createDirectory(at: folder,
                                withIntermediateDirectories: true)
        var digest: UInt64 = 14_695_981_039_346_656_037
        for byte in url.absoluteString.utf8 {
            digest ^= UInt64(byte)
            digest &*= 1_099_511_628_211
        }
        return folder.appendingPathComponent(String(format: "%016llx.art", digest))
    }
    private static func isImage(_ data: Data) -> Bool {
        let b = [UInt8](data.prefix(16))
        if b.count < 8 { return false }
        if b.starts(with: [0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A]) { return true }
        if b.starts(with: [0xFF,0xD8,0xFF]) { return true }
        if b.starts(with: [0x47,0x49,0x46,0x38]) { return true }
        if b.starts(with: [0x52,0x49,0x46,0x46]) &&
            b.count >= 12 && Array(b[8..<12]) == [0x57,0x45,0x42,0x50] {
            return true
        }
        return false
    }
    static func read(_ url: URL, completion: @escaping (Data?) -> Void) {
        queue.async {
            guard let path = file(for: url),
                  let bytes = try? Data(contentsOf: path),
                  isImage(bytes) else { completion(nil); return }
            completion(bytes)
        }
    }
    static func data(for url: URL) async -> Data? {
        await withCheckedContinuation { continuation in
            read(url) { bytes in continuation.resume(returning: bytes) }
        }
    }
    static func write(_ data: Data, for url: URL) {
        guard isImage(data) else { return }
        queue.async {
            guard let path = file(for: url) else { return }
            try? data.write(to: path, options: .atomic)
        }
    }
    static func remove(_ url: URL) {
        queue.async {
            guard let path = file(for: url) else { return }
            try? FileManager.default.removeItem(at: path)
        }
    }
}

@MainActor
final class PremiumArtworkRehydrationCoordinator {
    static let shared = PremiumArtworkRehydrationCoordinator()
    private init() {}
    func force(reason: String) {
        // Only loaders with missing image pixels are refreshed. Healthy
        // mounted artwork keeps its current bitmap during playback transitions.
        PremiumRemoteImageLoader.rehydrateBlankMountedLoaders()
    }
}
"""
# The alternate branch only has one RemoteImageFit after its #else.
alt_anchor="\nstruct RemoteImageFit: View {\n    enum Mode { case fill, fit, stretch }"
# The preserved Apple branch can contain the same declaration. Restrict
# insertion to the Android alternative after the known #else boundary.
android_boundary = "#else\n\nimport Foundation"
boundary_at = text.find(android_boundary)
if boundary_at < 0:p.error("Android Coil alternative branch missing")
android_section = text[boundary_at:]
if android_section.count(alt_anchor)!=1:
    p.error(f"Expected exactly one Android RemoteImageFit anchor; found {android_section.count(alt_anchor)}")
android_section = android_section.replace(alt_anchor,"\n"+runtime+alt_anchor,1)
text = text[:boundary_at]+android_section
# Extend premium loader with bounded network loading, keeping published UIKit
# image path for SignalDashboardBackdrop and other direct loader consumers.
old_loader = """        if !preserveCurrentImage { image = nil }
        imageURL = url
        failed = (url == nil)
    }"""
new_loader = """        if !preserveCurrentImage { image = nil }
        imageURL = url
        failed = (url == nil)
        loadTask?.cancel()
        guard let url else { return }
        loadTask = Task { [weak self] in
            var bytes = await PersistentArtworkSourceCache.data(for: url)
            if bytes == nil {
                bytes = try? await URLSession.shared.data(from: url).0
                if let bytes { PersistentArtworkSourceCache.write(bytes, for: url) }
            }
            guard !Task.isCancelled, let self,
                  self.imageURL == url else { return }
            self.image = bytes.flatMap { UIImage(data: $0) }
            self.failed = (self.image == nil)
        }
    }"""
if text.count(old_loader)!=1:p.error("Android loader source changed")
text=text.replace(old_loader,new_loader,1)
anchor="    @Published var failed = false\n\n    func load("
if text.count(anchor)!=1:p.error("Android loader state anchor changed")
text=text.replace(anchor,"    @Published var failed = false\n    private var loadTask: Task<Void, Never>?\n    private static var mounted: [WeakLoader] = []\n    private final class WeakLoader {\n        weak var value: PremiumRemoteImageLoader?\n        init(_ value: PremiumRemoteImageLoader) { self.value = value }\n    }\n    init() { Self.mounted.append(WeakLoader(self)) }\n    static func rehydrateBlankMountedLoaders() {\n        mounted.removeAll(where: { $0.value == nil })\n        for ref in mounted {\n            guard let loader = ref.value, loader.image == nil,\n                  let url = loader.imageURL else { continue }\n            loader.load(url)\n        }\n    }\n\n    func load(",1)
old_cancel="    func cancel() {}"
if text.count(old_cancel)!=1:p.error("Android cancellation method changed")
text=text.replace(old_cancel,"    func cancel() { loadTask?.cancel(); loadTask = nil }",1)
src.write_text(text,encoding="utf-8")
a.report.parent.mkdir(parents=True,exist_ok=True)
out={
 "new_symbols":["PersistentArtworkSourceCache", "PremiumArtworkRehydrationCoordinator"],
 "android_remote_loader_network_fetch":True,
 "android_source_byte_disk_cache":True,
 "android_blank_loader_rehydration":True,
 "android_coil_poster_loader":True,
 "kingfisher_prefetch_parity":False,
 "cache_limit_eviction_parity":False,
 "original_source_archive_modified":False,
}
a.report.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
print(json.dumps(out,indent=2))
