import SwiftUI

struct MemoryView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var status: MemoryStatus?
    @State private var chinese = false
    @State private var building = false
    @State private var translating = false
    @State private var confirmReset = false
    @State private var errorMessage: String?

    private var shownText: String? {
        chinese ? status?.contentZh : status?.content
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let status {
                        Text(meta(status)).font(.footnote).foregroundStyle(.secondary)
                    }
                    if let errorMessage {
                        Text(errorMessage).font(.footnote).foregroundStyle(.red)
                    }
                    if building {
                        HStack { ProgressView(); Text("Building memory — runs the LLM, may take a while…") }
                            .foregroundStyle(.secondary)
                    } else if translating {
                        HStack { ProgressView(); Text("Translating…") }.foregroundStyle(.secondary)
                    } else if let text = shownText {
                        MarkdownText(text: text)
                    } else if status != nil {
                        Text("No memory yet — press Update to distill your recordings " +
                             "into a long-term memory the assistant can use.")
                            .foregroundStyle(.secondary)
                    } else {
                        ProgressView()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
            }
            .navigationTitle("Memory")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close") { dismiss() } }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    if status?.content != nil {
                        Button(chinese ? "EN" : "中文") { toggleChinese() }
                            .disabled(translating || building)
                    }
                    Button(buildLabel) { build() }
                        .disabled(building || (status?.pending ?? 0) == 0)
                    Menu {
                        Button("Reset memory", role: .destructive) { confirmReset = true }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            }
            .confirmationDialog("Reset memory? The next build starts from scratch.",
                                isPresented: $confirmReset, titleVisibility: .visible) {
                Button("Reset", role: .destructive) { reset() }
            }
            .task { await load() }
        }
    }

    private var buildLabel: String {
        let pending = status?.pending ?? 0
        return pending > 0 ? "Update (\(pending))" : "Up to date"
    }

    private func meta(_ status: MemoryStatus) -> String {
        let updated = status.updatedAt.flatMap {
            ISO8601DateFormatter().date(from: $0)?.formatted()
        } ?? "never built"
        return "updated \(updated) · \(status.pending) new to fold in"
    }

    private func load() async {
        do {
            status = try await APIClient.memoryStatus()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func build() {
        building = true
        Task {
            defer { building = false }
            do {
                status = try await APIClient.memoryBuild()
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func toggleChinese() {
        chinese.toggle()
        guard chinese, status?.contentZh == nil else { return }
        translating = true
        Task {
            defer { translating = false }
            do {
                let zh = try await APIClient.memoryTranslate()
                status = MemoryStatus(content: status?.content, contentZh: zh,
                                      updatedAt: status?.updatedAt,
                                      pending: status?.pending ?? 0)
            } catch {
                errorMessage = error.localizedDescription
                chinese = false
            }
        }
    }

    private func reset() {
        Task {
            do {
                try await APIClient.memoryReset()
                chinese = false
                await load()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
