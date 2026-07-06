import AVFoundation
import SwiftUI

@MainActor
final class Recorder: ObservableObject {
    @Published var isRecording = false
    @Published var elapsed: TimeInterval = 0
    @Published var errorMessage: String?

    private var recorder: AVAudioRecorder?
    private var timer: Timer?
    private(set) var fileURL: URL?

    func start() {
        AVAudioSession.sharedInstance().requestRecordPermission { granted in
            Task { @MainActor in
                guard granted else {
                    self.errorMessage = "Microphone access denied — enable it in Settings."
                    return
                }
                self.beginRecording()
            }
        }
    }

    private func beginRecording() {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default)
            try session.setActive(true)

            let stamp = Date().formatted(.iso8601.year().month().day()
                .dateTimeSeparator(.standard).time(includingFractionalSeconds: false))
                .replacingOccurrences(of: ":", with: "-")
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent("recording-\(stamp).m4a")
            let settings: [String: Any] = [
                AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
                AVSampleRateKey: 44_100,
                AVNumberOfChannelsKey: 1,
                AVEncoderBitRateKey: 96_000,
            ]
            let recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder.record()
            self.recorder = recorder
            fileURL = url
            elapsed = 0
            isRecording = true
            timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in
                    self?.elapsed = self?.recorder?.currentTime ?? 0
                }
            }
        } catch {
            errorMessage = "Could not start recording: \(error.localizedDescription)"
        }
    }

    /// Stops and returns the recorded file URL (nil if nothing was captured).
    func stop() -> URL? {
        timer?.invalidate()
        timer = nil
        recorder?.stop()
        recorder = nil
        isRecording = false
        return fileURL
    }
}

struct RecordView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var recorder = Recorder()
    @State private var uploading = false
    @State private var statusMessage: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 28) {
                Text(timeLabel)
                    .font(.system(size: 54, weight: .bold).monospacedDigit())

                Button {
                    recorder.isRecording ? finish() : recorder.start()
                } label: {
                    ZStack {
                        Circle()
                            .fill(recorder.isRecording ? .red : Color.accentColor)
                            .frame(width: 92, height: 92)
                        Image(systemName: recorder.isRecording ? "stop.fill" : "mic.fill")
                            .font(.system(size: 34)).foregroundStyle(.white)
                    }
                }
                .buttonStyle(.plain)
                .disabled(uploading)

                if uploading { ProgressView("Uploading…") }
                if let message = statusMessage ?? recorder.errorMessage {
                    Text(message).font(.footnote).foregroundStyle(.secondary)
                        .multilineTextAlignment(.center).padding(.horizontal)
                }
                Spacer()
            }
            .padding(.top, 60)
            .navigationTitle("Record")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Close") {
                        _ = recorder.stop()
                        dismiss()
                    }
                }
            }
        }
    }

    private var timeLabel: String {
        let s = Int(recorder.elapsed)
        return String(format: "%d:%02d", s / 60, s % 60)
    }

    private func finish() {
        guard let url = recorder.stop() else { return }
        uploading = true
        Task {
            defer { uploading = false }
            do {
                try await APIClient.upload(fileURL: url)
                statusMessage = "Queued for transcription ✓"
                try? await Task.sleep(for: .seconds(1))
                dismiss()
            } catch {
                statusMessage = "Upload failed: \(error.localizedDescription)"
            }
        }
    }
}
