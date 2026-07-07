import SwiftUI

struct DetailView: View {
    let fileID: Int

    @Environment(\.dismiss) private var dismiss
    @StateObject private var player = PlayerController()
    @State private var detail: FileDetail?
    @State private var segments: [TranscriptSegment] = []
    @State private var tab = 0            // 0 = summary, 1 = transcript
    @State private var lang = "en"
    @State private var translatedText: String?
    @State private var translating = false
    @State private var errorMessage: String?
    @State private var confirmDelete = false
    @State private var languages: [APIClient.Language] = [.init(code: "en", label: "English")]

    var body: some View {
        ScrollViewReader { proxy in
            List {
                Section {
                    AsyncImage(url: detail.flatMap { _ in
                        APIClient.thumbURL(for: placeholderFile)
                    }) { image in
                        image.resizable().aspectRatio(contentMode: .fit)
                    } placeholder: {
                        Rectangle().fill(Color(white: 0.08)).aspectRatio(1, contentMode: .fit)
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .listRowInsets(EdgeInsets())

                    playerControls
                    if let detail, !detail.tagList.isEmpty {
                        HStack {
                            ForEach(detail.tagList, id: \.self) { tag in
                                Text("#\(tag)")
                                    .font(.caption.bold()).foregroundStyle(.secondary)
                                    .padding(.horizontal, 8).padding(.vertical, 3)
                                    .background(.quaternary, in: Capsule())
                            }
                        }
                    }
                }

                if let errorMessage {
                    Text(errorMessage).foregroundStyle(.red).font(.footnote)
                }

                Section {
                    Picker("View", selection: $tab) {
                        Text("Summary").tag(0)
                        Text("Transcript").tag(1)
                    }
                    .pickerStyle(.segmented)

                    if tab == 0 {
                        summaryView
                    } else {
                        transcriptView
                    }
                }
            }
            .onChange(of: currentSegmentID) { _, id in
                guard player.isPlaying, let id else { return }
                withAnimation { proxy.scrollTo(id, anchor: .center) }
            }
        }
        .navigationTitle(detail.map { $0.title?.isEmpty == false ? $0.title! : $0.filename }
                         ?? "Recording")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if tab == 0 {
                    Menu {
                        Picker("Language", selection: $lang) {
                            ForEach(languages) { Text($0.label).tag($0.code) }
                        }
                    } label: { Image(systemName: "globe") }
                        .disabled(translating)
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                ExportMenu(endpoint: "/api/files/\(fileID)/export",
                           name: detail?.title ?? detail?.filename ?? "recording",
                           lang: lang)
            }
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button("Re-run processing") { Task { try? await APIClient.rerun(id: fileID) } }
                    Button(detail?.memExclude == 1 ? "Include in memory" : "Exclude from memory") {
                        Task {
                            try? await APIClient.setMemExclude(
                                id: fileID, exclude: detail?.memExclude != 1)
                            await load()
                        }
                    }
                    Button("Delete", role: .destructive) { confirmDelete = true }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .confirmationDialog("Move this recording to trash? Restore it from Profile > Trash within 30 days.",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Move to Trash", role: .destructive) {
                Task {
                    try? await APIClient.delete(id: fileID)
                    dismiss()
                }
            }
        }
        .task { await load() }
        .onDisappear { player.stop() }
        .onChange(of: lang) { _, _ in loadTranslation() }
    }

    // A minimal RecordingFile so thumbURL can be reused for the header image.
    private var placeholderFile: RecordingFile {
        RecordingFile(id: fileID, filename: detail?.filename ?? "", title: nil,
                      status: detail?.status ?? "done", error: nil,
                      language: nil, duration: detail?.duration, owner: nil,
                      createdAt: detail?.createdAt ?? "", updatedAt: "")
    }

    private var playerControls: some View {
        HStack(spacing: 14) {
            Button {
                player.toggle()
            } label: {
                Image(systemName: player.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                    .font(.system(size: 42))
            }
            .buttonStyle(.plain)

            Slider(
                value: Binding(
                    get: { min(player.currentTime, max(player.duration, 0.1)) },
                    set: { player.seek(to: $0) }
                ),
                in: 0...max(player.duration, 0.1)
            )

            Text(timeLabel).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
    }

    private var timeLabel: String {
        func fmt(_ t: Double) -> String {
            let s = Int(t.rounded())
            return String(format: "%d:%02d", s / 60, s % 60)
        }
        return "\(fmt(player.currentTime)) / \(fmt(player.duration))"
    }

    @ViewBuilder
    private var summaryView: some View {
        if translating {
            HStack { ProgressView(); Text("Translating…").foregroundStyle(.secondary) }
        } else if lang == "en" {
            MarkdownText(text: detail?.summary ?? "(not ready)")
        } else {
            MarkdownText(text: translatedText ?? "(not ready)")
        }
    }

    private var currentSegmentID: UUID? {
        segments.last(where: { $0.start <= player.currentTime })?.id
    }

    @ViewBuilder
    private var transcriptView: some View {
        if segments.isEmpty {
            Text(detail?.transcript ?? "(not ready)").foregroundStyle(.secondary)
        } else {
            ForEach(segments) { segment in
                HStack(alignment: .top, spacing: 10) {
                    Text(segment.startLabel)
                        .font(.caption.bold().monospacedDigit())
                        .foregroundStyle(segment.id == currentSegmentID ? Color.accentColor : .secondary)
                        .frame(width: 44, alignment: .leading)
                    Text(segment.text)
                }
                .id(segment.id)
                .listRowBackground(segment.id == currentSegmentID
                                   ? Color.accentColor.opacity(0.12) : nil)
                .contentShape(Rectangle())
                .onTapGesture {
                    player.seek(to: segment.start)
                    if !player.isPlaying { player.toggle() }
                }
            }
        }
    }

    private func load() async {
        do {
            let d = try await APIClient.detail(id: fileID)
            detail = d
            segments = TranscriptSegment.parse(d.transcript ?? "")
            if let url = APIClient.audioURL(id: fileID) {
                player.load(url: url, fallbackDuration: d.duration)
            }
            if let langs = try? await APIClient.languages() { languages = langs }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func loadTranslation() {
        guard lang != "en" else { return }
        translatedText = nil
        translating = true
        Task {
            defer { translating = false }
            do { translatedText = try await APIClient.translate(id: fileID, lang: lang) }
            catch { errorMessage = error.localizedDescription; lang = "en" }
        }
    }
}
