import Foundation
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

public protocol ProcessLivenessChecking: Sendable {
    func isProcessAlive(_ pid: Int32) -> Bool
}

public struct POSIXProcessLivenessChecker: ProcessLivenessChecking {
    public init() {}

    public func isProcessAlive(_ pid: Int32) -> Bool {
        guard pid > 0 else { return false }
        if kill(pid_t(pid), 0) == 0 { return true }
        return errno == EPERM
    }
}

public enum CrashRecoveryCheckOutcome: Equatable, Sendable {
    case noRecovery
    case ownerAlive
    case restored
    case recoveryFailed(String)
}

public actor CrashRecoverySupervisor {
    private let recoveryStore: any RecoveryStatePersisting
    private let liveness: any ProcessLivenessChecking
    private let restorer: any DisplayRestoring

    public init(
        recoveryStore: any RecoveryStatePersisting,
        liveness: any ProcessLivenessChecking = POSIXProcessLivenessChecker(),
        restorer: any DisplayRestoring
    ) {
        self.recoveryStore = recoveryStore
        self.liveness = liveness
        self.restorer = restorer
    }

    public func checkOnce() async -> CrashRecoveryCheckOutcome {
        let state: RecoveryState
        do {
            guard let loaded = try recoveryStore.load() else { return .noRecovery }
            try loaded.validate()
            state = loaded
        } catch {
            return .recoveryFailed(String(describing: error))
        }

        if let pid = state.processIdentifier, liveness.isProcessAlive(pid) {
            return .ownerAlive
        }

        let restored = await restorer.restoreDisplay()
        return restored ? .restored : .recoveryFailed("display restore verification failed")
    }
}
