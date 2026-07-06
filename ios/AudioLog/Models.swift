import Foundation

struct RecordingFile: Identifiable, Codable, Equatable {
    let id: Int
    let filename: String
    let status: String
    let error: String?
    let language: String?
    let duration: Double?
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, filename, status, error, language, duration
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    var createdDate: Date {
        ISO8601DateFormatter().date(from: createdAt) ?? Date()
    }

    var durationLabel: String {
        guard let d = duration else { return "" }
        let s = Int(d.rounded())
        return String(format: "%d:%02d", s / 60, s % 60)
    }

    var isDone: Bool { status == "done" }
}

struct FileDetail: Codable {
    let id: Int
    let filename: String
    let status: String
    let error: String?
    let language: String?
    let duration: Double?
    let createdAt: String
    let transcript: String?
    let summary: String?
    let summaryZh: String?

    enum CodingKeys: String, CodingKey {
        case id, filename, status, error, language, duration, transcript, summary
        case createdAt = "created_at"
        case summaryZh = "summary_zh"
    }
}

struct TranscriptSegment: Identifiable {
    let id = UUID()
    let start: Double
    let text: String

    var startLabel: String {
        let s = Int(start)
        return String(format: "%d:%02d", s / 60, s % 60)
    }

    /// Parse "**[mm:ss]** text" lines out of a transcript markdown document.
    static func parse(_ markdown: String) -> [TranscriptSegment] {
        var segments: [TranscriptSegment] = []
        for line in markdown.split(separator: "\n") {
            guard let match = line.wholeMatch(of: /\*\*\[(\d+):(\d{2})\]\*\*\s*(.*)/) else { continue }
            let start = (Double(match.1) ?? 0) * 60 + (Double(match.2) ?? 0)
            segments.append(TranscriptSegment(start: start, text: String(match.3)))
        }
        return segments
    }
}

struct AskSource: Codable, Identifiable {
    let id: Int
    let filename: String
}

struct AskResponse: Codable {
    let answer: String
    let sources: [AskSource]
}

struct TranslateResponse: Codable {
    let summaryZh: String
    enum CodingKeys: String, CodingKey { case summaryZh = "summary_zh" }
}
