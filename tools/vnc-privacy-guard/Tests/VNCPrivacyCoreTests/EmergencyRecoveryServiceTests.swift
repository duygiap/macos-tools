import XCTest
@testable import VNCPrivacyCore

final class EmergencyRecoveryServiceTests: XCTestCase {
    func testStatusReportsExactSavedBrightness() {
        let state = RecoveryState(displays: [.init(displayID: 9, originalBrightness: 0.980469)], reason: "test")
        let service = EmergencyRecoveryService(recoveryStore: EmergencyStore(state: state), restorer: EmergencyRestorer(result: true))
        XCTAssertEqual(service.status(), .recoveryRequired(state))
    }
    func testRestoreDelegatesToVerifiedRestorer() async {
        let restorer = EmergencyRestorer(result: true)
        let service = EmergencyRecoveryService(recoveryStore: EmergencyStore(state: nil), restorer: restorer)
        let restored = await service.restore()
        XCTAssertTrue(restored)
        let calls = await restorer.calls
        XCTAssertEqual(calls, 1)
    }
}
private final class EmergencyStore: RecoveryStatePersisting, @unchecked Sendable { let state: RecoveryState?; init(state: RecoveryState?) { self.state = state }; func load() throws -> RecoveryState? { state }; func persist(_ state: RecoveryState) throws {}; func clear() throws {} }
private actor EmergencyRestorer: DisplayRestoring { let result: Bool; private(set) var calls = 0; init(result: Bool) { self.result = result }; func restoreDisplay() async -> Bool { calls += 1; return result } }
