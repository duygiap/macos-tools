import Foundation

public enum SecurityPhase: String, Codable, Equatable, Sendable {
    case idle
    case recovering
    case vncDetected
    case savingDisplayState
    case activatingProtection
    case protected
    case restoring
    case errorDegraded
    case recoveryFailed
}

public enum SecurityEvent: Equatable, Sendable {
    case sessionsChanged(Int)
    case savingDisplayStateStarted
    case activationStarted
    case activationSucceeded
    case activationFailed
    case restoreSucceeded
    case restoreFailed
    case driftDetected
}

public enum SecurityAction: Equatable, Sendable {
    case acquireSleepAssertion
    case activatePrivacy
    case maintainPrivacy
    case deactivatePrivacy
    case releaseSleepAssertion
}

public struct SecurityStateMachine: Sendable {
    public private(set) var phase: SecurityPhase = .idle
    private var activeSessions: Int = 0

    public init() {}

    public mutating func handle(_ event: SecurityEvent) -> [SecurityAction] {
        switch event {
        case .sessionsChanged(let count):
            let previous = activeSessions
            activeSessions = max(0, count)
            if previous == 0 && activeSessions > 0 {
                phase = .vncDetected
                return [.acquireSleepAssertion, .activatePrivacy]
            }
            if previous > 0 && activeSessions == 0 {
                phase = .restoring
                return [.deactivatePrivacy, .releaseSleepAssertion]
            }
            return []

        case .savingDisplayStateStarted:
            guard activeSessions > 0 else { return [] }
            phase = .savingDisplayState
            return []

        case .activationStarted:
            guard activeSessions > 0 else { return [] }
            phase = .activatingProtection
            return []

        case .activationSucceeded:
            guard activeSessions > 0 else { return [] }
            phase = .protected
            return []

        case .activationFailed:
            phase = .errorDegraded
            return []

        case .restoreSucceeded:
            phase = .idle
            return []

        case .restoreFailed:
            phase = .recoveryFailed
            return []

        case .driftDetected:
            guard phase == .protected else { return [] }
            phase = .activatingProtection
            return [.maintainPrivacy]
        }
    }
}
