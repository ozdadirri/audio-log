import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage("serverURL") private var serverURL = APIClient.defaultServer
    @State private var testResult: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.1.20:8300", text: $serverURL)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                } header: {
                    Text("Server")
                } footer: {
                    Text("The audio-log server on your Mac. Find its address with " +
                         "`ipconfig getifaddr en0` and start it with --host 0.0.0.0.")
                }

                Section {
                    Button("Test connection") { test() }
                    if let testResult {
                        Text(testResult).font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Done") { dismiss() } }
            }
        }
    }

    private func test() {
        testResult = "Testing…"
        Task {
            do {
                let files = try await APIClient.listFiles()
                testResult = "Connected ✓ — \(files.count) recordings"
            } catch {
                testResult = "Failed: \(error.localizedDescription)"
            }
        }
    }
}
