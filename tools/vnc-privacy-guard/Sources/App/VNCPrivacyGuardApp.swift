import Foundation

@main
struct VNCPrivacyGuardBootstrap {
    static func main() {
        #if os(macOS)
        // Replaced by the SwiftUI menu-bar composition in the next TDD slice.
        #else
        print("VNC Privacy Guard is a macOS-only application.")
        #endif
    }
}
