import XCTest
@testable import VNCPrivacyCore

final class SecurityCoordinatorTests: XCTestCase {
    func testRapidDisconnectDuringActivationNeverPublishesProtected() async {
        let display = DelayedDisplayPrivacyManager(delayNanoseconds: 50_000_000, activationResult: protectedResult); let power = RecordingPowerManager(); let coordinator = SecurityCoordinator(display: display, power: power)
        let activation = Task { await coordinator.handleSessionSnapshot(snapshot(count: 1)) }; try? await Task.sleep(nanoseconds: 5_000_000); await coordinator.handleSessionSnapshot(VNCSessionSnapshot(state: .disconnected, activeConnections: [])); await activation.value
        let status = await coordinator.status; XCTAssertNotEqual(status.phase, .protected); XCTAssertEqual(status.activeSessionCount, 0); let acquireCount = await power.acquireCount; let releaseCount = await power.releaseCount; let restoreCount = await display.restoreCount; XCTAssertEqual(acquireCount, 1); XCTAssertEqual(releaseCount, 1); XCTAssertGreaterThanOrEqual(restoreCount, 1)
    }
    func testTwoClientsDoNotRestoreUntilLastDisconnect() async {
        let display = DelayedDisplayPrivacyManager(delayNanoseconds: 0, activationResult: protectedResult); let power = RecordingPowerManager(); let coordinator = SecurityCoordinator(display: display, power: power)
        await coordinator.handleSessionSnapshot(snapshot(count: 2)); await coordinator.handleSessionSnapshot(snapshot(count: 1)); XCTAssertEqual(await display.restoreCount, 0); XCTAssertEqual((await coordinator.status).phase, .protected)
        await coordinator.handleSessionSnapshot(VNCSessionSnapshot(state: .disconnected, activeConnections: [])); XCTAssertEqual(await display.restoreCount, 1); XCTAssertEqual(await power.releaseCount, 1); XCTAssertEqual((await coordinator.status).phase, .idle)
    }
    func testPartialProtectionIsNeverReportedAsProtected() async {
        let partial = ProtectionResult(overall: .partialProtection, displays: [.init(displayID: 1, method: .hardwareBrightnessVerified),.init(displayID: 2, method: .unsupported)])
        let coordinator = SecurityCoordinator(display: DelayedDisplayPrivacyManager(delayNanoseconds: 0, activationResult: partial), power: RecordingPowerManager()); await coordinator.handleSessionSnapshot(snapshot(count: 1)); let status = await coordinator.status; XCTAssertEqual(status.phase, .errorDegraded); XCTAssertEqual(status.protection?.overall, .partialProtection)
    }
    private func snapshot(count: Int) -> VNCSessionSnapshot { VNCSessionSnapshot(state: .connected, activeConnections: (0..<count).map { VNCConnection(localAddress: "192.168.1.10", localPort: 5900, remoteAddress: "10.0.0.\($0 + 1)", remotePort: UInt16(50_000 + $0), firstSeen: Date(timeIntervalSince1970: 1_000)) }) }
}
private let protectedResult = ProtectionResult(overall: .protected, displays: [.init(displayID: 1, method: .hardwareBrightnessVerified)])
private actor DelayedDisplayPrivacyManager: DisplayPrivacyManaging { private let delayNanoseconds: UInt64; private let activationResult: ProtectionResult; private(set) var restoreCount = 0; init(delayNanoseconds: UInt64, activationResult: ProtectionResult) { self.delayNanoseconds = delayNanoseconds; self.activationResult = activationResult }; func activateProtection(reason: String) async -> ProtectionResult { if delayNanoseconds > 0 { try? await Task.sleep(nanoseconds: delayNanoseconds) }; return activationResult }; func maintainProtection() async -> ProtectionResult { activationResult }; func restoreDisplay() async -> Bool { restoreCount += 1; return true } }
private actor RecordingPowerManager: PowerAssertionManaging { private(set) var acquireCount = 0; private(set) var releaseCount = 0; func acquire() async throws { acquireCount += 1 }; func release() async { releaseCount += 1 } }
