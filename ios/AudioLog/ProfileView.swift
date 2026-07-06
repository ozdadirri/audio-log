import SwiftUI

struct ProfileView: View {
    let me: Me?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 10) {
                        Image(systemName: "person.circle.fill")
                            .font(.system(size: 36)).foregroundStyle(Color.accentColor)
                        VStack(alignment: .leading) {
                            Text(me?.username ?? "(unknown)").font(.headline)
                            if me?.isAdmin == true {
                                Text("ADMIN").font(.caption2.bold())
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, 7).padding(.vertical, 2)
                                    .background(Color.accentColor, in: Capsule())
                            }
                        }
                    }
                } footer: {
                    Text("The API key in Settings is your login — to switch profiles, " +
                         "enter a different user's key there.")
                }

                if me?.isAdmin == true {
                    Section {
                        NavigationLink("Manage users") { UsersView() }
                    }
                }
            }
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close") { dismiss() } }
            }
        }
    }
}

struct UsersView: View {
    @State private var users: [UserAccount] = []
    @State private var newUsername = ""
    @State private var message: String?
    @State private var errorMessage: String?

    var body: some View {
        List {
            Section("Add user") {
                HStack {
                    TextField("username", text: $newUsername)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    Button("Add") { add() }
                        .disabled(newUsername.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                if let message {
                    Text(message).font(.footnote).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                if let errorMessage {
                    Text(errorMessage).font(.footnote).foregroundStyle(.red)
                }
            }

            Section("Users") {
                ForEach(users) { user in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(user.username).bold()
                            if user.isAdmin == 1 {
                                Text("ADMIN").font(.caption2.bold())
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, 6).padding(.vertical, 1)
                                    .background(Color.accentColor, in: Capsule())
                            }
                            Spacer()
                            Text("\(user.fileCount ?? 0) recordings")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Text(user.apiKey)
                            .font(.caption2.monospaced()).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    .swipeActions {
                        if user.isAdmin == 0 {
                            Button("Delete", role: .destructive) { remove(user) }
                        }
                    }
                }
            }
        }
        .navigationTitle("Users")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        do {
            users = try await APIClient.listUsers()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func add() {
        let username = newUsername.trimmingCharacters(in: .whitespaces)
        Task {
            do {
                let user = try await APIClient.createUser(username: username)
                message = "Created \(user.username) — key: \(user.apiKey)"
                errorMessage = nil
                newUsername = ""
                await load()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func remove(_ user: UserAccount) {
        Task {
            do {
                try await APIClient.deleteUser(id: user.id)
                await load()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
