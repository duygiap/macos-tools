import Foundation

public enum SocketSnapshotParser {
    public static func parseNormalizedRow(_ row: String) -> TCPConnectionRecord? {
        let fields = row.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        guard fields.count == 5,
              let localPort = UInt16(fields[2]),
              let remotePort = UInt16(fields[4]) else { return nil }
        let state = TCPState(rawValue: fields[0]) ?? .unknown
        return TCPConnectionRecord(
            state: state,
            localAddress: fields[1],
            localPort: localPort,
            remoteAddress: fields[3],
            remotePort: remotePort
        )
    }
}

public enum VNCConnectionFilter {
    public static func activeConnections(_ records: [TCPConnectionRecord], localPort: UInt16 = 5900) -> [TCPConnectionRecord] {
        records.filter { $0.localPort == localPort && $0.state == .established }
    }

    public static func connectingConnections(_ records: [TCPConnectionRecord], localPort: UInt16 = 5900) -> [TCPConnectionRecord] {
        records.filter {
            $0.localPort == localPort && ($0.state == .synSent || $0.state == .synReceived)
        }
    }
}
