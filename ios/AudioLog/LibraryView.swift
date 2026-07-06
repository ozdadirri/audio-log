import SwiftUI

struct LibraryView: View {
    @State private var files: [RecordingFile] = []
    @State private var searchText = ""
    @State private var errorMessage: String?
    @State private var showSettings = false
    @State private var showRecorder = false
    @State private var showAsk = false
    @State private var showImporter = false
    @State private var uploadMessage: String?
    @State private var me: Me?
    @State private var adminUsers: [UserAccount] = []
    @State private var ownerFilter: String?
    @State private var showProfile = false
    @State private var showMemory = false

    private var shown: [RecordingFile] {
        files.filter { file in
            (ownerFilter == nil || file.owner == ownerFilter) &&
            (searchText.isEmpty || file.filename.localizedCaseInsensitiveContains(searchText))
        }
    }

    /// Files grouped by local day, newest group first.
    private var groups: [(label: String, items: [RecordingFile])] {
        let calendar = Calendar.current
        let grouped = Dictionary(grouping: shown) { calendar.startOfDay(for: $0.createdDate) }
        return grouped.keys.sorted(by: >).map { day in
            (Self.dayLabel(day), grouped[day] ?? [])
        }
    }

    private static func dayLabel(_ day: Date) -> String {
        if Calendar.current.isDateInToday(day) { return "Today" }
        if Calendar.current.isDateInYesterday(day) { return "Yesterday" }
        return day.formatted(date: .abbreviated, time: .omitted)
    }

    private var isProcessing: Bool {
        files.contains { ["pending", "transcribing", "summarizing"].contains($0.status) }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                if let uploadMessage {
                    Text(uploadMessage).font(.footnote).foregroundStyle(.secondary)
                }
                if isProcessing {
                    Label("Processing — playback may stutter while the AI models run",
                          systemImage: "gearshape.2")
                        .font(.footnote).foregroundStyle(.orange)
                }
                LazyVStack(alignment: .leading, spacing: 20) {
                    ForEach(groups, id: \.label) { group in
                        Section {
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 6)],
                                      spacing: 6) {
                                ForEach(group.items) { file in
                                    NavigationLink(value: file.id) {
                                        TileView(file: file, showOwner: me?.isAdmin == true)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        } header: {
                            HStack(spacing: 8) {
                                Text(group.label).font(.headline)
                                Text("\(group.items.count)").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                .padding(.horizontal, 12)
            }
            .navigationTitle("AudioLog")
            .navigationDestination(for: Int.self) { id in
                DetailView(fileID: id)
            }
            .searchable(text: $searchText, prompt: "Filter recordings")
            .refreshable { await load() }
            .toolbar {
                ToolbarItemGroup(placement: .topBarLeading) {
                    Button { showProfile = true } label: {
                        Image(systemName: me?.isAdmin == true ? "person.circle.fill" : "person.circle")
                    }
                    Button { showMemory = true } label: {
                        Image(systemName: "brain")
                    }
                }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    if me?.isAdmin == true {
                        Menu {
                            Picker("Owner", selection: $ownerFilter) {
                                Text("All users").tag(String?.none)
                                ForEach(adminUsers) { user in
                                    Text("\(user.username) (\(user.fileCount ?? 0))")
                                        .tag(String?.some(user.username))
                                }
                            }
                        } label: {
                            Image(systemName: ownerFilter == nil
                                  ? "line.3.horizontal.decrease.circle"
                                  : "line.3.horizontal.decrease.circle.fill")
                        }
                    }
                    Button { showAsk = true } label: { Image(systemName: "sparkles") }
                    Menu {
                        Button { showRecorder = true } label: {
                            Label("Record", systemImage: "mic")
                        }
                        Button { showImporter = true } label: {
                            Label("Import audio", systemImage: "square.and.arrow.down")
                        }
                    } label: { Image(systemName: "plus.circle") }
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .sheet(isPresented: $showSettings, onDismiss: { Task { await loadProfile() } }) {
                SettingsView()
            }
            .sheet(isPresented: $showProfile) { ProfileView(me: me) }
            .sheet(isPresented: $showMemory) { MemoryView() }
            .sheet(isPresented: $showAsk) { AskView() }
            .sheet(isPresented: $showRecorder, onDismiss: { Task { await load() } }) {
                RecordView()
            }
            .fileImporter(isPresented: $showImporter,
                          allowedContentTypes: [.audio, .movie],
                          allowsMultipleSelection: true) { result in
                Task { await handleImport(result) }
            }
            .overlay {
                if let errorMessage, files.isEmpty {
                    ContentUnavailableView("Cannot reach server",
                                           systemImage: "wifi.exclamationmark",
                                           description: Text(errorMessage))
                }
            }
            .task { await pollLoop() }
        }
    }

    private func pollLoop() async {
        await loadProfile()
        while !Task.isCancelled {
            await load()
            try? await Task.sleep(for: .seconds(5))
        }
    }

    private func loadProfile() async {
        me = try? await APIClient.me()
        if me?.isAdmin == true {
            adminUsers = (try? await APIClient.listUsers()) ?? []
        } else {
            adminUsers = []
            ownerFilter = nil
        }
    }

    private func load() async {
        do {
            // only reassign when content changed — a no-op assignment every poll
            // re-renders the whole stack and dismisses any open menu/dialog
            let fresh = try await APIClient.listFiles()
            if fresh != files { files = fresh }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func handleImport(_ result: Result<[URL], Error>) async {
        guard case .success(let urls) = result else { return }
        for url in urls {
            let secured = url.startAccessingSecurityScopedResource()
            defer { if secured { url.stopAccessingSecurityScopedResource() } }
            do {
                uploadMessage = "Uploading \(url.lastPathComponent)…"
                try await APIClient.upload(fileURL: url)
                uploadMessage = "Queued ✓"
            } catch {
                uploadMessage = "Upload failed: \(error.localizedDescription)"
            }
        }
        await load()
        try? await Task.sleep(for: .seconds(3))
        uploadMessage = nil
    }
}

struct TileView: View {
    let file: RecordingFile
    var showOwner = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            thumbnail
            Text(file.displayName)
                .font(.caption2).foregroundStyle(.secondary)
                .lineLimit(2, reservesSpace: true)
                .multilineTextAlignment(.leading)
        }
    }

    private var thumbnail: some View {
        AsyncImage(url: APIClient.thumbURL(for: file)) { image in
            image.resizable().aspectRatio(contentMode: .fill)
        } placeholder: {
            Rectangle().fill(Color(white: 0.08))
                .overlay { ProgressView().tint(.gray) }
        }
        .aspectRatio(1, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(alignment: .topTrailing) {
            if !file.durationLabel.isEmpty {
                Text(file.durationLabel)
                    .font(.caption2.bold()).foregroundStyle(.white)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(.black.opacity(0.55), in: Capsule())
                    .padding(6)
            }
        }
        .overlay(alignment: .topLeading) {
            VStack(alignment: .leading, spacing: 4) {
                if showOwner, let owner = file.owner {
                    Text(owner)
                        .font(.caption2.bold()).foregroundStyle(.white)
                        .lineLimit(1)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(.black.opacity(0.55), in: Capsule())
                }
                if !file.isDone {
                    Text(file.status)
                        .font(.caption2.bold()).foregroundStyle(.white)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(file.status == "error" ? .red : .orange, in: Capsule())
                }
            }
            .padding(6)
        }
    }
}
