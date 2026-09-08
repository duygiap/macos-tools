import XCTest
@testable import VNCPrivacyCore

final class CrashRecoverySupervisorTests: XCTestCase {
    func testOwnerStillAliveDoesNotRestore() async {
        let state = RecoveryState(displays: [.init(displayID: 1, originalBrightness: 0.8)], processIdentifier: 123, reason: "test")
        let restorer = SupervisorRestorer(result: true)
        let supervisor = CrashRecoverySupervisor(recoveryStore: SupervisorStore(state: state), liveness: StubLiveness(alivePIDs: [123]), restorer: restorer)
        let outcome = await supervisor.checkOnce()
        XCTAssertEqual(outcome, .ownerAlive)
        let calls = await restorer.calls
        XCTAssertEqual(calls, 0)
    }
    func testDeadOwnerRestoresPersistedDisplayState() async {
        let state = RecoveryState(displays: [.init(displayID: 1, originalBrightness: 0.8)], processIdentifier: 123, reason: "test")
        let restorer = SupervisorRestorer(result: true)
        let supervisor = CrashRecoverySupervisor(recoveryStore: SupervisorStore(state: state), liveness: StubLiveness(alivePIDs: []), restorer: restorer)
        let outcome = await supervisor.checkOnce()
        XCTAssertEqual(outcome, .restored)
        let calls = await restorer.calls
        XCTAssertEqual(calls, 1)
    }
    func testMalformedStateFailsSafelyWithoutCallingDisplay() async {
        let restorer = SupervisorRestorer(result: true)
        let supervisor = CrashRecoverySupervisor(recoveryStore: ThrowingSupervisorStore(error: RecoveryStoreError.corrupted("bad json")), liveness: StubLiveness(alivePIDs: []), restorer: restorer)
        let outcome = await supervisor.checkOnce()
        guard case .recoveryFailed = outcome else { return XCTFail("expected recoveryFailed, got \(outcome)") }
        let calls = await restorer.calls
        XCTAssertEqual(calls, 0)
    }
}
private struct StubLiveness: ProcessLivenessChecking { let alivePIDs: Set<Int32>; func isProcessAlive(_ pid: Int32) -> Bool { alivePIDs.contains(pid) } }
private final class SupervisorStore: RecoveryStatePersisting, @unchecked Sendable { let state: RecoveryState?; init(state: RecoveryState?) { self.state = state }; func load() throws -> RecoveryState? { state }; func persist(_ state: RecoveryState) throws {}; func clear() throws {} }
private final class ThrowingSupervisorStore: RecoveryStatePersisting, @unchecked Sendable { let error: Error; init(error: Error) { self.error = error }; func load() throws -> RecoveryState? { throw error }; func persist(_ state: RecoveryState) throws {}; func clear() throws {} }
private actor SupervisorRestorer: DisplayRestoring { let result: Bool; private(set) var calls = 0; init(result: Bool) { self.result = result }; func restoreDisplay() async -> Bool { calls += 1; return result } }
