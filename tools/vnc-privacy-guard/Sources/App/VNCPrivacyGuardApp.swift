import Foundation
import VNCPrivacyCore

#if os(macOS)
import AppKit
import ServiceManagement

actor RuntimeEngine {
    private let store: FileRecoveryStateStore
    private let display: DisplayPrivacyController
    private let coordinator: SecurityCoordinator
    private let monitor: VNCSessionMonitor
    private let watchdog: ProtectionWatchdog
    private var running = false

    init() {
        let store = FileRecoveryStateStore()
        let display = DisplayPrivacyController(
            hardware: IntelIOKitBrightnessController(),
            recoveryStore: store
        )
        let coordinator = SecurityCoordinator(
            display: display,
            power: SleepAssertionManager()
        )
        let provider = FallbackTCPConnectionProvider(
            primary: NativeTCPConnectionProvider(localPortFilter: 5900),
            fallback: NetstatTCPConnectionProvider()
        )

        self.store = store
        self.display = display
        self.coordinator = coordinator
        self.monitor = VNCSessionMonitor(
            provider: provider,
            localPort: 5900,
            pollInterval: 1.0,
            disconnectDebounce: 2.0
        )
        self.watchdog = ProtectionWatchdog(maintainer: coordinator, interval: 1.0)
    }

    func start(statusHandler: @escaping @Sendable (SecurityStatus) async -> Void) async -> StartupRecoveryOutcome {
        guard !running else {
            await statusHandler(await coordinator.status)
            return .clean
        }

        let recovery = await StartupRecoveryManager(store: store, restorer: display).recoverIfNeeded()
        if case .failed = recovery {
            return recovery
        }

        running = true
        let coordinator = self.coordinator
        await monitor.start { snapshot in
            await coordinator.handleSessionSnapshot(snapshot)
            await statusHandler(await coordinator.status)
        }
        await watchdog.start()
        await statusHandler(await coordinator.status)
        return recovery
    }

    func stopAndRestore() async -> Bool {
        await monitor.stop()
        await watchdog.stop()
        running = false
        return await coordinator.emergencyRestore()
    }

    func restoreDisplay() async -> Bool {
        await coordinator.emergencyRestore()
    }

    func blankNow() async -> ProtectionResult {
        await display.activateProtection(reason: "Manual Blank Now")
    }
}

@MainActor
final class MenuBarAppDelegate: NSObject, NSApplicationDelegate {
    private let engine = RuntimeEngine()
    private var statusItem: NSStatusItem!
    private var statusMenuItem: NSMenuItem!
    private var protectionMenuItem: NSMenuItem!
    private var launchAtLoginMenuItem: NSMenuItem!
    private var protectionEnabled = true
    private var terminationInProgress = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureStatusItem()
        refreshLaunchAtLoginState()
        startProtectionEngine()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !terminationInProgress else { return .terminateLater }
        terminationInProgress = true
        statusMenuItem.title = "Restoring display before quit…"

        Task { [weak self] in
            guard let self else {
                sender.reply(toApplicationShouldTerminate: true)
                return
            }
            let restored = await self.engine.stopAndRestore()
            await MainActor.run {
                if restored {
                    sender.reply(toApplicationShouldTerminate: true)
                } else {
                    self.terminationInProgress = false
                    let alert = NSAlert()
                    alert.alertStyle = .critical
                    alert.messageText = "Display brightness could not be restored."
                    alert.informativeText = "VNC Privacy Guard kept the recovery record. Retry Restore before quitting, or force quit only if you can recover over SSH."
                    alert.addButton(withTitle: "Retry Restore")
                    alert.addButton(withTitle: "Force Quit")
                    let response = alert.runModal()
                    if response == .alertSecondButtonReturn {
                        sender.reply(toApplicationShouldTerminate: true)
                    } else {
                        sender.reply(toApplicationShouldTerminate: false)
                        self.restoreDisplay(nil)
                    }
                }
            }
        }
        return .terminateLater
    }

    private func configureStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "shield", accessibilityDescription: "VNC Privacy Guard")
        statusItem.button?.toolTip = "VNC Privacy Guard"

        let menu = NSMenu()
        statusMenuItem = NSMenuItem(title: "Starting…", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        menu.addItem(statusMenuItem)
        menu.addItem(.separator())

        protectionMenuItem = NSMenuItem(title: "Protection Enabled", action: #selector(toggleProtection(_:)), keyEquivalent: "")
        protectionMenuItem.target = self
        protectionMenuItem.state = .on
        menu.addItem(protectionMenuItem)

        let blankItem = NSMenuItem(title: "Blank Now", action: #selector(blankNow(_:)), keyEquivalent: "")
        blankItem.target = self
        menu.addItem(blankItem)

        let restoreItem = NSMenuItem(title: "Restore Display", action: #selector(restoreDisplay(_:)), keyEquivalent: "")
        restoreItem.target = self
        menu.addItem(restoreItem)

        menu.addItem(.separator())
        launchAtLoginMenuItem = NSMenuItem(title: "Launch at Login", action: #selector(toggleLaunchAtLogin(_:)), keyEquivalent: "")
        launchAtLoginMenuItem.target = self
        menu.addItem(launchAtLoginMenuItem)

        menu.addItem(.separator())
        let aboutItem = NSMenuItem(title: "About VNC Privacy Guard", action: #selector(showAbout(_:)), keyEquivalent: "")
        aboutItem.target = self
        menu.addItem(aboutItem)

        let quitItem = NSMenuItem(title: "Quit VNC Privacy Guard", action: #selector(quit(_:)), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem.menu = menu
    }

    private func startProtectionEngine() {
        statusMenuItem.title = "Starting protection engine…"
        Task { [weak self] in
            guard let self else { return }
            let outcome = await self.engine.start { [weak self] status in
                guard let self else { return }
                await self.apply(status: status)
            }
            await self.apply(recoveryOutcome: outcome)
        }
    }

    @objc private func toggleProtection(_ sender: NSMenuItem) {
        protectionEnabled.toggle()
        protectionMenuItem.state = protectionEnabled ? .on : .off

        if protectionEnabled {
            startProtectionEngine()
        } else {
            statusMenuItem.title = "Protection disabled — restoring display…"
            Task { [weak self] in
                guard let self else { return }
                let restored = await self.engine.stopAndRestore()
                await MainActor.run {
                    self.statusMenuItem.title = restored
                        ? "Protection disabled"
                        : "RECOVERY REQUIRED — restore failed"
                    self.updateIcon(warning: !restored, protected: false)
                }
            }
        }
    }

    @objc private func blankNow(_ sender: NSMenuItem) {
        Task { [weak self] in
            guard let self else { return }
            let result = await self.engine.blankNow()
            await MainActor.run {
                let protected = result.overall == .protected
                self.statusMenuItem.title = protected
                    ? "Protected — manual blank"
                    : "Warning — manual blank not fully verified"
                self.updateIcon(warning: !protected, protected: protected)
            }
        }
    }

    @objc private func restoreDisplay(_ sender: NSMenuItem?) {
        Task { [weak self] in
            guard let self else { return }
            let restored = await self.engine.restoreDisplay()
            await MainActor.run {
                self.statusMenuItem.title = restored ? "Display restored" : "RECOVERY REQUIRED — restore failed"
                self.updateIcon(warning: !restored, protected: false)
            }
        }
    }

    @objc private func toggleLaunchAtLogin(_ sender: NSMenuItem) {
        do {
            let service = SMAppService.mainApp
            if service.status == .enabled {
                try service.unregister()
            } else {
                try service.register()
            }
            refreshLaunchAtLoginState()
        } catch {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "Unable to change Launch at Login"
            alert.informativeText = error.localizedDescription
            alert.runModal()
            refreshLaunchAtLoginState()
        }
    }

    private func refreshLaunchAtLoginState() {
        launchAtLoginMenuItem?.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    @objc private func showAbout(_ sender: NSMenuItem) {
        let alert = NSAlert()
        alert.messageText = "VNC Privacy Guard"
        alert.informativeText = "Native Intel macOS privacy guard. It watches established VNC/Screen Sharing sessions on TCP 5900 and uses IOKit display brightness control so the physical panel can be dark while the remote desktop remains interactive."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    @objc private func quit(_ sender: NSMenuItem) {
        NSApp.terminate(nil)
    }

    private func apply(recoveryOutcome: StartupRecoveryOutcome) {
        switch recoveryOutcome {
        case .clean:
            break
        case .restored:
            statusMenuItem.title = "Recovered previous display state"
        case .failed(let message):
            statusMenuItem.title = "RECOVERY REQUIRED"
            updateIcon(warning: true, protected: false)
            let alert = NSAlert()
            alert.alertStyle = .critical
            alert.messageText = "Previous display state could not be recovered"
            alert.informativeText = message
            alert.addButton(withTitle: "Restore Display")
            alert.runModal()
        }
    }

    private func apply(status: SecurityStatus) {
        let count = status.activeSessionCount
        let sessions = count == 1 ? "1 VNC session" : "\(count) VNC sessions"

        switch status.phase {
        case .idle:
            statusMenuItem.title = "Idle — No VNC connection"
            updateIcon(warning: false, protected: false)
        case .recovering:
            statusMenuItem.title = "Recovering previous display state…"
            updateIcon(warning: false, protected: false)
        case .vncDetected, .savingDisplayState, .activatingProtection:
            statusMenuItem.title = "Securing display — \(sessions)"
            updateIcon(warning: false, protected: false)
        case .protected:
            if status.protection?.overall == .protected {
                statusMenuItem.title = "Protected — \(sessions)"
                updateIcon(warning: false, protected: true)
            } else {
                statusMenuItem.title = "Partial/Unverified — \(sessions)"
                updateIcon(warning: true, protected: false)
            }
        case .restoring:
            statusMenuItem.title = "Restoring display…"
            updateIcon(warning: false, protected: false)
        case .errorDegraded:
            statusMenuItem.title = "Warning — VNC active, protection not verified"
            updateIcon(warning: true, protected: false)
        case .recoveryFailed:
            statusMenuItem.title = "RECOVERY REQUIRED"
            updateIcon(warning: true, protected: false)
        }
    }

    private func updateIcon(warning: Bool, protected: Bool) {
        let symbol: String
        if warning {
            symbol = "exclamationmark.triangle.fill"
        } else if protected {
            symbol = "eye.slash.fill"
        } else {
            symbol = "shield"
        }
        statusItem.button?.image = NSImage(systemSymbolName: symbol, accessibilityDescription: "VNC Privacy Guard")
    }
}

@main
struct VNCPrivacyGuardApplication {
    static func main() {
        let app = NSApplication.shared
        let delegate = MenuBarAppDelegate()
        app.delegate = delegate
        app.run()
        _ = delegate
    }
}
#else
@main
struct VNCPrivacyGuardApplication {
    static func main() {
        print("VNC Privacy Guard is a macOS-only application.")
    }
}
#endif
