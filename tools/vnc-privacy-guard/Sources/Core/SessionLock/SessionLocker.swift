import Foundation

public protocol SessionLocking: Sendable {
    func lock() async throws
}

public enum SessionLockError: Error, Equatable, Sendable, CustomStringConvertible {
    case unavailable(String)
    case launchFailed(String)
    case commandFailed(Int32)

    public var description: String {
        switch self {
        case .unavailable(let path):
            return "Lock helper is unavailable at \(path)"
        case .launchFailed(let message):
            return "Unable to launch lock helper: \(message)"
        case .commandFailed(let status):
            return "Lock helper exited with status \(status)"
        }
    }
}

#if os(macOS)
public struct MacCGSessionLocker: SessionLocking {
    public static let defaultExecutablePath = "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession"

    private let executableURL: URL

    public init(executableURL: URL = URL(fileURLWithPath: Self.defaultExecutablePath)) {
        self.executableURL = executableURL
    }

    public func lock() async throws {
        let executableURL = self.executableURL
        guard FileManager.default.isExecutableFile(atPath: executableURL.path) else {
            throw SessionLockError.unavailable(executableURL.path)
        }

        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = executableURL
            process.arguments = ["-suspend"]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice

            do {
                try process.run()
            } catch {
                throw SessionLockError.launchFailed(error.localizedDescription)
            }

            process.waitUntilExit()
            guard process.terminationReason == .exit, process.terminationStatus == 0 else {
                throw SessionLockError.commandFailed(process.terminationStatus)
            }
        }.value
    }
}
#else
public struct MacCGSessionLocker: SessionLocking {
    public init() {}

    public func lock() async throws {
        throw SessionLockError.unavailable("macOS only")
    }
}
#endif
