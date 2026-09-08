import Foundation

public enum TCPProviderMode: String, Codable, Equatable, Sendable {
    case nativeSysctl
    case netstatFallback
}

public actor FallbackTCPConnectionProvider: TCPConnectionProviding {
    private let primary: any TCPConnectionProviding
    private let fallback: any TCPConnectionProviding
    public private(set) var currentMode: TCPProviderMode = .nativeSysctl

    public init(primary: any TCPConnectionProviding = NativeTCPConnectionProvider(), fallback: any TCPConnectionProviding = NetstatTCPConnectionProvider()) {
        self.primary = primary
        self.fallback = fallback
    }

    public func snapshot() async throws -> [TCPConnectionRecord] {
        do {
            let records = try await primary.snapshot()
            currentMode = .nativeSysctl
            return records
        } catch {
            let records = try await fallback.snapshot()
            currentMode = .netstatFallback
            return records
        }
    }
}
