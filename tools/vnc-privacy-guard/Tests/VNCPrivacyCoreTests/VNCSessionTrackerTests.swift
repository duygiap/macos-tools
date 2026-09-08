import XCTest
@testable import VNCPrivacyCore

final class VNCSessionTrackerTests: XCTestCase {
    private let base = Date(timeIntervalSince1970: 1_000)

    func testListenOnlyIsDisconnected() {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let snapshot = tracker.update(records: [record(.listen, remote: "*")], now: base)
        XCTAssertEqual(snapshot.state, .disconnected)
        XCTAssertEqual(snapshot.activeConnections.count, 0)
    }

    func testSynReceivedReportsConnectingButDoesNotCountActive() {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let snapshot = tracker.update(records: [record(.synReceived, remote: "100.64.1.2")], now: base)
        XCTAssertEqual(snapshot.state, .connecting)
        XCTAssertEqual(snapshot.activeConnections.count, 0)
    }

    func testTwoEstablishedClientsRemainProtectedUntilLastConfirmedDisconnect() throws {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let a = record(.established, remote: "100.64.1.2", remotePort: 50001)
        let b = record(.established, remote: "192.168.1.20", remotePort: 50002)

        var snapshot = tracker.update(records: [a, b], now: base)
        XCTAssertEqual(snapshot.activeConnections.count, 2)

        snapshot = tracker.update(records: [b], now: base.addingTimeInterval(0.5))
        XCTAssertEqual(snapshot.activeConnections.count, 1)

        snapshot = tracker.update(records: [], now: base.addingTimeInterval(1.0))
        XCTAssertTrue(snapshot.isDisconnectDebouncing)

        snapshot = tracker.update(records: [], now: base.addingTimeInterval(3.1))
        XCTAssertEqual(snapshot.state, .disconnected)
    }

    func testRapidReconnectCancelsPendingDisconnectWithoutZeroCountTransition() {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let a = record(.established, remote: "100.64.1.2", remotePort: 50001)
        _ = tracker.update(records: [a], now: base)
        _ = tracker.update(records: [], now: base.addingTimeInterval(0.5))

        let reconnected = tracker.update(records: [a], now: base.addingTimeInterval(1.0))
        XCTAssertEqual(reconnected.state, .connected)
        XCTAssertEqual(reconnected.activeConnections.first?.firstSeen, base)
    }

    func testProviderFailureNeverPrematurelyDropsActiveSession() {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let a = record(.established, remote: "100.64.1.2", remotePort: 50001)
        _ = tracker.update(records: [a], now: base)

        let uncertain = tracker.providerFailed(now: base.addingTimeInterval(10))
        XCTAssertEqual(uncertain.state, .uncertain)
        XCTAssertTrue(uncertain.shouldProtect)
    }

    func testRepeatedProviderFailureFailsClosedAfterGracePeriod() {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let a = record(.established, remote: "100.64.1.2", remotePort: 50001)
        _ = tracker.update(records: [a], now: base)

        let firstFailure = tracker.providerFailed(now: base.addingTimeInterval(0.5))
        XCTAssertEqual(firstFailure.state, .uncertain)
        XCTAssertTrue(firstFailure.shouldProtect)

        let sustainedFailure = tracker.providerFailed(now: base.addingTimeInterval(2.6))
        XCTAssertEqual(sustainedFailure.state, .disconnected)
        XCTAssertFalse(sustainedFailure.shouldProtect)
    }

    func testSuccessfulSnapshotCancelsProviderFailureGracePeriod() {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let a = record(.established, remote: "100.64.1.2", remotePort: 50001)
        _ = tracker.update(records: [a], now: base)
        _ = tracker.providerFailed(now: base.addingTimeInterval(0.5))

        let recovered = tracker.update(records: [a], now: base.addingTimeInterval(1.0))
        XCTAssertEqual(recovered.state, .connected)
        XCTAssertTrue(recovered.shouldProtect)

        let freshFailure = tracker.providerFailed(now: base.addingTimeInterval(3.0))
        XCTAssertEqual(freshFailure.state, .uncertain)
        XCTAssertTrue(freshFailure.shouldProtect)
    }

    func testTailscaleLabelIsInformational() {
        var tracker = VNCSessionTracker(disconnectDebounce: 2)
        let snapshot = tracker.update(records: [record(.established, remote: "100.127.255.1")], now: base)
        XCTAssertEqual(snapshot.activeConnections.first?.likelyTailscalePeer, true)
    }

    private func record(_ state: TCPState, remote: String, remotePort: UInt16 = 50000) -> TCPConnectionRecord {
        TCPConnectionRecord(
            state: state,
            localAddress: "192.168.1.10",
            localPort: 5900,
            remoteAddress: remote,
            remotePort: remotePort
        )
    }
}
