# VNC Privacy Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native, lightweight macOS menu-bar application that detects real established VNC/Screen Sharing sessions and protects physical displays without interrupting the remote framebuffer, while restoring display state safely after the final disconnect.

**Architecture:** A dependency-free Swift package separates pure logic from macOS system adapters. A native Darwin TCP PCB provider detects `ESTABLISHED` sockets, a display controller uses public IOKit brightness control with read-back verification plus a degraded display-sleep fallback, and a serialized security coordinator drives an explicit state machine and deterministic power/recovery lifecycle.

**Tech Stack:** Swift 5.9+, SwiftUI, AppKit, CoreGraphics, IOKit, ServiceManagement, Network (integration tests only), Swift Package Manager, GitHub Actions on `macos-15-intel`.

**Spec:** `docs/architecture.md`

## Global Constraints

- Deployment target: macOS 13.0 or later.
- Required release architecture: x86_64; arm64 may also compile but is not allowed to replace Intel verification.
- No Electron, Node.js, Python runtime, Java, kernel extension, privileged daemon, root requirement, Full Disk Access, Accessibility permission, or Screen Recording permission.
- No analytics, telemetry, external API calls, cloud backend, or long-term peer history.
- Never report `Protected` when any online display is unsupported or when protection verification fails.
- Never restore an arbitrary brightness; restore the exact captured value when available.
- `LISTEN` is never an active VNC session; only `ESTABLISHED` counts as connected.
- Multiple simultaneous sessions keep protection active until the count reaches zero.
- No production code is added for a behavior until a failing test for that behavior has been observed.

---

## File map

```text
Package.swift                                      SwiftPM products/targets and framework links
VNCPrivacyGuard/Core/Models.swift                 shared value types and protection coverage
VNCPrivacyGuard/Core/TailscaleClassifier.swift    100.64.0.0/10 classification
VNCPrivacyGuard/VNCMonitoring/SocketSnapshotParser.swift
VNCPrivacyGuard/VNCMonitoring/VNCSessionMonitor.swift
VNCPrivacyGuard/VNCMonitoring/NativeTCPConnectionProvider.swift
VNCPrivacyGuard/VNCMonitoring/NetstatTCPConnectionProvider.swift
VNCPrivacyGuard/CTCPSocketSnapshot/include/CTCPSocketSnapshot.h
VNCPrivacyGuard/CTCPSocketSnapshot/CTCPSocketSnapshot.c
VNCPrivacyGuard/SecurityState/SecurityStateMachine.swift
VNCPrivacyGuard/SecurityState/SecurityCoordinator.swift
VNCPrivacyGuard/DisplayPrivacy/DisplayPrivacyController.swift
VNCPrivacyGuard/DisplayPrivacy/MacDisplayHardware.swift
VNCPrivacyGuard/DisplayPrivacy/DisplaySleepFallback.swift
VNCPrivacyGuard/DisplayPrivacy/RecoveryStore.swift
VNCPrivacyGuard/Power/SleepAssertionManager.swift
VNCPrivacyGuard/Utilities/DiagnosticsStore.swift
VNCPrivacyGuard/Utilities/TerminationManager.swift
VNCPrivacyGuard/App/VNCPrivacyGuardApp.swift
VNCPrivacyGuard/UI/MenuContentView.swift
VNCPrivacyGuard/UI/SessionDetailsView.swift
VNCPrivacyGuard/UI/DiagnosticsView.swift
VNCPrivacyGuard/App/Resources/Info.plist
VNCPrivacyGuardTests/*.swift                       unit and macOS-only integration tests
scripts/build-app.sh                               assemble unsigned .app
scripts/verify.sh                                  build/test/lipo/static checks
.github/workflows/ci.yml                           Intel macOS CI
README.md
docs/THREAT_MODEL.md
```

---

### Task 1: Package scaffold, shared models, and IP classification

**Files:**
- Create: `Package.swift`
- Create: `VNCPrivacyGuard/Core/Models.swift`
- Create: `VNCPrivacyGuard/Core/TailscaleClassifier.swift`
- Create: `VNCPrivacyGuardTests/CoreModelTests.swift`
- Create: `VNCPrivacyGuardTests/TailscaleClassifierTests.swift`

**Interfaces:**
- Produces `TCPState`, `TCPConnectionRecord`, `VNCConnection`, `DisplayDescriptor`, `DisplayProtectionMethod`, `DisplayProtectionResult`, `ProtectionCoverage`, `SecurityPhase`.
- Produces `TailscaleClassifier.isLikelyTailscaleIPv4(_:) -> Bool`.

- [ ] **Step 1: Write failing tests for value semantics and Tailscale range boundaries.**

```swift
@Test func tailscaleRangeBoundaries() {
    #expect(TailscaleClassifier.isLikelyTailscaleIPv4("100.64.0.0"))
    #expect(TailscaleClassifier.isLikelyTailscaleIPv4("100.127.255.255"))
    #expect(!TailscaleClassifier.isLikelyTailscaleIPv4("100.63.255.255"))
    #expect(!TailscaleClassifier.isLikelyTailscaleIPv4("100.128.0.0"))
}
```

- [ ] **Step 2: Run `swift test --filter TailscaleClassifierTests` and confirm RED because the classifier/types do not exist.**
- [ ] **Step 3: Implement the minimum shared types and IPv4 `/10` classifier without Foundation networking side effects.**
- [ ] **Step 4: Run the focused tests, then `swift test`, and confirm GREEN.**
- [ ] **Step 5: Commit `test: add core VNC privacy models` plus minimal passing implementation.**

---

### Task 2: Socket parsing and established-session monitoring

**Files:**
- Create: `VNCPrivacyGuard/VNCMonitoring/SocketSnapshotParser.swift`
- Create: `VNCPrivacyGuard/VNCMonitoring/VNCSessionMonitor.swift`
- Create: `VNCPrivacyGuardTests/SocketSnapshotParserTests.swift`
- Create: `VNCPrivacyGuardTests/VNCSessionMonitorTests.swift`

**Interfaces:**

```swift
protocol TCPConnectionProviding: Sendable {
    func snapshot() async throws -> [TCPConnectionRecord]
}

protocol SessionMonitoring: Sendable {
    func start(handler: @escaping @Sendable ([VNCConnection]) async -> Void) async
    func stop() async
}
```

- [ ] **Step 1: Write parser tests proving `LISTEN` and `SYN_RECEIVED` do not become active sessions and `ESTABLISHED` does.**
- [ ] **Step 2: Run focused parser tests and confirm RED.**
- [ ] **Step 3: Implement a strict parser for normalized socket rows (`state|localIP|localPort|remoteIP|remotePort`).**
- [ ] **Step 4: Run parser tests and confirm GREEN.**
- [ ] **Step 5: Write monitor tests for one client, two clients, first disconnect, final disconnect, and rapid connect/disconnect using a deterministic fake provider.**
- [ ] **Step 6: Run monitor tests and confirm RED.**
- [ ] **Step 7: Implement the actor-based monitor with one-second async polling, connection-key first-seen tracking, and change-only emission.**
- [ ] **Step 8: Run all monitor tests and confirm GREEN.**
- [ ] **Step 9: Commit `test: add VNC session state tests` and `feat: add VNC session monitor` as logical increments.**

---

### Task 3: Native Darwin TCP provider and safe fallback

**Files:**
- Create: `VNCPrivacyGuard/CTCPSocketSnapshot/include/CTCPSocketSnapshot.h`
- Create: `VNCPrivacyGuard/CTCPSocketSnapshot/CTCPSocketSnapshot.c`
- Create: `VNCPrivacyGuard/VNCMonitoring/NativeTCPConnectionProvider.swift`
- Create: `VNCPrivacyGuard/VNCMonitoring/NetstatTCPConnectionProvider.swift`
- Create: `VNCPrivacyGuardTests/NetstatParserTests.swift`
- Create: `VNCPrivacyGuardTests/NativeSocketIntegrationTests.swift`

**Interfaces:**

```c
int vpg_copy_tcp_snapshot(uint16_t local_port, char **utf8_lines, size_t *length);
void vpg_free_tcp_snapshot(char *buffer);
```

- [ ] **Step 1: Write fallback parser tests using representative macOS `netstat -anv -p tcp` rows for LISTEN and ESTABLISHED IPv4/IPv6 connections.**
- [ ] **Step 2: Run tests and confirm RED.**
- [ ] **Step 3: Implement fallback parsing and a direct `/usr/sbin/netstat` `Process` call with fixed arguments, no shell.**
- [ ] **Step 4: Run fallback tests and confirm GREEN.**
- [ ] **Step 5: Add the macOS-only integration test that creates a temporary TCP listener/client pair, asks the native provider for that local port, and expects an ESTABLISHED record.**
- [ ] **Step 6: On Linux, confirm the integration test is skipped/guarded; on macOS CI, confirm it initially fails before the C provider exists.**
- [ ] **Step 7: Implement the bounds-checked `net.inet.tcp.pcblist_n` parser based on Darwin exported structures. Reject malformed record lengths/kinds rather than reading past the sysctl buffer.**
- [ ] **Step 8: Wrap the C output in `NativeTCPConnectionProvider`; on native-provider failure, surface an error so the composition root can switch to the fallback provider and expose that fact in diagnostics.**
- [ ] **Step 9: Run all tests and commit `feat: add native VNC TCP session detection`.**

---

### Task 4: Security state machine and serialized coordinator

**Files:**
- Create: `VNCPrivacyGuard/SecurityState/SecurityStateMachine.swift`
- Create: `VNCPrivacyGuard/SecurityState/SecurityCoordinator.swift`
- Create: `VNCPrivacyGuardTests/SecurityStateMachineTests.swift`
- Create: `VNCPrivacyGuardTests/SecurityCoordinatorTests.swift`

**Interfaces:**

```swift
enum SecurityEvent: Sendable, Equatable {
    case sessionsChanged(Int)
    case activationSucceeded(ProtectionCoverage)
    case activationFailed(String)
    case restoreSucceeded
    case restoreFailed(String)
    case driftDetected
}

enum SecurityAction: Sendable, Equatable {
    case acquireSleepAssertion
    case activatePrivacy
    case maintainPrivacy
    case deactivatePrivacy
    case releaseSleepAssertion
}
```

- [ ] **Step 1: Write reducer tests for IDLE -> VNC_DETECTED -> SECURING -> SECURED -> RESTORING -> IDLE and all degraded/error branches.**
- [ ] **Step 2: Run focused tests and confirm RED.**
- [ ] **Step 3: Implement the pure reducer with no system calls.**
- [ ] **Step 4: Run reducer tests and confirm GREEN.**
- [ ] **Step 5: Write coordinator tests that reproduce stale activation completion after a rapid disconnect and two-client behavior.**
- [ ] **Step 6: Run coordinator tests and confirm RED.**
- [ ] **Step 7: Implement a serial actor with a generation counter and protocol-injected display/power/recovery dependencies.**
- [ ] **Step 8: Run all coordinator tests and confirm GREEN.**
- [ ] **Step 9: Commit `feat: add security state machine`.**

---

### Task 5: Brightness snapshot/restore, recovery persistence, and degraded display sleep

**Files:**
- Create: `VNCPrivacyGuard/DisplayPrivacy/DisplayPrivacyController.swift`
- Create: `VNCPrivacyGuard/DisplayPrivacy/MacDisplayHardware.swift`
- Create: `VNCPrivacyGuard/DisplayPrivacy/DisplaySleepFallback.swift`
- Create: `VNCPrivacyGuard/DisplayPrivacy/RecoveryStore.swift`
- Create: `VNCPrivacyGuardTests/DisplayPrivacyControllerTests.swift`
- Create: `VNCPrivacyGuardTests/RecoveryStoreTests.swift`

**Interfaces:**

```swift
protocol DisplayHardwareControlling: Sendable {
    func displays() throws -> [DisplayDescriptor]
    func readBrightness(displayID: UInt32) throws -> Float?
    func setBrightness(displayID: UInt32, value: Float) throws
    func isDisplayAsleep(displayID: UInt32) -> Bool
}

protocol DisplayControlling: Sendable {
    func activatePrivacy(reusing snapshot: RecoverySnapshot?) async -> ProtectionCoverage
    func maintainPrivacy() async -> ProtectionCoverage
    func deactivatePrivacy() async throws
}
```

- [ ] **Step 1: Write tests proving 0.37 restores to 0.37, zero is not overwritten as the recovery baseline on restart, unsupported external displays yield Partial/Warning, and display removal does not falsely claim full coverage.**
- [ ] **Step 2: Run tests and confirm RED.**
- [ ] **Step 3: Implement pure snapshot/coverage logic with injected fake hardware.**
- [ ] **Step 4: Run tests and confirm GREEN.**
- [ ] **Step 5: Write atomic JSON recovery-store tests in a temporary directory.**
- [ ] **Step 6: Run tests and confirm RED, then implement schema-versioned atomic persistence and confirm GREEN.**
- [ ] **Step 7: Implement macOS IOKit/CoreGraphics hardware adapter using public brightness get/set, `CGDisplayIOServicePort`, read-back verification, and no force unwraps.**
- [ ] **Step 8: Implement `/usr/bin/pmset displaysleepnow` fallback with fixed executable path and a minimum reassert interval.**
- [ ] **Step 9: Commit `feat: add display privacy controller` and `test: add recovery and display coverage tests`.**

---

### Task 6: Power assertion and termination fail-safe

**Files:**
- Create: `VNCPrivacyGuard/Power/SleepAssertionManager.swift`
- Create: `VNCPrivacyGuard/Utilities/TerminationManager.swift`
- Create: `VNCPrivacyGuardTests/SleepAssertionLifecycleTests.swift`

**Interfaces:**

```swift
protocol PowerAssertionManaging: Sendable {
    func acquire() async throws
    func release() async
}
```

- [ ] **Step 1: Write lifecycle tests proving acquire is idempotent, release is idempotent, and the final session releases exactly once.**
- [ ] **Step 2: Run tests and confirm RED.**
- [ ] **Step 3: Implement the abstract lifecycle, then the macOS `IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleSystemSleep, ...)` adapter and deterministic release.**
- [ ] **Step 4: Add AppKit termination plus SIGTERM/SIGINT routing to coordinator emergency restore; document SIGKILL as unrecoverable until relaunch.**
- [ ] **Step 5: Run tests and commit `feat: add power assertion and termination recovery`.**

---

### Task 7: Menu-bar app, Launch at Login, diagnostics, and emergency restore CLI mode

**Files:**
- Create: `VNCPrivacyGuard/App/VNCPrivacyGuardApp.swift`
- Create: `VNCPrivacyGuard/UI/MenuContentView.swift`
- Create: `VNCPrivacyGuard/UI/SessionDetailsView.swift`
- Create: `VNCPrivacyGuard/UI/DiagnosticsView.swift`
- Create: `VNCPrivacyGuard/Utilities/DiagnosticsStore.swift`
- Create: `VNCPrivacyGuard/App/Resources/Info.plist`

**Interfaces:**
- `SMAppService.mainApp` controls Launch at Login.
- `VNCPrivacyGuard --restore` restores persisted display state and exits without starting the menu UI.

- [ ] **Step 1: Write bounded diagnostics-store tests (oldest event evicted after capacity) and status-copy tests mapping coverage to `Idle`, `Protected`, `Partial Protection`, `Protection Unverified`, or `Protection Failed`.**
- [ ] **Step 2: Run tests and confirm RED; implement the view model/status mapping and confirm GREEN.**
- [ ] **Step 3: Implement `MenuBarExtra` UI with Protection Enabled, Launch at Login, Blank Now, Restore Display, Session Details, Diagnostics, About, and Quit.**
- [ ] **Step 4: Implement `SMAppService.mainApp` registration status/error handling.**
- [ ] **Step 5: Implement `--restore`; emergency restore disables automatic protection for the current run rather than immediately reblanking.**
- [ ] **Step 6: Commit `feat: add menu bar application`.**

---

### Task 8: Packaging, CI, documentation, and manual test plan

**Files:**
- Create: `scripts/build-app.sh`
- Create: `scripts/verify.sh`
- Create: `.github/workflows/ci.yml`
- Create: `README.md`
- Create: `docs/THREAT_MODEL.md`
- Create: `LICENSE`

- [ ] **Step 1: Add `build-app.sh` that runs a release Swift build and assembles `dist/VNC Privacy Guard.app/Contents/{MacOS,Resources}` with Info.plist; no signing identity is hard-coded.**
- [ ] **Step 2: Add `verify.sh` that runs tests, release build, bundle build, `file`, and `lipo -info` and fails unless x86_64 is present on macOS.**
- [ ] **Step 3: Add GitHub Actions on `macos-15-intel` for tests/build/architecture verification and upload an unsigned zipped app artifact.**
- [ ] **Step 4: Write README sections requested by the specification, including Tailscale's role, permissions, protection modes, multiple-monitor limitations, Emergency Recovery, signing/notarization, troubleshooting, uninstall, and the full 23-step manual Intel test checklist.**
- [ ] **Step 5: Write `docs/THREAT_MODEL.md` with required protect-against/out-of-scope/assumption sections.**
- [ ] **Step 6: Commit `ci: add macOS Intel build and test workflow` and `docs: add security and recovery documentation`.**

---

### Task 9: Independent security review and final verification

**Files:**
- Modify only files implicated by findings.

- [ ] **Step 1: Review every process launch for shell/argument injection; expect only fixed absolute `netstat` and `pmset` paths.**
- [ ] **Step 2: Review persistence for path traversal, sensitive fields, non-atomic writes, and stale-state corruption.**
- [ ] **Step 3: Review actor/state transitions for stale Protected state, two-client restore bugs, hot-plug races, and power assertion leaks.**
- [ ] **Step 4: For every High/Critical finding, add a failing regression test before changing production code, then run it RED -> GREEN.**
- [ ] **Step 5: Run `swift test` and a clean release build on macOS Intel CI.**
- [ ] **Step 6: Run `lipo -info` on the packaged executable and record x86_64 evidence.**
- [ ] **Step 7: Inspect `git status`, changed-file list, and final diff.**
- [ ] **Step 8: Push the feature branch and create a PR into `main` with Summary, Architecture, Security model, VNC detection, physical blanking, fallback, permissions, Intel compatibility, tests, manual test plan, and known limitations. Do not merge.**
