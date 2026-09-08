import Foundation

public protocol DisplayPrivacyManaging: Sendable {
    func activateProtection(reason: String) async -> ProtectionResult
    func maintainProtection() async -> ProtectionResult
    func restoreDisplay() async -> Bool
}

extension DisplayPrivacyController: DisplayPrivacyManaging {}

public struct SecurityStatus: Equatable, Sendable {
    public let phase: SecurityPhase
    public let activeSessionCount: Int
    public let monitorState: VNCMonitorState
    public let protection: ProtectionResult?

    public init(phase: SecurityPhase, activeSessionCount: Int, monitorState: VNCMonitorState, protection: ProtectionResult?) {
        self.phase = phase
        self.activeSessionCount = activeSessionCount
        self.monitorState = monitorState
        self.protection = protection
    }
}

public actor SecurityCoordinator {
    private let display: any DisplayPrivacyManaging
    private let power: any PowerAssertionManaging
    private var machine = SecurityStateMachine()
    private var generation: UInt64 = 0
    private var activeSessionCount = 0
    private var monitorState: VNCMonitorState = .disconnected
    private var protection: ProtectionResult?

    public init(display: any DisplayPrivacyManaging, power: any PowerAssertionManaging) {
        self.display = display
        self.power = power
    }

    public var status: SecurityStatus {
        SecurityStatus(
            phase: machine.phase,
            activeSessionCount: activeSessionCount,
            monitorState: monitorState,
            protection: protection
        )
    }

    public func handleSessionSnapshot(_ snapshot: VNCSessionSnapshot) async {
        let newCount = snapshot.activeConnections.count
        monitorState = snapshot.state
        if newCount != activeSessionCount {
            generation &+= 1
        }
        activeSessionCount = newCount
        let operationGeneration = generation
        let actions = machine.handle(.sessionsChanged(newCount))
        await execute(actions, generation: operationGeneration)
    }

    public func watchdogTick() async {
        guard activeSessionCount > 0 else { return }
        let result = await display.maintainProtection()
        protection = result
        if result.overall == .protected {
            if machine.phase != .protected {
                _ = machine.handle(.activationSucceeded)
            }
        } else {
            _ = machine.handle(.activationFailed)
        }
    }

    public func emergencyRestore() async -> Bool {
        generation &+= 1
        let restored = await display.restoreDisplay()
        await power.release()
        protection = nil
        activeSessionCount = 0
        monitorState = .disconnected
        _ = machine.handle(restored ? .restoreSucceeded : .restoreFailed)
        return restored
    }

    private func execute(_ actions: [SecurityAction], generation operationGeneration: UInt64) async {
        for action in actions {
            switch action {
            case .acquireSleepAssertion:
                do {
                    try await power.acquire()
                } catch {
                    _ = machine.handle(.activationFailed)
                }

            case .activatePrivacy:
                guard operationGeneration == generation, activeSessionCount > 0 else { continue }
                _ = machine.handle(.savingDisplayStateStarted)
                _ = machine.handle(.activationStarted)
                let result = await display.activateProtection(reason: "VNC session established")
                guard operationGeneration == generation, activeSessionCount > 0 else {
                    _ = await display.restoreDisplay()
                    continue
                }
                protection = result
                if result.overall == .protected {
                    _ = machine.handle(.activationSucceeded)
                } else {
                    _ = machine.handle(.activationFailed)
                }

            case .maintainPrivacy:
                guard activeSessionCount > 0 else { continue }
                let result = await display.maintainProtection()
                protection = result
                if result.overall == .protected {
                    _ = machine.handle(.activationSucceeded)
                } else {
                    _ = machine.handle(.activationFailed)
                }

            case .deactivatePrivacy:
                let restored = await display.restoreDisplay()
                protection = nil
                _ = machine.handle(restored ? .restoreSucceeded : .restoreFailed)

            case .releaseSleepAssertion:
                await power.release()
            }
        }
    }
}
