import Foundation

public struct DisplayDescriptor: Codable, Equatable, Hashable, Sendable {
    public let id: UInt32
    public let isBuiltIn: Bool
    public let isOnline: Bool

    public init(id: UInt32, isBuiltIn: Bool, isOnline: Bool) {
        self.id = id
        self.isBuiltIn = isBuiltIn
        self.isOnline = isOnline
    }
}

public enum DisplayProtectionMethod: String, Codable, Equatable, Sendable {
    case hardwareBrightnessVerified
    case unsupported
    case offline
    case failed
}

public struct DisplayProtectionStatus: Codable, Equatable, Sendable {
    public let displayID: UInt32
    public let method: DisplayProtectionMethod
    public let message: String?

    public init(displayID: UInt32, method: DisplayProtectionMethod, message: String? = nil) {
        self.displayID = displayID
        self.method = method
        self.message = message
    }
}

public enum ProtectionOverallStatus: String, Codable, Equatable, Sendable {
    case protected
    case partialProtection
    case unverified
    case failed
}

public struct ProtectionResult: Codable, Equatable, Sendable {
    public let overall: ProtectionOverallStatus
    public let displays: [DisplayProtectionStatus]

    public init(overall: ProtectionOverallStatus, displays: [DisplayProtectionStatus]) {
        self.overall = overall
        self.displays = displays
    }
}
