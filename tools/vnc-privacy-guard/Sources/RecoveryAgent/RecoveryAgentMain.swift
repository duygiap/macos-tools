import Foundation
import VNCPrivacyCore

@main
struct RecoveryAgentMain {
    static func main() async {
        let store = FileRecoveryStateStore()
        let hardware = IntelIOKitBrightnessController()
        let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        let supervisor = CrashRecoverySupervisor(recoveryStore: store, restorer: controller)

        while !Task.isCancelled {
            _ = await supervisor.checkOnce()
            do {
                try await Task.sleep(nanoseconds: 1_000_000_000)
            } catch {
                return
            }
        }
    }
}
