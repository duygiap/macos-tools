import XCTest
@testable import VNCPrivacyCore

final class DisconnectLockPolicyTests: XCTestCase {
    func testArmsAfterEstablishedSessionAndLocksWhenLastSessionDisconnects() {
        var policy = DisconnectLockPolicy()
        let active = snapshot(.connected, count: 1)
        let disconnected = snapshot(.disconnected, count: 0)

        XCTAssertFalse(policy.observe(active, protectionEnabled: true, lockOnDisconnect: true))
        XCTAssertTrue(policy.observe(disconnected, protectionEnabled: true, lockOnDisconnect: true))
        XCTAssertFalse(policy.observe(disconnected, protectionEnabled: true, lockOnDisconnect: true))
    }

    func testDoesNotLockWhenFeatureDisabled() {
        var policy = DisconnectLockPolicy()
        _ = policy.observe(snapshot(.connected, count: 1), protectionEnabled: true, lockOnDisconnect: false)

        XCTAssertFalse(policy.observe(snapshot(.disconnected, count: 0), protectionEnabled: true, lockOnDisconnect: false))
    }

    func testDoesNotLockWhenProtectionWasManuallyDisabled() {
        var policy = DisconnectLockPolicy()
        _ = policy.observe(snapshot(.connected, count: 1), protectionEnabled: true, lockOnDisconnect: true)
        policy.disarm()

        XCTAssertFalse(policy.observe(snapshot(.disconnected, count: 0), protectionEnabled: false, lockOnDisconnect: true))
    }

    func testUncertainStateDoesNotLockDuringGracePeriod() {
        var policy = DisconnectLockPolicy()
        _ = policy.observe(snapshot(.connected, count: 1), protectionEnabled: true, lockOnDisconnect: true)

        XCTAssertFalse(policy.observe(snapshot(.uncertain, count: 1, debouncing: true), protectionEnabled: true, lockOnDisconnect: true))
    }

    func testMultipleClientsLockOnlyAfterLastClientIsGone() {
        var policy = DisconnectLockPolicy()
        _ = policy.observe(snapshot(.connected, count: 2), protectionEnabled: true, lockOnDisconnect: true)

        XCTAssertFalse(policy.observe(snapshot(.connected, count: 1), protectionEnabled: true, lockOnDisconnect: true))
        XCTAssertTrue(policy.observe(snapshot(.disconnected, count: 0), protectionEnabled: true, lockOnDisconnect: true))
    }

    private func snapshot(_ state: VNCMonitorState, count: Int, debouncing: Bool = false) -> VNCSessionSnapshot {
        let connections = (0..<count).map { index in
            VNCConnection(
                localAddress: "192.168.1.10",
                localPort: 5900,
                remoteAddress: "100.64.0.\(index + 1)",
                remotePort: UInt16(50000 + index),
                firstSeen: Date(timeIntervalSince1970: 1_000)
            )
        }
        return VNCSessionSnapshot(state: state, activeConnections: connections, isDisconnectDebouncing: debouncing)
    }
}
