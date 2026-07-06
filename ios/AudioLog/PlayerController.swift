import AVFoundation
import Foundation

/// Wraps AVPlayer for streaming playback with observable time/state.
@MainActor
final class PlayerController: ObservableObject {
    @Published var isPlaying = false
    @Published var currentTime: Double = 0
    @Published var duration: Double = 0

    private var player: AVPlayer?
    private var timeObserver: Any?

    func load(url: URL, fallbackDuration: Double?) {
        try? AVAudioSession.sharedInstance().setCategory(.playback)
        try? AVAudioSession.sharedInstance().setActive(true)
        let item = AVPlayerItem(url: url)
        let player = AVPlayer(playerItem: item)
        self.player = player
        duration = fallbackDuration ?? 0
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.5, preferredTimescale: 10),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.currentTime = time.seconds
                let itemDuration = player.currentItem?.duration.seconds ?? .nan
                if itemDuration.isFinite && itemDuration > 0 { self.duration = itemDuration }
                self.isPlaying = player.timeControlStatus == .playing
            }
        }
    }

    func toggle() {
        guard let player else { return }
        if player.timeControlStatus == .playing {
            player.pause()
        } else {
            // restart from the top when playback previously reached the end
            if duration > 0 && currentTime >= duration - 0.3 {
                player.seek(to: .zero)
            }
            player.play()
        }
        isPlaying = player.timeControlStatus == .playing
    }

    func seek(to seconds: Double) {
        player?.seek(to: CMTime(seconds: seconds, preferredTimescale: 600))
        currentTime = seconds
    }

    func stop() {
        if let timeObserver, let player { player.removeTimeObserver(timeObserver) }
        timeObserver = nil
        player?.pause()
        player = nil
    }
}
