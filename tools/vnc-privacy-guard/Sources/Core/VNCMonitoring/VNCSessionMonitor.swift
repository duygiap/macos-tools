import Foundation

public protocol SessionMonitoring: Sendable {
    func start(handler: @escaping @Sendable (VNCSessionSnapshot) async -> Void) async
    func stop() async
}

public actor VNCSessionMonitor: SessionMonitoring {
    private let provider: any TCPConnectionProviding
    private let pollIntervalNanoseconds: UInt64
    private var tracker: VNCSessionTracker
    private var pollingTask: Task<Void, Never>?
    private var handler: (@Sendable (VNCSessionSnapshot) async -> Void)?
    private var lastEmitted: VNCSessionSnapshot?
    public private(set) var currentSnapshot = VNCSessionSnapshot(state: .disconnected, activeConnections: [])

    public init(
        provider: any TCPConnectionProviding,
        localPort: UInt16 = 5900,
        pollInterval: TimeInterval = 1.0,
        disconnectDebounce: TimeInterval = 2.0
    ) {
        self.provider = provider
        self.pollIntervalNanoseconds = UInt64(max(0.1, pollInterval) * 1_000_000_000)
        self.tracker = VNCSessionTracker(localPort: localPort, disconnectDebounce: disconnectDebounce)
    }

    @discardableResult
    public func pollOnce(now: Date = Date()) async -> VNCSessionSnapshot? {
        let snapshot: VNCSessionSnapshot
        do {
            snapshot = tracker.update(records: try await provider.snapshot(), now: now)
        } catch {
            snapshot = tracker.providerFailed(now: now)
        }
        currentSnapshot = snapshot
        guard snapshot != lastEmitted else { return nil }
        lastEmitted = snapshot
        if let handler {
            await handler(snapshot)
        }
        return snapshot
    }

    public func start(handler: @escaping @Sendable (VNCSessionSnapshot) async -> Void) async {
        self.handler = handler
        guard pollingTask == nil else { return }
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                _ = await self.pollOnce()
                do {
                    try await Task.sleep(nanoseconds: await self.pollIntervalNanosecondsValue())
                } catch {
                    return
                }
            }
        }
    }

    public func stop() async {
        pollingTask?.cancel()
        pollingTask = nil
        handler = nil
    }

    private func pollIntervalNanosecondsValue() -> UInt64 {
        pollIntervalNanoseconds
    }
}
