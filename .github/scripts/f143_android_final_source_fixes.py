#!/usr/bin/env python3
"""Source-checked Android staged Swift fixes from compiler evidence (25).

Preserve all original Apple TV source and Signal functionality. Break a
complex diagnostic SwiftUI body into smaller typed subviews, and expose the
backdrop state-owner class after Skip's SwiftUI visibility promotions.
"""
import argparse,json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument("--source-root",required=True,type=Path)
p.add_argument("--report",required=True,type=Path)
a=p.parse_args()
root=a.source_root.resolve()
backdrop=root/"SignalDashboardBackdrop.swift"
diagnostic=root/"DiagnosticsDeveloperToolsManager.swift"
for f in (backdrop,diagnostic):
    if not f.is_file():p.error("Missing original F143 source: "+str(f))
b=backdrop.read_text(encoding="utf-8")
old="@MainActor private final class SignalBackdropBitmapOwner: ObservableObject {"
if b.count(old)!=1:p.error("Backdrop owner signature changed")
if "SignalBackdropBitmapOwner()" not in b:p.error("Backdrop owner no longer used")
b=b.replace(old,"@MainActor final class SignalBackdropBitmapOwner: ObservableObject {",1)
d=diagnostic.read_text(encoding="utf-8")
marker="struct DiagnosticsDeveloperToolsPanel: View {"
if d.count(marker)!=1:p.error("Diagnostics panel signature changed")
index=d.index(marker)
panel=d[index:]
expected=[
 'VStack(alignment: .leading, spacing: 14) {',
 'ForEach(manager.snapshots.prefix(8)) { snapshot in',
 'ForEach(snapshot.details.prefix(5), id: \\.self) { line in',
 'if let note = manager.lastDeveloperNote, !note.isEmpty {',
 'if manager.snapshots.isEmpty {'
]
if any(panel.count(x)!=1 for x in expected):
    p.error("Diagnostics panel body changed: refusing unchecked replacement")
if panel.count("var body: some View {")!=1 or not panel.rstrip().endswith("}"):
    p.error("Diagnostics panel no longer the sole trailing view")
view=r"""struct DiagnosticsDeveloperToolsPanel: View {
    @ObservedObject var manager: DiagnosticsDeveloperToolsManager

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            heading
            developerNote
            snapshotRows
            emptyMessage
        }
        .padding(20)
        .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Color.black.opacity(0.42)))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(Color.white.opacity(0.10), lineWidth: 1))
    }

    private var heading: some View {
        HStack(spacing: 12) {
            Image(systemName: "stethoscope")
                .font(.system(size: 30, weight: .black))
                .foregroundStyle(.cyan)
            VStack(alignment: .leading, spacing: 3) {
                Text("Diagnostics")
                    .font(.system(size: 30, weight: .black, design: .rounded))
                    .foregroundStyle(.white)
                Text("Read-only developer snapshots for production QA.")
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.62))
            }
        }
    }

    @ViewBuilder private var developerNote: some View {
        if let note = manager.lastDeveloperNote, !note.isEmpty {
            Text(note)
                .font(.system(size: 14, weight: .bold, design: .rounded))
                .foregroundStyle(.orange.opacity(0.9))
        }
    }

    private var snapshotRows: some View {
        ForEach(manager.snapshots.prefix(8)) { snapshot in
            snapshotRow(snapshot)
        }
    }

    private func snapshotRow(_ snapshot: DiagnosticsDeveloperToolsManager.Snapshot) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("\(snapshot.area.rawValue) • \(snapshot.title)")
                .font(.system(size: 17, weight: .black, design: .rounded))
                .foregroundStyle(.white)
            Text(snapshot.status)
                .font(.system(size: 14, weight: .bold, design: .rounded))
                .foregroundStyle(.cyan.opacity(0.9))
            ForEach(snapshot.details.prefix(5), id: \.self) { line in
                Text(line)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.62))
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.white.opacity(0.055)))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Color.white.opacity(0.08), lineWidth: 1))
    }

    @ViewBuilder private var emptyMessage: some View {
        if manager.snapshots.isEmpty {
            Text("No diagnostics captured yet.")
                .font(.system(size: 15, weight: .semibold, design: .rounded))
                .foregroundStyle(.white.opacity(0.58))
        }
    }
}
"""
if "struct " in panel[len(marker):]:
    p.error("Additional types after diagnostics panel; refusing to truncate")
d=d[:index]+view
backdrop.write_text(b,encoding="utf-8")
diagnostic.write_text(d,encoding="utf-8")

# The preview namespace is unused by the actual tab renderer. SkipFuseUI
# explicitly marks Namespace.init unavailable; retain the identical static
# preview by using the renderer's existing optional nil namespace.
menu=root/"SignalTopMenuVisuals.swift"
m=menu.read_text(encoding="utf-8")
if m.count("    @Namespace private var previewSelection\n")!=1 or m.count("selectionNamespace: previewSelection")!=1 or m.count("previewSelection")!=2 or m.count("selectionNamespace")!=2 or "var selectionNamespace: Namespace.ID? = nil" not in m:
    p.error("Top menu preview namespace usage changed; refusing unchecked repair")
m=m.replace("    @Namespace private var previewSelection\n","",1).replace("selectionNamespace: previewSelection","selectionNamespace: nil",1)
menu.write_text(m,encoding="utf-8")

a.report.parent.mkdir(parents=True,exist_ok=True)
a.report.write_text(json.dumps({
 "backdrop_owner_visibility":"internal",
 "diagnostics_view":"split into heading/note/rows/empty components",
 "top_menu_preview_namespace":"removed unused unavailable wrapper; same static renderer",
 "original_zip_modified":False,
 "full_android_compile_verified":False
},indent=2)+"\n",encoding="utf-8")
print("Patched two confirmed compiler blockers in staged Signal Swift sources")
