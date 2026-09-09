import Foundation

public enum VNCMonitorState: String, Codable, Equatable, Sendable {
    case disconnected
    case connecting
    case connected
    case uncertain
}

public struct VNCSessionSnapshot: Equatable, Sendable {
    public let state: VNCMonitorState
    public let activeConnections: [VNCConnection]
    public let isDisconnectDebouncing: Bool

    public init(state: VNCMonitorState, activeConnections: [VNCConnection], isDisconnectDebouncing: Bool = false) {
        self.state = state
        self.activeConnections = activeConnections
        self.isDisconnectDebouncing = isDisconnectDebouncing
    }

    public var shouldProtect: Bool { !activeConnections.isEmpty }
}

public struct VNCSessionTracker: Sendable {
    private struct Key: Hashable, Sendable {
        let localAddress: String
        let localPort: UInt16
        let remoteAddress: String
        let remotePort: UInt16

        init(_ record: TCPConnectionRecord) {
            self.localAddress = record.localAddress
            self.localPort = record.localPort
            self.remoteAddress = record.remoteAddress
            self.remotePort = record.remotePort
        }
    }

    private let localPort: UInt16
    private let disconnectDebounce: TimeInterval
    private var activeByKey: [Key: VNCConnection] = [:]
    private var disconnectStartedAt: Date?
    private var providerFailureStartedAt: Date?

    public init(localPort: UInt16 = 5900, disconnectDebounce: TimeInterval = 2.0) {
        self.localPort = localPort
        self.disconnectDebounce = max(0, disconnectDebounce)
    }

    public mutating func update(records: [TCPConnectionRecord], now: Date = Date()) -> VNCSessionSnapshot {
        providerFailureStartedAt = nil

        let established = VNCConnectionFilter.activeConnections(records, localPort: localPort)
        if !established.isEmpty {
            var next: [Key: VNCConnection] = [:]
            for record in established {
                let key = Key(record)
                if let existing = activeByKey[key] {
                    next[key] = existing
                } else {
                    next[key] = VNCConnection(
                        localAddress: record.localAddress,
                        localPort: record.localPort,
                        remoteAddress: record.remoteAddress,
                        remotePort: record.remotePort,
                        firstSeen: now
                    )
                }
            }
            activeByKey = next
            disconnectStartedAt = nil
            return snapshot(state: .connected, debouncing: false)
        }

        if !activeByKey.isEmpty {
            if disconnectStartedAt == nil {
                disconnectStartedAt = now
            }
            let elapsed = now.timeIntervalSince(disconnectStartedAt ?? now)
            if elapsed < disconnectDebounce {
                return snapshot(state: .connected, debouncing: true)
            }
            activeByKey.removeAll()
            disconnectStartedAt = nil
        }

        if !VNCConnectionFilter.connectingConnections(records, localPort: localPort).isEmpty {
            return VNCSessionSnapshot(state: .connecting, activeConnections: [], isDisconnectDebouncing: false)
        }
        return VNCSessionSnapshot(state: .disconnected, activeConnections: [], isDisconnectDebouncing: false)
    }

    public mutating func providerFailed(now: Date = Date()) -> VNCSessionSnapshot {
        guard !activeByKey.isEmpty else {
            providerFailureStartedAt = providerFailureStartedAt ?? now
            return VNCSessionSnapshot(state: .uncertain, activeConnections: [], isDisconnectDebouncing: false)
        }

        if providerFailureStartedAt == nil {
            providerFailureStartedAt = disconnectStartedAt ?? now
        }

        let elapsed = now.timeIntervalSince(providerFailureStartedAt ?? now)
        if elapsed < disconnectDebounce {
            return snapshot(state: .uncertain, debouncing: true)
        }

        activeByKey.removeAll()
        disconnectStartedAt = nil
        providerFailureStartedAt = nil
        return VNCSessionSnapshot(state: .disconnected, activeConnections: [], isDisconnectDebouncing: false)
    }

    private func snapshot(state: VNCMonitorState, debouncing: Bool) -> VNCSessionSnapshot {
        let connections = activeByKey.values.sorted {
            if $0.remoteAddress == $1.remoteAddress { return $0.remotePort < $1.remotePort }
            return $0.remoteAddress < $1.remoteAddress
        }
        return VNCSessionSnapshot(state: state, activeConnections: connections, isDisconnectDebouncing: debouncing)
    }
}
