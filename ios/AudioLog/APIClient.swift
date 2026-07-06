import Foundation

enum APIError: LocalizedError {
    case badURL
    case server(String)

    var errorDescription: String? {
        switch self {
        case .badURL: return "Invalid server URL — check Settings."
        case .server(let message): return message
        }
    }
}

/// Thin async client for the audio-log FastAPI server.
struct APIClient {
    static let defaultServer = "http://192.168.50.90:8300"

    static var serverURLString: String {
        UserDefaults.standard.string(forKey: "serverURL") ?? defaultServer
    }

    static var baseURL: URL? {
        URL(string: serverURLString.trimmingCharacters(in: .whitespaces))
    }

    static func url(_ path: String) throws -> URL {
        guard let base = baseURL, let url = URL(string: path, relativeTo: base) else {
            throw APIError.badURL
        }
        return url
    }

    static func thumbURL(for file: RecordingFile) -> URL? {
        try? url("/api/files/\(file.id)/thumb?v=3-\(String(file.createdAt.prefix(10)))")
    }

    static func audioURL(id: Int) -> URL? {
        try? url("/api/files/\(id)/audio?v=3")
    }

    private static func get<T: Decodable>(_ path: String) async throws -> T {
        let (data, response) = try await URLSession.shared.data(from: url(path))
        try check(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private static func send<T: Decodable>(_ path: String, method: String,
                                           body: Data? = nil,
                                           contentType: String? = nil) async throws -> T {
        var request = URLRequest(url: try url(path))
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = 600  // ask/translate can run a local LLM for minutes
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await URLSession.shared.data(for: request)
        try check(response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private static func check(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            struct Detail: Decodable { let detail: String }
            let message = (try? JSONDecoder().decode(Detail.self, from: data))?.detail
            throw APIError.server(message ?? "HTTP \(http.statusCode)")
        }
    }

    // MARK: - Endpoints

    static func listFiles() async throws -> [RecordingFile] {
        try await get("/api/files")
    }

    static func detail(id: Int) async throws -> FileDetail {
        try await get("/api/files/\(id)")
    }

    static func delete(id: Int) async throws {
        struct Deleted: Decodable { let deleted: Int }
        let _: Deleted = try await send("/api/files/\(id)", method: "DELETE")
    }

    static func rerun(id: Int) async throws {
        struct Status: Decodable { let status: String }
        let _: Status = try await send("/api/files/\(id)/rerun", method: "POST")
    }

    static func translate(id: Int) async throws -> String {
        let response: TranslateResponse = try await send("/api/files/\(id)/translate", method: "POST")
        return response.summaryZh
    }

    static func ask(question: String) async throws -> AskResponse {
        let body = try JSONEncoder().encode(["question": question])
        return try await send("/api/ask", method: "POST", body: body,
                              contentType: "application/json")
    }

    static func upload(fileURL: URL) async throws {
        let data = try Data(contentsOf: fileURL)
        try await upload(data: data, filename: fileURL.lastPathComponent)
    }

    static func upload(data: Data, filename: String) async throws {
        let boundary = "audiolog-\(UUID().uuidString)"
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        struct Saved: Decodable { let saved: String }
        let _: Saved = try await send("/api/upload", method: "POST", body: body,
                                      contentType: "multipart/form-data; boundary=\(boundary)")
    }
}
