import XCTest
@testable import VNCPrivacyCore

final class RecoveryInvariantTests: XCTestCase {
    func testProtectionPersistsOriginalBrightnessBeforeBlanking() async throws {
        let recorder = EventRecorder()
        let hardware = RecordingBrightnessHardware(initial: 0.980469, recorder: recorder)
        let store = RecordingRecoveryStore(recorder: recorder)
        let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        let result = await controller.activateProtection(reason: "vnc")
        XCTAssertEqual(result.overall, .protected)
        XCTAssertNotNil(store.persisted?.displays.single)
        XCTAssertEqual(store.persisted!.displays.single!.originalBrightness, Float(0.980469), accuracy: Float(0.000001))
        XCTAssertEqual(recorder.events.first, "hardware.read:1:0.980469")
        let persistIndex = try XCTUnwrap(recorder.events.firstIndex(of: "store.persist:0.980469"))
        let zeroIndex = try XCTUnwrap(recorder.events.firstIndex(of: "hardware.set:1:0.0"))
        let verificationIndex = try XCTUnwrap(recorder.events.lastIndex(of: "hardware.read:1:0.0"))
        XCTAssertLessThan(persistIndex, zeroIndex)
        XCTAssertLessThan(zeroIndex, verificationIndex)
    }
    func testRepeatedActivationNeverOverwritesOriginalBrightnessWithZero() async throws {
        let recorder = EventRecorder(); let hardware = RecordingBrightnessHardware(initial: 0.75, recorder: recorder); let store = RecordingRecoveryStore(recorder: recorder); let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        _ = await controller.activateProtection(reason: "vnc"); _ = await controller.activateProtection(reason: "watchdog"); _ = await controller.activateProtection(reason: "watchdog")
        XCTAssertEqual(store.persistCalls, 1); XCTAssertEqual(store.persisted!.displays.single!.originalBrightness, Float(0.75), accuracy: Float(0.000001))
    }
    func testFailedPersistencePreventsZeroBrightnessWrite() async throws {
        let recorder = EventRecorder(); let hardware = RecordingBrightnessHardware(initial: 0.8, recorder: recorder); let store = RecordingRecoveryStore(recorder: recorder, failPersist: true); let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        let result = await controller.activateProtection(reason: "vnc")
        XCTAssertEqual(result.overall, .failed); XCTAssertFalse(recorder.events.contains("hardware.set:1:0.0"))
    }
    func testRestoreVerifiesBeforeClearingRecoveryState() async throws {
        let recorder = EventRecorder(); let hardware = RecordingBrightnessHardware(initial: 0.8, recorder: recorder); let store = RecordingRecoveryStore(recorder: recorder); let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        _ = await controller.activateProtection(reason: "vnc"); recorder.events.removeAll(); let restored = await controller.restoreDisplay()
        XCTAssertTrue(restored); XCTAssertEqual(recorder.events, ["hardware.set:1:0.8","hardware.read:1:0.8","store.clear"]); XCTAssertNil(store.persisted)
    }
    func testUnsupportedExternalDisplayPreventsFullProtectedStatus() async throws {
        let recorder = EventRecorder(); let hardware = RecordingBrightnessHardware(displays: [.init(id: 1, isBuiltIn: true, isOnline: true),.init(id: 2, isBuiltIn: false, isOnline: true)], brightness: [1: 0.6, 2: nil], recorder: recorder); let store = RecordingRecoveryStore(recorder: recorder); let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        let result = await controller.activateProtection(reason: "vnc")
        XCTAssertEqual(result.overall, .partialProtection); XCTAssertEqual(result.displays.first(where: { $0.displayID == 2 })?.method, .unsupported)
    }
}
private extension Array { var single: Element? { count == 1 ? first : nil } }
private final class EventRecorder: @unchecked Sendable { var events: [String] = [] }
private final class RecordingBrightnessHardware: @unchecked Sendable, DisplayBrightnessControlling {
    private let displayList: [DisplayDescriptor]; private var brightness: [UInt32: Float?]; private let recorder: EventRecorder
    convenience init(initial: Float, recorder: EventRecorder) { self.init(displays: [.init(id: 1, isBuiltIn: true, isOnline: true)], brightness: [1: initial], recorder: recorder) }
    init(displays: [DisplayDescriptor], brightness: [UInt32: Float?], recorder: EventRecorder) { self.displayList = displays; self.brightness = brightness; self.recorder = recorder }
    func displays() throws -> [DisplayDescriptor] { displayList }
    func currentBrightness(displayID: UInt32) throws -> Float? { let value = brightness[displayID] ?? nil; if let value { recorder.events.append("hardware.read:\(displayID):\(value)") } else { recorder.events.append("hardware.read:\(displayID):nil") }; return value }
    func setBrightness(displayID: UInt32, value: Float) throws { recorder.events.append("hardware.set:\(displayID):\(value)"); brightness[displayID] = value }
    func simulateExternalBrightness(displayID: UInt32, value: Float) { brightness[displayID] = value }
}
private final class RecordingRecoveryStore: @unchecked Sendable, RecoveryStatePersisting {
    var persisted: RecoveryState?; var persistCalls = 0; var failPersist: Bool; private let recorder: EventRecorder
    init(recorder: EventRecorder, failPersist: Bool = false) { self.recorder = recorder; self.failPersist = failPersist }
    func load() throws -> RecoveryState? { persisted }
    func persist(_ state: RecoveryState) throws { persistCalls += 1; if failPersist { throw RecoveryStoreError.writeFailed("simulated") }; persisted = state; let first = state.displays.first?.originalBrightness ?? -1; recorder.events.append("store.persist:\(first)") }
    func clear() throws { recorder.events.append("store.clear"); persisted = nil }
}
final class WatchdogReblankTests: XCTestCase {
    func testMaintainProtectionReblanksBrightnessDriftAndCountsEvent() async throws {
        let recorder = EventRecorder(); let hardware = RecordingBrightnessHardware(initial: 0.8, recorder: recorder); let store = RecordingRecoveryStore(recorder: recorder); let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        _ = await controller.activateProtection(reason: "vnc"); hardware.simulateExternalBrightness(displayID: 1, value: 0.5); recorder.events.removeAll(); let result = await controller.maintainProtection()
        XCTAssertEqual(result.overall, .protected); XCTAssertEqual(recorder.events, ["hardware.read:1:0.5","hardware.set:1:0.0","hardware.read:1:0.0"]); let count = await controller.reblankCount; XCTAssertEqual(count, 1)
    }
}
