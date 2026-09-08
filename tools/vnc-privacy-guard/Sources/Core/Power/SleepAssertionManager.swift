import Foundation

public protocol PowerAssertionManaging: Sendable {
    func acquire() async throws
    func release() async
}

public protocol SleepAssertionBackend: Sendable {
    func createAssertion() async throws -> UInt32
    func releaseAssertion(_ id: UInt32) async
}

public enum SleepAssertionError: Error, Equatable, Sendable {
    case creationFailed(Int32)
}

public actor SleepAssertionManager: PowerAssertionManaging {
    private let backend: any SleepAssertionBackend
    private var assertionID: UInt32?

    public init(backend: any SleepAssertionBackend) {
        self.backend = backend
    }

    public func acquire() async throws {
        guard assertionID == nil else { return }
        assertionID = try await backend.createAssertion()
    }

    public func release() async {
        guard let id = assertionID else { return }
        assertionID = nil
        await backend.releaseAssertion(id)
    }

    public var isActive: Bool { assertionID != nil }
}

#if os(macOS)
import IOKit.pwr_mgt

public struct MacIOPMAssertionBackend: SleepAssertionBackend {
    public init() {}

    public func createAssertion() async throws -> UInt32 {
        var assertionID = IOPMAssertionID(0)
        let result = IOPMAssertionCreateWithName(
            kIOPMAssertionTypePreventUserIdleSystemSleep as CFString,
            IOPMAssertionLevel(kIOPMAssertionLevelOn),
            "VNC Privacy Guard active remote session" as CFString,
            &assertionID
        )
        guard result == kIOReturnSuccess else {
            throw SleepAssertionError.creationFailed(result)
        }
        return assertionID
    }

    public func releaseAssertion(_ id: UInt32) async {
        _ = IOPMAssertionRelease(IOPMAssertionID(id))
    }
}

public extension SleepAssertionManager {
    convenience init() {
        self.init(backend: MacIOPMAssertionBackend())
    }
}
#endif
