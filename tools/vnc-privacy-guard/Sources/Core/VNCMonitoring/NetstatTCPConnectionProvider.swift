import Foundation

public enum NetstatTCPParser {
    public static func parse(_ output: String) -> [TCPConnectionRecord] {
        output.split(whereSeparator: \.isNewline).compactMap { parseLine(String($0)) }
    }

    public static func parseLine(_ line: String) -> TCPConnectionRecord? {
        let fields = line.split(whereSeparator: \.isWhitespace).map(String.init)
        guard fields.count >= 6, fields[0].hasPrefix("tcp") else { return nil }
        guard let local = parseEndpoint(fields[3]), let remote = parseEndpoint(fields[4]) else { return nil }
        return TCPConnectionRecord(
            state: mapState(fields[5]),
            localAddress: local.address,
            localPort: local.port,
            remoteAddress: remote.address,
            remotePort: remote.port
        )
    }

    private static func parseEndpoint(_ endpoint: String) -> (address: String, port: UInt16)? {
        if endpoint == "*.*" { return ("*", 0) }
        guard let separator = endpoint.lastIndex(of: ".") else { return nil }
        let address = String(endpoint[..<separator])
        let portText = String(endpoint[endpoint.index(after: separator)...])
        if portText == "*" { return (address.isEmpty ? "*" : address, 0) }
        guard let port = UInt16(portText) else { return nil }
        return (address.isEmpty ? "*" : address, port)
    }

    private static func mapState(_ state: String) -> TCPState {
        switch state.uppercased() {
        case "LISTEN": return .listen
        case "SYN_SENT": return .synSent
        case "SYN_RCVD", "SYN_RECEIVED": return .synReceived
        case "ESTABLISHED": return .established
        case "CLOSE_WAIT": return .closeWait
        case "FIN_WAIT_1": return .finWait1
        case "FIN_WAIT_2": return .finWait2
        case "CLOSING": return .closing
        case "LAST_ACK": return .lastAck
        case "TIME_WAIT": return .timeWait
        case "CLOSED": return .closed
        default: return .unknown
        }
    }
}

public struct NetstatTCPConnectionProvider: TCPConnectionProviding {
    public init() {}

    public func snapshot() async throws -> [TCPConnectionRecord] {
        try await Task.detached(priority: .utility) {
            let executable = URL(fileURLWithPath: "/usr/sbin/netstat")
            guard FileManager.default.isExecutableFile(atPath: executable.path) else {
                throw TCPConnectionProviderError.unavailable("/usr/sbin/netstat is unavailable")
            }

            let process = Process()
            process.executableURL = executable
            process.arguments = ["-anv", "-p", "tcp"]
            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr

            do {
                try process.run()
            } catch {
                throw TCPConnectionProviderError.executionFailed(error.localizedDescription)
            }
            process.waitUntilExit()

            let outputData = stdout.fileHandleForReading.readDataToEndOfFile()
            let errorData = stderr.fileHandleForReading.readDataToEndOfFile()
            guard process.terminationStatus == 0 else {
                let message = String(data: errorData, encoding: .utf8) ?? "exit \(process.terminationStatus)"
                throw TCPConnectionProviderError.executionFailed(message.trimmingCharacters(in: .whitespacesAndNewlines))
            }
            guard let output = String(data: outputData, encoding: .utf8) else {
                throw TCPConnectionProviderError.malformedOutput("netstat output was not UTF-8")
            }
            return NetstatTCPParser.parse(output)
        }.value
    }
}
