import Foundation

public protocol SessionLocking: Sendable {
    func lock() async throws
}

public enum SessionLockError: Error, Equatable, Sendable, CustomStringConvertible {
    case unavailable(String)
    case symbolMissing(String)
    case lockRequestFailed(Int32)

    public var description: String {
        switch self {
        case .unavailable(let message):
            return "macOS lock framework unavailable: \(message)"
        case .symbolMissing(let symbol):
            return "macOS lock symbol is unavailable: \(symbol)"
        case .lockRequestFailed(let status):
            return "macOS lock request failed with status \(status)"
        }
    }
}

#if os(macOS)
import Darwin

public struct MacLoginFrameworkSessionLocker: SessionLocking {
    public static let frameworkPath = "/System/Library/PrivateFrameworks/login.framework/Versions/A/login"
    public static let lockSymbol = "SACLockScreenImmediate"

    private typealias LockFunction = @convention(c) () -> Int32

    public init() {}

    public static var isAvailable: Bool {
        guard let handle = dlopen(frameworkPath, RTLD_LAZY | RTLD_LOCAL) else {
            return false
        }
        defer { dlclose(handle) }
        return dlsym(handle, lockSymbol) != nil
    }

    public func lock() async throws {
        try await Task.detached(priority: .userInitiated) {
            guard let handle = dlopen(Self.frameworkPath, RTLD_LAZY | RTLD_LOCAL) else {
                let detail = dlerror().map { String(cString: $0) } ?? Self.frameworkPath
                throw SessionLockError.unavailable(detail)
            }
            defer { dlclose(handle) }

            guard let symbol = dlsym(handle, Self.lockSymbol) else {
                throw SessionLockError.symbolMissing(Self.lockSymbol)
            }

            let lockFunction = unsafeBitCast(symbol, to: LockFunction.self)
            let status = lockFunction()
            guard status == 0 else {
                throw SessionLockError.lockRequestFailed(status)
            }
        }.value
    }
}
#else
public struct MacLoginFrameworkSessionLocker: SessionLocking {
    public init() {}
    public static var isAvailable: Bool { false }

    public func lock() async throws {
        throw SessionLockError.unavailable("macOS only")
    }
}
#endif
