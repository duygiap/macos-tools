import Foundation
import VNCPrivacyCore
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

@main
struct VNCPrivacyCLI {
    static func main() async {
        let store = FileRecoveryStateStore()
        let hardware = IntelIOKitBrightnessController()
        let controller = DisplayPrivacyController(hardware: hardware, recoveryStore: store)
        let service = EmergencyRecoveryService(recoveryStore: store, restorer: controller)
        let command = CommandLine.arguments.dropFirst().first

        switch command {
        case "status":
            printStatus(service.status())
        case "restore":
            if await service.restore() {
                print("Display restore verified; recovery state cleared.")
            } else {
                fputs("Display restore failed or could not be verified. Recovery state was preserved.\n", stderr)
                exit(2)
            }
        default:
            fputs("Usage: vncprivacy <status|restore>\n", stderr)
            exit(64)
        }
    }

    private static func printStatus(_ status: EmergencyRecoveryStatus) {
        switch status {
        case .healthy:
            print("Recovery state: Healthy")
        case .recoveryRequired(let state):
            print("Recovery state: RECOVERY REQUIRED")
            for display in state.displays {
                let formattedBrightness = String(format: "%.6f", display.originalBrightness)
                print("Display \(display.displayID): saved brightness \(formattedBrightness)")
            }
            print("Reason: \(state.reason)")
        case .invalidRecoveryState(let error):
            print("Recovery state: INVALID")
            print("Error: \(error)")
        }
    }
}
