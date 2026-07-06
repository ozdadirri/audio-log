# AudioLog for iPhone & iPad (SwiftUI)

Native client for the audio-log server: library grid with spectrogram
thumbnails grouped by day, streaming playback with a transcript that highlights
and scrolls in sync (tap a line to seek), summaries with an EN/中文 toggle,
Ask AI with tappable sources, native mic recording (uploads m4a into the
pipeline), file upload from the Files app, re-run, and delete.

Requires iOS/iPadOS 17+ and Xcode 16+.

## Build & run

1. Open `ios/AudioLog.xcodeproj` in Xcode.
2. Select the **AudioLog** target → Signing & Capabilities → choose your
   **Team** (a free Apple ID works; apps signed with a free account must be
   re-installed every 7 days). Change the bundle identifier if Xcode complains
   it's taken.
3. Start the server on the Mac so devices can reach it:
   `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300 --reload`
4. Pick your iPhone/iPad (or a simulator) as the run destination and hit ⌘R.
5. In the app, open **Settings (gear icon)** and set the server URL to your
   Mac's LAN address, e.g. `http://192.168.50.90:8300`, then "Test connection".

Notes:

- HTTP (not HTTPS) to the local server is allowed via
  `NSAppTransportSecurity/NSAllowsArbitraryLoads` in `Info.plist` — fine for a
  personal LAN app; tighten to `NSAllowsLocalNetworking` if you prefer.
- Unlike the web/PWA version, **mic recording works natively** here (no
  secure-context restriction): the mic button records m4a and uploads it.
- This project was scaffolded without Xcode available to compile it, so the
  first build may surface small fixable errors.
