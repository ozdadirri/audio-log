import SwiftUI

struct AskView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var question = ""
    @State private var answer: AskResponse?
    @State private var thinking = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Ask about your recordings…", text: $question, axis: .vertical)
                        .onSubmit { ask() }
                    Button("Ask AI") { ask() }
                        .disabled(question.trimmingCharacters(in: .whitespaces).isEmpty || thinking)
                }

                if thinking {
                    HStack { ProgressView(); Text("Searching recordings and thinking…") }
                        .foregroundStyle(.secondary)
                }

                if let errorMessage {
                    Text(errorMessage).foregroundStyle(.red).font(.footnote)
                }

                if let answer {
                    Section("Answer") {
                        MarkdownText(text: answer.answer)
                    }
                    Section("Sources") {
                        ForEach(answer.sources) { source in
                            NavigationLink(value: source.id) {
                                Label(source.filename, systemImage: "waveform")
                            }
                        }
                    }
                }
            }
            .navigationTitle("Ask AI")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Int.self) { id in DetailView(fileID: id) }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close") { dismiss() } }
            }
        }
    }

    private func ask() {
        let q = question.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        thinking = true
        answer = nil
        errorMessage = nil
        Task {
            defer { thinking = false }
            do { answer = try await APIClient.ask(question: q) }
            catch { errorMessage = error.localizedDescription }
        }
    }
}
