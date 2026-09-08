import Foundation
import CTCPSocketSnapshot

public enum NativeTCPStateMapper {
    public static func map(_ state: Int32) -> TCPState {
        switch state {
        case 0: return .closed
        case 1: return .listen
        case 2: return .synSent
        case 3: return .synReceived
        case 4: return .established
        case 5: return .closeWait
        case 6: return .finWait1
        case 7: return .closing
        case 8: return .lastAck
        case 9: return .finWait2
        case 10: return .timeWait
        default: return .unknown
        }
    }
}

public struct NativeTCPConnectionProvider: TCPConnectionProviding {
    public let localPortFilter: UInt16

    public init(localPortFilter: UInt16 = 0) {
        self.localPortFilter = localPortFilter
    }

    public func snapshot() async throws -> [TCPConnectionRecord] {
        let filter = localPortFilter
        return try await Task.detached(priority: .utility) {
            var buffer: UnsafeMutablePointer<CChar>?
            var length = 0
            let status = vpg_copy_tcp_snapshot(filter, &buffer, &length)
            defer { vpg_free_tcp_snapshot(buffer) }
            guard status == 0 else {
                throw TCPConnectionProviderError.unavailable("native TCP sysctl provider failed with errno \(status)")
            }
            guard length == 0 || buffer != nil else {
                throw TCPConnectionProviderError.malformedOutput("native TCP provider returned a null buffer")
            }
            guard length > 0, let buffer else { return [] }
            let data = Data(bytes: buffer, count: length)
            guard let text = String(data: data, encoding: .utf8) else {
                throw TCPConnectionProviderError.malformedOutput("native TCP snapshot was not UTF-8")
            }
            return text
                .split(whereSeparator: \.isNewline)
                .compactMap { SocketSnapshotParser.parseNormalizedRow(String($0)) }
        }.value
    }
}
