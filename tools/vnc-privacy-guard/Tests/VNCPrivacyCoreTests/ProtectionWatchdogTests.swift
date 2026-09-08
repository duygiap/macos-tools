import XCTest
@testable import VNCPrivacyCore

final class ProtectionWatchdogTests: XCTestCase {
    func testTickOnceDelegatesOneMaintenanceCheck() async {
        let maintainer = RecordingProtectionMaintainer(); let watchdog = ProtectionWatchdog(maintainer: maintainer)
        await watchdog.tickOnce(); let count = await maintainer.tickCount; XCTAssertEqual(count, 1)
    }
}
private actor RecordingProtectionMaintainer: ProtectionMaintaining { private(set) var tickCount = 0; func watchdogTick() async { tickCount += 1 } }
