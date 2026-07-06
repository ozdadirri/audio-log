import Foundation

struct RecordingFile: Identifiable, Codable, Equatable {
    let id: Int
    let filename: String
    let title: String?
    let status: String
    let error: String?
    let language: String?
    let duration: Double?
    let owner: String?
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, filename, title, status, error, language, duration, owner
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    var displayName: String { title?.isEmpty == false ? title! : filename }

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
    let title: String?
    let status: String
    let error: String?
    let language: String?
    let duration: Double?
    let tags: String?
    let memExclude: Int?
    let createdAt: String
    let transcript: String?
    let summary: String?
    let summaryZh: String?

    enum CodingKeys: String, CodingKey {
        case id, filename, title, status, error, language, duration, tags,
             transcript, summary
        case memExclude = "mem_exclude"
        case createdAt = "created_at"
        case summaryZh = "summary_zh"
    }

    var tagList: [String] {
        (tags ?? "").split(separator: ",").map(String.init)
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

struct ChatTurn: Codable {
    let question: String
    let answer: String
}

struct MemoryStatus: Codable {
    let content: String?
    let contentZh: String?
    let updatedAt: String?
    let pending: Int

    enum CodingKeys: String, CodingKey {
        case content, pending
        case contentZh = "content_zh"
        case updatedAt = "updated_at"
    }
}

struct TranslateResponse: Codable {
    let summaryZh: String
    enum CodingKeys: String, CodingKey { case summaryZh = "summary_zh" }
}

struct Me: Codable {
    let id: Int
    let username: String
    let isAdmin: Bool
    enum CodingKeys: String, CodingKey {
        case id, username
        case isAdmin = "is_admin"
    }
}

struct UserAccount: Codable, Identifiable {
    let id: Int
    let username: String
    let apiKey: String
    let isAdmin: Int
    let fileCount: Int?   // absent in the create-user response

    enum CodingKeys: String, CodingKey {
        case id, username
        case apiKey = "api_key"
        case isAdmin = "is_admin"
        case fileCount = "file_count"
    }
}
