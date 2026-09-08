import Foundation

public struct DisconnectLockPolicy: Sendable {
    private var armed = false

    public init() {}

    public mutating func observe(
        _ snapshot: VNCSessionSnapshot,
        protectionEnabled: Bool,
        lockOnDisconnect: Bool
    ) -> Bool {
        guard protectionEnabled else {
            armed = false
            return false
        }

        if snapshot.shouldProtect {
            armed = lockOnDisconnect
            return false
        }

        guard lockOnDisconnect else {
            armed = false
            return false
        }

        guard armed,
              snapshot.state == .disconnected,
              !snapshot.isDisconnectDebouncing else {
            return false
        }

        armed = false
        return true
    }

    public mutating func disarm() {
        armed = false
    }
}
