import SwiftUI

struct ChatEntry: Identifiable {
    let id = UUID()
    let question: String
    let answer: String
    let sources: [AskSource]
}

struct AskView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var question = ""
    @State private var chat: [ChatEntry] = []
    @State private var thinking = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                ForEach(chat) { entry in
                    Section {
                        Text(entry.question).bold().foregroundStyle(Color.accentColor)
                        MarkdownText(text: entry.answer)
                        ForEach(entry.sources) { source in
                            NavigationLink(value: source.id) {
                                Label(source.filename, systemImage: "waveform")
                                    .font(.footnote)
                            }
                        }
                    }
                }

                Section {
                    if thinking {
                        HStack { ProgressView(); Text("Searching recordings and thinking…") }
                            .foregroundStyle(.secondary)
                    }
                    if let errorMessage {
                        Text(errorMessage).foregroundStyle(.red).font(.footnote)
                    }
                    TextField(chat.isEmpty ? "Ask about your recordings…" : "Follow up…",
                              text: $question, axis: .vertical)
                        .onSubmit { ask() }
                    Button(chat.isEmpty ? "Ask AI" : "Send") { ask() }
                        .disabled(question.trimmingCharacters(in: .whitespaces).isEmpty || thinking)
                }
            }
            .navigationTitle("Ask AI")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Int.self) { id in DetailView(fileID: id) }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    if !chat.isEmpty {
                        Button("Clear") { chat = []; errorMessage = nil }
                    }
                }
            }
        }
    }

    private func ask() {
        let q = question.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !thinking else { return }
        thinking = true
        errorMessage = nil
        question = ""
        Task {
            defer { thinking = false }
            do {
                let history = chat.map { ChatTurn(question: $0.question, answer: $0.answer) }
                let response = try await APIClient.ask(question: q, history: history)
                chat.append(ChatEntry(question: q, answer: response.answer,
                                      sources: response.sources))
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
