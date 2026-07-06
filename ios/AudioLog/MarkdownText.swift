import SwiftUI

/// Renders the pipeline's markdown digests: #/## headings, "*"/"-" bullets,
/// and inline **bold** / `code` via AttributedString.
struct MarkdownText: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(text.split(separator: "\n", omittingEmptySubsequences: true).enumerated()),
                    id: \.offset) { _, rawLine in
                line(String(rawLine))
            }
        }
    }

    @ViewBuilder
    private func line(_ raw: String) -> some View {
        let trimmed = raw.trimmingCharacters(in: .whitespaces)
        if trimmed.hasPrefix("## ") {
            Text(inline(String(trimmed.dropFirst(3))))
                .font(.caption.bold())
                .textCase(.uppercase)
                .foregroundStyle(Color.accentColor)
                .padding(.top, 8)
        } else if trimmed.hasPrefix("# ") {
            Text(inline(String(trimmed.dropFirst(2))))
                .font(.headline)
        } else if trimmed.hasPrefix("* ") || trimmed.hasPrefix("- ") {
            HStack(alignment: .top, spacing: 8) {
                Text("•")
                Text(inline(String(trimmed.dropFirst(2))))
            }
            .padding(.leading, 4)
        } else {
            Text(inline(trimmed))
        }
    }

    private func inline(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s)) ?? AttributedString(s)
    }
}
