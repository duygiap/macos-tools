import Foundation

public protocol DisplayRestoring: Sendable {
    func restoreDisplay() async -> Bool
}

extension DisplayPrivacyController: DisplayRestoring {}

public enum StartupRecoveryOutcome: Equatable, Sendable {
    case clean
    case restored
    case failed(String)
}

public struct StartupRecoveryManager: Sendable {
    private let store: any RecoveryStatePersisting
    private let restorer: any DisplayRestoring

    public init(store: any RecoveryStatePersisting, restorer: any DisplayRestoring) {
        self.store = store
        self.restorer = restorer
    }

    public func recoverIfNeeded() async -> StartupRecoveryOutcome {
        do {
            guard let state = try store.load() else { return .clean }
            try state.validate()
            guard await restorer.restoreDisplay() else {
                return .failed("Display restore verification failed")
            }
            return .restored
        } catch {
            return .failed(String(describing: error))
        }
    }
}
