#!/usr/bin/env python3
"""Replace the Kingfisher-owned artwork implementation in Android staging only.

Keep original Kingfisher code in Apple conditional. Use SkipFuseUI's AsyncImage
(which is Coil-backed on Android) to render live Signal artworks. Keep the
public Swift call-site shapes and URL routing. The old UIImage loader remains
a compatibility adapter; prewarming and exact eviction semantics need separate
Android implementations, not silently claimed parity.
"""
import argparse, json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument("--source-root",type=Path,required=True)
p.add_argument("--report",type=Path,required=True)
a=p.parse_args()
source=a.source_root/"RemoteImageFit.swift"
if not source.is_file(): p.error("Missing original RemoteImageFit.swift")
data=source.read_text(encoding="utf-8")
assert data.count("import Kingfisher")==1, "Unexpected Kingfisher source layout"
assert data.count("enum PremiumArtworkURL {")==1, "Missing URL routing"
assert data.count("struct RemoteImageFit: View {")==1, "Missing original remote artwork view"
start=data.index("enum PremiumArtworkURL {")
end=data.index("// vBRDC091: artwork loaded",start)
url_router=data[start:end]
if "static func url(_ input: String?) -> URL?" not in url_router: p.error("URL router changed")
alternative=r"""
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import SwiftUI

// Shared routing (including backend image proxy and original TMDB size) is
// taken verbatim from the supplied Apple source and is not reimplemented.
__URL_ROUTER__

enum PremiumArtworkCacheDomain: Hashable {
    case persistent, sports, favorites
}
private struct PremiumArtworkCacheDomainEnvironmentKey: EnvironmentKey {
    static let defaultValue: PremiumArtworkCacheDomain = .persistent
}
extension EnvironmentValues {
    var premiumArtworkCacheDomain: PremiumArtworkCacheDomain {
        get { self[PremiumArtworkCacheDomainEnvironmentKey.self] }
        set { self[PremiumArtworkCacheDomainEnvironmentKey.self] = newValue }
    }
}
extension Notification.Name {
    static let signalVODArtworkReveal = Notification.Name("signal.vod.artwork.reveal")
}

// Compatibility with existing DashboardBackdrop and Unity control points.
// This adapter deliberately does not pretend that source prewarm and decoded
// eviction have been ported. Main artwork rendering uses Coil-backed AsyncImage.
@MainActor
final class PremiumRemoteImageLoader: ObservableObject {
    @Published var image: UIImage? = nil
    @Published private(set) var imageURL: URL? = nil
    @Published var failed = false

    func load(_ url: URL?, preserveCurrentImage: Bool = false,
              maxPixelSize: Int? = nil,
              cacheDomain: PremiumArtworkCacheDomain = .persistent,
              allowPublicationDuringSurfaceHandoff: Bool = false,
              allowPublicationDuringPlayback: Bool = false,
              forceVisiblePlaybackPublication: Bool = false) {
        if !preserveCurrentImage { image = nil }
        imageURL = url
        failed = (url == nil)
    }
    func loadAfterNavigationSettles(_ url: URL?,
              preserveCurrentImage: Bool = false,
              maxPixelSize: Int? = nil,
              cacheDomain: PremiumArtworkCacheDomain = .persistent,
              allowPublicationDuringSurfaceHandoff: Bool = false,
              allowPublicationDuringPlayback: Bool = false,
              forceVisiblePlaybackPublication: Bool = false) {
        load(url, preserveCurrentImage: preserveCurrentImage, maxPixelSize: maxPixelSize,
             cacheDomain: cacheDomain,
             allowPublicationDuringSurfaceHandoff: allowPublicationDuringSurfaceHandoff,
             allowPublicationDuringPlayback: allowPublicationDuringPlayback,
             forceVisiblePlaybackPublication: forceVisiblePlaybackPublication)
    }
    func cancel() {}
    static func suspendForBackground() {}
    static func handleMemoryPressure() {}
    static func beginExclusivePlayback() {}
    static func endExclusivePlayback() {}
    static func releaseDecodedArtworkForHiddenVODOverlay() {}
    static func releaseDecodedArtworkForLiveTVPlayback() {}
    static func releaseTransientSurfaceResources(domain: PremiumArtworkCacheDomain, reason: String) {}
    static func cancelObsoletePrefetches(keeping urlsToKeep: Set<URL>) {}
    static func cancelIdlePrewarmsForNavigation() {}
    static func prefetch(_ urls: [URL], keeping keepAliveURLs: Set<URL> = []) {}
    static func prewarm(_ url: URL?, maxPixelSize: Int? = nil) {}
    static var releaseStabilityActiveWorkCount: Int { 0 }
    static var releaseStabilityDecodedCacheLimitBytes: Int { 0 }
    static func artworkCacheDiagnostics() -> [String: Double] { [:] }
}

struct RemoteImageFit: View {
    enum Mode { case fill, fit, stretch }
    let url: String?
    var mode: Mode = .fill
    var showPlaceholder: Bool = true
    var maxPixelSize: Int? = nil
    var preservePreviousOnURLChange = false
    var publishDuringSurfaceHandoff = false
    var publishDuringPlayback = false
    var forceVisiblePlaybackPublication = false
    var deferHeavyLoadDuringNavigation = false
    var onDisplayedURLChange: ((URL?) -> Void)? = nil
    var fallbackText: String? = nil

    private var target: URL? { PremiumArtworkURL.url(url) }

    @ViewBuilder
    private func scale(_ image: Image) -> some View {
        switch mode {
        case .fill: image.resizable().scaledToFill()
        case .fit: image.resizable().scaledToFit()
        case .stretch: image.resizable()
        }
    }
    var body: some View {
        AsyncImage(url: target) { phase in
            switch phase {
            case .success(let image):
                scale(image)
            case .empty:
                if showPlaceholder {
                    ProgressView().opacity(0.30)
                } else {
                    Color.clear
                }
            case .failure:
                if let fallbackText, !fallbackText.isEmpty {
                    Text(fallbackText).lineLimit(1)
                } else if showPlaceholder {
                    Color.gray.opacity(0.16)
                } else {
                    Color.clear
                }
            @unknown default:
                Color.clear
            }
        }
        .clipped()
        .onAppear { onDisplayedURLChange?(target) }
        .onChange(of: target) { _, next in onDisplayedURLChange?(next) }
    }
}
""".replace("__URL_ROUTER__",url_router.rstrip())
# Android cannot compile Kingfisher. The tvOS source stays byte-identical
# within the non-Android conditional branch.
replacement="#if canImport(Kingfisher) && canImport(UIKit) && canImport(ImageIO)\n"+data.rstrip()+"\n#else\n"+alternative+"\n#endif // Apple Kingfisher vs Android Coil-backed AsyncImage\n"
source.write_text(replacement,encoding="utf-8")
a.report.parent.mkdir(parents=True,exist_ok=True)
out={"file":"RemoteImageFit.swift","apple_code_retained":True,
     "android_image_component":"SkipFuseUI.AsyncImage (Coil-backed)",
     "android_preload_parity":False,
     "android_decoded_cache_eviction_parity":False,
     "original_source_archive_modified":False}
a.report.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
print(json.dumps(out,indent=2))
