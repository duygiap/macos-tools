import Foundation
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

public final class FileRecoveryStateStore: @unchecked Sendable, RecoveryStatePersisting {
    public let directoryURL: URL
    public let stateURL: URL

    private let fileManager: FileManager
    private let lock = NSLock()

    public init(directoryURL: URL, fileManager: FileManager = .default) {
        self.directoryURL = directoryURL
        self.stateURL = directoryURL.appendingPathComponent("recovery-state.json", isDirectory: false)
        self.fileManager = fileManager
    }

    public convenience init(fileManager: FileManager = .default) {
        let base: URL
        if let applicationSupport = try? fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ) {
            base = applicationSupport
        } else {
            base = fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support", isDirectory: true)
        }
        self.init(directoryURL: base.appendingPathComponent("VNCPrivacyGuard", isDirectory: true), fileManager: fileManager)
    }

    public func load() throws -> RecoveryState? {
        try lock.withLock {
            guard fileManager.fileExists(atPath: stateURL.path) else { return nil }
            let data: Data
            do {
                data = try Data(contentsOf: stateURL, options: [.mappedIfSafe])
            } catch {
                throw RecoveryStoreError.readFailed(error.localizedDescription)
            }

            let state: RecoveryState
            do {
                state = try JSONDecoder().decode(RecoveryState.self, from: data)
            } catch {
                throw RecoveryStoreError.corrupted(error.localizedDescription)
            }
            try state.validate()
            return state
        }
    }

    public func persist(_ state: RecoveryState) throws {
        try state.validate()
        try lock.withLock {
            do {
                try ensureDirectory()
                let encoder = JSONEncoder()
                encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
                let data = try encoder.encode(state)
                try atomicDurableWrite(data)
            } catch let error as RecoveryStoreError {
                throw error
            } catch {
                throw RecoveryStoreError.writeFailed(error.localizedDescription)
            }
        }
    }

    public func clear() throws {
        try lock.withLock {
            guard fileManager.fileExists(atPath: stateURL.path) else { return }
            do {
                try fileManager.removeItem(at: stateURL)
                try syncDirectoryBestEffort()
            } catch {
                throw RecoveryStoreError.deleteFailed(error.localizedDescription)
            }
        }
    }

    private func ensureDirectory() throws {
        if !fileManager.fileExists(atPath: directoryURL.path) {
            try fileManager.createDirectory(
                at: directoryURL,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: NSNumber(value: Int16(0o700))]
            )
        }
        try fileManager.setAttributes(
            [.posixPermissions: NSNumber(value: Int16(0o700))],
            ofItemAtPath: directoryURL.path
        )
    }

    private func atomicDurableWrite(_ data: Data) throws {
        let temporaryURL = directoryURL.appendingPathComponent(".recovery-state.\(UUID().uuidString).tmp")
        var fd: Int32 = -1
        defer {
            if fd >= 0 { _ = systemClose(fd) }
            try? fileManager.removeItem(at: temporaryURL)
        }

        fd = systemOpen(temporaryURL.path, O_WRONLY | O_CREAT | O_EXCL, 0o600)
        guard fd >= 0 else {
            throw RecoveryStoreError.writeFailed("open temporary file failed: errno \(errno)")
        }

        let writtenAll = data.withUnsafeBytes { rawBuffer -> Bool in
            guard let base = rawBuffer.baseAddress else { return data.isEmpty }
            var remaining = rawBuffer.count
            var offset = 0
            while remaining > 0 {
                let count = systemWrite(fd, base.advanced(by: offset), remaining)
                if count < 0 {
                    if errno == EINTR { continue }
                    return false
                }
                remaining -= count
                offset += count
            }
            return true
        }
        guard writtenAll else {
            throw RecoveryStoreError.writeFailed("write temporary file failed: errno \(errno)")
        }
        guard systemFSync(fd) == 0 else {
            throw RecoveryStoreError.writeFailed("fsync temporary file failed: errno \(errno)")
        }
        guard systemClose(fd) == 0 else {
            fd = -1
            throw RecoveryStoreError.writeFailed("close temporary file failed: errno \(errno)")
        }
        fd = -1

        guard systemRename(temporaryURL.path, stateURL.path) == 0 else {
            throw RecoveryStoreError.writeFailed("atomic rename failed: errno \(errno)")
        }
        try fileManager.setAttributes(
            [.posixPermissions: NSNumber(value: Int16(0o600))],
            ofItemAtPath: stateURL.path
        )
        try syncDirectoryBestEffort()
    }

    private func syncDirectoryBestEffort() throws {
        let directoryFD = systemOpen(directoryURL.path, O_RDONLY, 0)
        guard directoryFD >= 0 else { return }
        defer { _ = systemClose(directoryFD) }
        if systemFSync(directoryFD) != 0 {
            #if os(macOS)
            if errno != EINVAL && errno != ENOTSUP {
                throw RecoveryStoreError.writeFailed("fsync directory failed: errno \(errno)")
            }
            #endif
        }
    }
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}

private func systemOpen(_ path: String, _ flags: Int32, _ mode: mode_t) -> Int32 {
    path.withCString { pointer in
        #if canImport(Darwin)
        Darwin.open(pointer, flags, mode)
        #else
        Glibc.open(pointer, flags, mode)
        #endif
    }
}

private func systemClose(_ fd: Int32) -> Int32 {
    #if canImport(Darwin)
    Darwin.close(fd)
    #else
    Glibc.close(fd)
    #endif
}

private func systemWrite(_ fd: Int32, _ buffer: UnsafeRawPointer, _ count: Int) -> Int {
    #if canImport(Darwin)
    Darwin.write(fd, buffer, count)
    #else
    Glibc.write(fd, buffer, count)
    #endif
}

private func systemFSync(_ fd: Int32) -> Int32 {
    #if canImport(Darwin)
    Darwin.fsync(fd)
    #else
    Glibc.fsync(fd)
    #endif
}

private func systemRename(_ from: String, _ to: String) -> Int32 {
    from.withCString { fromPtr in
        to.withCString { toPtr in
            #if canImport(Darwin)
            Darwin.rename(fromPtr, toPtr)
            #else
            Glibc.rename(fromPtr, toPtr)
            #endif
        }
    }
}
