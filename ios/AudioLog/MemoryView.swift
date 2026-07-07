import SwiftUI

struct MemoryView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var status: MemoryStatus?
    @State private var lang = "en"
    @State private var translated: String?
    @State private var building = false
    @State private var translating = false
    @State private var confirmReset = false
    @State private var errorMessage: String?
    @State private var languages: [APIClient.Language] = [.init(code: "en", label: "English")]

    private var shownText: String? {
        lang == "en" ? status?.content : translated
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
                        Menu {
                            Picker("Language", selection: $lang) {
                                ForEach(languages) { Text($0.label).tag($0.code) }
                            }
                        } label: { Image(systemName: "globe") }
                            .disabled(translating || building)
                    }
                    Button(buildLabel) { build() }
                        .disabled(building || (status?.pending ?? 0) == 0)
                    if status?.content != nil {
                        ExportMenu(endpoint: "/api/memory/export", name: "memory", lang: lang)
                    }
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
            .onChange(of: lang) { _, _ in loadTranslation() }
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
            if let langs = try? await APIClient.languages() { languages = langs }
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
                lang = "en"      // rebuilt content invalidates translations
                translated = nil
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func loadTranslation() {
        guard lang != "en" else { return }
        translated = nil
        translating = true
        Task {
            defer { translating = false }
            do { translated = try await APIClient.memoryTranslate(lang: lang) }
            catch { errorMessage = error.localizedDescription; lang = "en" }
        }
    }

    private func reset() {
        Task {
            do {
                try await APIClient.memoryReset()
                lang = "en"
                translated = nil
                await load()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
