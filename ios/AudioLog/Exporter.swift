import SwiftUI
import WebKit

enum ExportFormat: String, CaseIterable, Identifiable {
    case pdf, markdown, html
    var id: String { rawValue }
    var label: String {
        switch self {
        case .pdf: return "PDF"
        case .markdown: return "Markdown"
        case .html: return "HTML"
        }
    }
    var apiValue: String { self == .markdown ? "md" : rawValue }
    var ext: String { self == .markdown ? "md" : rawValue }
}

/// Produces a shareable file for an export endpoint. Markdown and HTML come
/// straight from the server; PDF is rendered on-device from the server's HTML
/// via WKWebView, so no server-side PDF engine is required.
enum Exporter {
    /// `endpoint` is a path like "/api/files/12/export" or "/api/memory/export".
    static func file(endpoint: String, name: String, format: ExportFormat,
                     lang: String) async throws -> URL {
        let safeName = name.replacingOccurrences(of: "/", with: "-")
            .trimmingCharacters(in: .whitespaces)
        let dest = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(safeName).\(format.ext)")

        if format == .pdf {
            let html = try await fetchText(endpoint, format: "html", lang: lang)
            let pdf = try await Self.renderPDF(html: html)
            try pdf.write(to: dest)
        } else {
            let text = try await fetchText(endpoint, format: format.apiValue, lang: lang)
            try text.data(using: .utf8)?.write(to: dest)
        }
        return dest
    }

    private static func fetchText(_ endpoint: String, format: String,
                                  lang: String) async throws -> String {
        let url = try APIClient.url("\(endpoint)?format=\(format)&lang=\(lang)")
        var request = URLRequest(url: url)
        if !APIClient.apiKey.isEmpty {
            request.setValue(APIClient.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        let (data, _) = try await URLSession.shared.data(for: request)
        return String(data: data, encoding: .utf8) ?? ""
    }

    @MainActor
    private static func renderPDF(html: String) async throws -> Data {
        let webView = WKWebView(frame: CGRect(x: 0, y: 0, width: 595, height: 842)) // A4 pt
        let delegate = LoadDelegate()
        webView.navigationDelegate = delegate
        webView.loadHTMLString(html, baseURL: nil)
        try await delegate.wait()
        return try await webView.pdf(configuration: WKPDFConfiguration())
    }

    private final class LoadDelegate: NSObject, WKNavigationDelegate {
        private var continuation: CheckedContinuation<Void, Error>?

        func wait() async throws {
            try await withCheckedThrowingContinuation { self.continuation = $0 }
        }
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            continuation?.resume(); continuation = nil
        }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!,
                     withError error: Error) {
            continuation?.resume(throwing: error); continuation = nil
        }
    }
}

/// UIActivityViewController wrapper for sharing an exported file.
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

/// A Menu of export formats that produces a file and presents a share sheet.
/// Drop into a toolbar; `endpoint`, `name`, and `lang` describe what to export.
struct ExportMenu: View {
    let endpoint: String
    let name: String
    var lang: String = "en"

    @State private var shareURL: URL?
    @State private var busy = false
    @State private var errorMessage: String?

    var body: some View {
        Menu {
            ForEach(ExportFormat.allCases) { format in
                Button(format.label) { export(format) }
            }
        } label: {
            if busy { ProgressView() } else { Image(systemName: "square.and.arrow.up") }
        }
        .disabled(busy)
        .sheet(item: $shareURL) { url in ShareSheet(items: [url]) }
        .alert("Export failed", isPresented: .constant(errorMessage != nil)) {
            Button("OK") { errorMessage = nil }
        } message: { Text(errorMessage ?? "") }
    }

    private func export(_ format: ExportFormat) {
        busy = true
        Task {
            defer { busy = false }
            do {
                shareURL = try await Exporter.file(endpoint: endpoint, name: name,
                                                   format: format, lang: lang)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}
