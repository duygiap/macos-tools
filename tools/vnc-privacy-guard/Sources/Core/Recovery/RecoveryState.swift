import Foundation

public struct DisplayRecoverySnapshot: Codable, Equatable, Sendable {
    public let displayID: UInt32
    public let originalBrightness: Float

    public init(displayID: UInt32, originalBrightness: Float) {
        self.displayID = displayID
        self.originalBrightness = originalBrightness
    }
}

public struct RecoveryState: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let protectionWasActive: Bool
    public let displays: [DisplayRecoverySnapshot]
    public let timestamp: Date
    public let processIdentifier: Int32?
    public let reason: String

    public init(
        schemaVersion: Int = RecoveryState.currentSchemaVersion,
        protectionWasActive: Bool = true,
        displays: [DisplayRecoverySnapshot],
        timestamp: Date = Date(),
        processIdentifier: Int32? = nil,
        reason: String
    ) {
        self.schemaVersion = schemaVersion
        self.protectionWasActive = protectionWasActive
        self.displays = displays
        self.timestamp = timestamp
        self.processIdentifier = processIdentifier
        self.reason = reason
    }

    public func validate() throws {
        guard schemaVersion == Self.currentSchemaVersion else {
            throw RecoveryStoreError.unsupportedSchema(schemaVersion)
        }
        guard protectionWasActive else {
            throw RecoveryStoreError.invalidState("protectionWasActive is false")
        }
        guard !displays.isEmpty else {
            throw RecoveryStoreError.invalidState("no display snapshots")
        }
        for snapshot in displays {
            guard snapshot.originalBrightness.isFinite,
                  snapshot.originalBrightness >= 0,
                  snapshot.originalBrightness <= 1 else {
                throw RecoveryStoreError.invalidState("brightness outside 0...1")
            }
        }
    }
}

public enum RecoveryStoreError: Error, Equatable, Sendable {
    case writeFailed(String)
    case readFailed(String)
    case deleteFailed(String)
    case unsupportedSchema(Int)
    case invalidState(String)
    case corrupted(String)
}

public protocol RecoveryStatePersisting: Sendable {
    func load() throws -> RecoveryState?
    func persist(_ state: RecoveryState) throws
    func clear() throws
}
