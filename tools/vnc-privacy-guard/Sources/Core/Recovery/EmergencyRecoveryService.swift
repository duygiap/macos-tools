import Foundation

public enum EmergencyRecoveryStatus: Equatable, Sendable {
    case healthy
    case recoveryRequired(RecoveryState)
    case invalidRecoveryState(String)
}

public struct EmergencyRecoveryService: Sendable {
    private let recoveryStore: any RecoveryStatePersisting
    private let restorer: any DisplayRestoring

    public init(recoveryStore: any RecoveryStatePersisting, restorer: any DisplayRestoring) {
        self.recoveryStore = recoveryStore
        self.restorer = restorer
    }

    public func status() -> EmergencyRecoveryStatus {
        do {
            guard let state = try recoveryStore.load() else { return .healthy }
            try state.validate()
            return .recoveryRequired(state)
        } catch {
            return .invalidRecoveryState(String(describing: error))
        }
    }

    public func restore() async -> Bool {
        await restorer.restoreDisplay()
    }
}
