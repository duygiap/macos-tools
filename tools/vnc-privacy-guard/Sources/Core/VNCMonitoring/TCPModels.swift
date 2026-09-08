import Foundation

public enum TCPState: String, Codable, Equatable, Sendable {
    case listen = "LISTEN"
    case synSent = "SYN_SENT"
    case synReceived = "SYN_RECEIVED"
    case established = "ESTABLISHED"
    case closeWait = "CLOSE_WAIT"
    case finWait1 = "FIN_WAIT_1"
    case finWait2 = "FIN_WAIT_2"
    case closing = "CLOSING"
    case lastAck = "LAST_ACK"
    case timeWait = "TIME_WAIT"
    case closed = "CLOSED"
    case unknown = "UNKNOWN"
}

public struct TCPConnectionRecord: Codable, Equatable, Hashable, Sendable {
    public let state: TCPState
    public let localAddress: String
    public let localPort: UInt16
    public let remoteAddress: String
    public let remotePort: UInt16

    public init(state: TCPState, localAddress: String, localPort: UInt16, remoteAddress: String, remotePort: UInt16) {
        self.state = state
        self.localAddress = localAddress
        self.localPort = localPort
        self.remoteAddress = remoteAddress
        self.remotePort = remotePort
    }
}

public struct VNCConnection: Codable, Equatable, Hashable, Sendable {
    public let localAddress: String
    public let localPort: UInt16
    public let remoteAddress: String
    public let remotePort: UInt16
    public let firstSeen: Date

    public init(localAddress: String, localPort: UInt16, remoteAddress: String, remotePort: UInt16, firstSeen: Date = Date()) {
        self.localAddress = localAddress
        self.localPort = localPort
        self.remoteAddress = remoteAddress
        self.remotePort = remotePort
        self.firstSeen = firstSeen
    }

    public var likelyTailscalePeer: Bool {
        TailscaleClassifier.isLikelyTailscaleIPv4(remoteAddress)
    }
}
