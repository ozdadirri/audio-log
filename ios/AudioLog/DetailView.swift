import SwiftUI

struct DetailView: View {
    let fileID: Int

    @Environment(\.dismiss) private var dismiss
    @StateObject private var player = PlayerController()
    @State private var detail: FileDetail?
    @State private var segments: [TranscriptSegment] = []
    @State private var tab = 0            // 0 = summary, 1 = transcript
    @State private var chinese = false
    @State private var chineseText: String?
    @State private var translating = false
    @State private var errorMessage: String?
    @State private var confirmDelete = false

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
        .navigationTitle(detail?.filename ?? "Recording")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                if tab == 0 {
                    Button(chinese ? "EN" : "中文") { toggleChinese() }
                        .disabled(translating)
                }
                Menu {
                    Button("Re-run processing") { Task { try? await APIClient.rerun(id: fileID) } }
                    Button("Delete", role: .destructive) { confirmDelete = true }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .confirmationDialog("Delete this recording and its transcript and summary?",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                Task {
                    try? await APIClient.delete(id: fileID)
                    dismiss()
                }
            }
        }
        .task { await load() }
        .onDisappear { player.stop() }
    }

    // A minimal RecordingFile so thumbURL can be reused for the header image.
    private var placeholderFile: RecordingFile {
        RecordingFile(id: fileID, filename: detail?.filename ?? "",
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
        } else {
            MarkdownText(text: (chinese ? chineseText : detail?.summary) ?? "(not ready)")
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
            chineseText = d.summaryZh
            if let url = APIClient.audioURL(id: fileID) {
                player.load(url: url, fallbackDuration: d.duration)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func toggleChinese() {
        chinese.toggle()
        guard chinese, chineseText == nil else { return }
        translating = true
        Task {
            defer { translating = false }
            do { chineseText = try await APIClient.translate(id: fileID) }
            catch { errorMessage = error.localizedDescription; chinese = false }
        }
    }
}
