import XCTest
@testable import VNCPrivacyCore

final class CoreLogicTests: XCTestCase {
    func testTailscaleCGNATBoundaries() {
        XCTAssertTrue(TailscaleClassifier.isLikelyTailscaleIPv4("100.64.0.0"))
        XCTAssertTrue(TailscaleClassifier.isLikelyTailscaleIPv4("100.127.255.255"))
        XCTAssertFalse(TailscaleClassifier.isLikelyTailscaleIPv4("100.63.255.255"))
        XCTAssertFalse(TailscaleClassifier.isLikelyTailscaleIPv4("100.128.0.0"))
    }

    func testOnlyEstablished5900CountsAsActive() {
        let rows = [
            "LISTEN|0.0.0.0|5900|*|0",
            "SYN_RECEIVED|192.168.1.10|5900|100.64.1.5|50000",
            "ESTABLISHED|192.168.1.10|5900|100.64.1.6|50001",
            "ESTABLISHED|192.168.1.10|22|100.64.1.7|50002",
        ]
        let records = rows.compactMap(SocketSnapshotParser.parseNormalizedRow)
        let active = VNCConnectionFilter.activeConnections(records, localPort: 5900)
        XCTAssertEqual(active.count, 1)
        XCTAssertEqual(active.first?.remoteAddress, "100.64.1.6")
    }

    func testMultipleSessionsRestoreOnlyAtZero() {
        var machine = SecurityStateMachine()
        XCTAssertEqual(machine.handle(.sessionsChanged(1)), [.acquireSleepAssertion, .activatePrivacy])
        XCTAssertEqual(machine.phase, .vncDetected)
        _ = machine.handle(.savingDisplayStateStarted)
        XCTAssertEqual(machine.phase, .savingDisplayState)
        _ = machine.handle(.activationStarted)
        XCTAssertEqual(machine.phase, .activatingProtection)
        _ = machine.handle(.activationSucceeded)
        XCTAssertEqual(machine.phase, .protected)
        XCTAssertEqual(machine.handle(.sessionsChanged(2)), [])
        XCTAssertEqual(machine.handle(.sessionsChanged(1)), [])
        XCTAssertEqual(machine.handle(.sessionsChanged(0)), [.deactivatePrivacy, .releaseSleepAssertion])
        XCTAssertEqual(machine.phase, .restoring)
    }
}
