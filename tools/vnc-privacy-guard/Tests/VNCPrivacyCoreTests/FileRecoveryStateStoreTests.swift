import XCTest
@testable import VNCPrivacyCore

final class FileRecoveryStateStoreTests: XCTestCase {
    func testRoundTripUses0600FileAnd0700Directory() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("vpg-store-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = FileRecoveryStateStore(directoryURL: directory)
        let state = RecoveryState(displays: [.init(displayID: 7, originalBrightness: 0.980469)], timestamp: Date(timeIntervalSince1970: 1234), processIdentifier: 42, reason: "test")
        try store.persist(state)
        XCTAssertEqual(try store.load(), state)
        let fileAttributes = try FileManager.default.attributesOfItem(atPath: store.stateURL.path)
        let dirAttributes = try FileManager.default.attributesOfItem(atPath: directory.path)
        XCTAssertEqual((fileAttributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        XCTAssertEqual((dirAttributes[.posixPermissions] as? NSNumber)?.intValue, 0o700)
    }
    func testClearRemovesOnlyRecoveryFile() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("vpg-store-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = FileRecoveryStateStore(directoryURL: directory)
        try store.persist(RecoveryState(displays: [.init(displayID: 1, originalBrightness: 0.5)], reason: "test"))
        try store.clear()
        XCTAssertNil(try store.load())
    }
    func testMalformedJSONThrowsCorruptedInsteadOfCrashing() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("vpg-store-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = FileRecoveryStateStore(directoryURL: directory)
        try Data("{not-json".utf8).write(to: store.stateURL)
        XCTAssertThrowsError(try store.load()) { error in guard case RecoveryStoreError.corrupted = error else { return XCTFail("unexpected error: \(error)") } }
    }
    func testInvalidSchemaIsRejected() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("vpg-store-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = FileRecoveryStateStore(directoryURL: directory)
        let invalid = RecoveryState(schemaVersion: 999, displays: [.init(displayID: 1, originalBrightness: 0.5)], reason: "test")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try JSONEncoder().encode(invalid).write(to: store.stateURL)
        XCTAssertThrowsError(try store.load()) { error in XCTAssertEqual(error as? RecoveryStoreError, .unsupportedSchema(999)) }
    }
    func testInvalidBrightnessIsRejected() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("vpg-store-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = FileRecoveryStateStore(directoryURL: directory)
        let invalid = RecoveryState(displays: [.init(displayID: 1, originalBrightness: 1.2)], reason: "test")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try JSONEncoder().encode(invalid).write(to: store.stateURL)
        XCTAssertThrowsError(try store.load()) { error in guard case RecoveryStoreError.invalidState = error else { return XCTFail("unexpected error: \(error)") } }
    }
}
