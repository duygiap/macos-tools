import Foundation

public protocol TCPConnectionProviding: Sendable {
    func snapshot() async throws -> [TCPConnectionRecord]
}

public enum TCPConnectionProviderError: Error, Equatable, Sendable {
    case unavailable(String)
    case executionFailed(String)
    case malformedOutput(String)
}
