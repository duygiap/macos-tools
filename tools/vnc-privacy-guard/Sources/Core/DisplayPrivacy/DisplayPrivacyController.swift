import Foundation

public actor DisplayPrivacyController {
    public static let blankVerificationThreshold: Float = 0.02
    public static let restoreVerificationTolerance: Float = 0.02

    private let hardware: any DisplayBrightnessControlling
    private let recoveryStore: any RecoveryStatePersisting
    private var activeRecoveryState: RecoveryState?
    private(set) public var reblankCount: UInt64 = 0

    public init(hardware: any DisplayBrightnessControlling, recoveryStore: any RecoveryStatePersisting) {
        self.hardware = hardware
        self.recoveryStore = recoveryStore
    }

    public func activateProtection(reason: String) async -> ProtectionResult {
        let state: RecoveryState
        do {
            if let activeRecoveryState {
                state = activeRecoveryState
            } else if let persisted = try recoveryStore.load() {
                try persisted.validate()
                state = persisted
                activeRecoveryState = persisted
            } else {
                let online = try hardware.displays().filter(\.isOnline)
                var snapshots: [DisplayRecoverySnapshot] = []
                snapshots.reserveCapacity(online.count)

                for display in online {
                    guard let brightness = try hardware.currentBrightness(displayID: display.id) else { continue }
                    guard brightness.isFinite, brightness >= 0, brightness <= 1 else {
                        return ProtectionResult(
                            overall: .failed,
                            displays: [DisplayProtectionStatus(displayID: display.id, method: .failed, message: "Invalid brightness readback")]
                        )
                    }
                    snapshots.append(.init(displayID: display.id, originalBrightness: brightness))
                }

                guard !snapshots.isEmpty else {
                    return ProtectionResult(overall: .failed, displays: [])
                }

                let newState = RecoveryState(
                    displays: snapshots,
                    processIdentifier: Int32(ProcessInfo.processInfo.processIdentifier),
                    reason: reason
                )
                try newState.validate()
                try recoveryStore.persist(newState)
                state = newState
                activeRecoveryState = newState
            }
        } catch {
            return ProtectionResult(overall: .failed, displays: [])
        }

        return applyZeroBrightness(using: state)
    }

    public func maintainProtection() async -> ProtectionResult {
        guard let state = activeRecoveryState ?? (try? recoveryStore.load()) else {
            return ProtectionResult(overall: .failed, displays: [])
        }
        return applyZeroBrightness(using: state, countReblank: true)
    }

    public func restoreDisplay() async -> Bool {
        let state: RecoveryState
        do {
            if let activeRecoveryState {
                state = activeRecoveryState
            } else if let persisted = try recoveryStore.load() {
                try persisted.validate()
                state = persisted
            } else {
                return true
            }
        } catch {
            return false
        }

        var allRestored = true
        for snapshot in state.displays {
            do {
                try hardware.setBrightness(displayID: snapshot.displayID, value: snapshot.originalBrightness)
                guard let actual = try hardware.currentBrightness(displayID: snapshot.displayID),
                      abs(actual - snapshot.originalBrightness) <= Self.restoreVerificationTolerance else {
                    allRestored = false
                    continue
                }
            } catch {
                allRestored = false
            }
        }

        guard allRestored else { return false }

        do {
            try recoveryStore.clear()
            activeRecoveryState = nil
            return true
        } catch {
            return false
        }
    }

    public func currentRecoveryState() -> RecoveryState? {
        activeRecoveryState ?? (try? recoveryStore.load())
    }

    private func applyZeroBrightness(using state: RecoveryState, countReblank: Bool = false) -> ProtectionResult {
        let descriptors: [DisplayDescriptor]
        do {
            descriptors = try hardware.displays()
        } catch {
            return ProtectionResult(overall: .failed, displays: [])
        }

        let snapshotIDs = Set(state.displays.map(\.displayID))
        var statuses: [DisplayProtectionStatus] = []
        var didReblank = false

        for display in descriptors where display.isOnline {
            guard snapshotIDs.contains(display.id) else {
                statuses.append(.init(displayID: display.id, method: .unsupported, message: "Brightness control unavailable"))
                continue
            }

            do {
                let before = try hardware.currentBrightness(displayID: display.id)
                if let before, before > Self.blankVerificationThreshold {
                    didReblank = countReblank
                }
                try hardware.setBrightness(displayID: display.id, value: 0)
                guard let actual = try hardware.currentBrightness(displayID: display.id),
                      actual <= Self.blankVerificationThreshold else {
                    statuses.append(.init(displayID: display.id, method: .failed, message: "Brightness readback did not verify blank"))
                    continue
                }
                statuses.append(.init(displayID: display.id, method: .hardwareBrightnessVerified))
            } catch {
                statuses.append(.init(displayID: display.id, method: .failed, message: String(describing: error)))
            }
        }

        if didReblank { reblankCount &+= 1 }

        let onlineCount = descriptors.filter(\.isOnline).count
        let verifiedCount = statuses.filter { $0.method == .hardwareBrightnessVerified }.count
        let unsupportedCount = statuses.filter { $0.method == .unsupported }.count
        let failedCount = statuses.filter { $0.method == .failed }.count

        let overall: ProtectionOverallStatus
        if onlineCount > 0 && verifiedCount == onlineCount {
            overall = .protected
        } else if verifiedCount > 0 && (unsupportedCount > 0 || failedCount > 0) {
            overall = .partialProtection
        } else if failedCount > 0 {
            overall = .failed
        } else {
            overall = .unverified
        }

        if overall == .failed {
            _ = tryRestoreAfterActivationFailure(state)
        }

        return ProtectionResult(overall: overall, displays: statuses)
    }

    private func tryRestoreAfterActivationFailure(_ state: RecoveryState) -> Bool {
        var success = true
        for snapshot in state.displays {
            do {
                try hardware.setBrightness(displayID: snapshot.displayID, value: snapshot.originalBrightness)
                guard let actual = try hardware.currentBrightness(displayID: snapshot.displayID),
                      abs(actual - snapshot.originalBrightness) <= Self.restoreVerificationTolerance else {
                    success = false
                    continue
                }
            } catch {
                success = false
            }
        }
        if success {
            do {
                try recoveryStore.clear()
                activeRecoveryState = nil
            } catch {
                success = false
            }
        }
        return success
    }
}
