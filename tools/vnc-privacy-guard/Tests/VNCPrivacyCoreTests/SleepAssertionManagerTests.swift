import XCTest
@testable import VNCPrivacyCore

final class SleepAssertionManagerTests: XCTestCase {
    func testAcquireAndReleaseAreIdempotent() async throws {
        let backend = RecordingAssertionBackend(); let manager = SleepAssertionManager(backend: backend); try await manager.acquire(); try await manager.acquire(); await manager.release(); await manager.release(); let createCount = await backend.createCount; let releaseIDs = await backend.releaseIDs; XCTAssertEqual(createCount, 1); XCTAssertEqual(releaseIDs, [42])
    }
}
private actor RecordingAssertionBackend: SleepAssertionBackend { private(set) var createCount = 0; private(set) var releaseIDs: [UInt32] = []; func createAssertion() async throws -> UInt32 { createCount += 1; return 42 }; func releaseAssertion(_ id: UInt32) async { releaseIDs.append(id) } }
