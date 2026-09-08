import Foundation

public protocol ProtectionMaintaining: Sendable {
    func watchdogTick() async
}

extension SecurityCoordinator: ProtectionMaintaining {}

public actor ProtectionWatchdog {
    private let maintainer: any ProtectionMaintaining
    private let intervalNanoseconds: UInt64
    private var task: Task<Void, Never>?

    public init(maintainer: any ProtectionMaintaining, interval: TimeInterval = 1.0) {
        self.maintainer = maintainer
        self.intervalNanoseconds = UInt64(min(2.0, max(0.5, interval)) * 1_000_000_000)
    }

    public func tickOnce() async {
        await maintainer.watchdogTick()
    }

    public func start() {
        guard task == nil else { return }
        task = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    try await Task.sleep(nanoseconds: await self.interval())
                } catch {
                    return
                }
                await self.tickOnce()
            }
        }
    }

    public func stop() {
        task?.cancel()
        task = nil
    }

    private func interval() -> UInt64 { intervalNanoseconds }
}
