# VNC Privacy Guard Architecture

## Status

This document defines the initial architecture for **VNC Privacy Guard**, a native macOS menu-bar application whose primary target is **Intel x86_64**.

The repository was empty at the start of this work: no commits, files, issues, pull requests, or GitHub Actions existed. The implementation therefore starts from a clean architecture rather than modifying an existing application.

## Security goal

When a real VNC/macOS Screen Sharing TCP session is established to the Mac, VNC Privacy Guard should make the physical displays unreadable while keeping WindowServer, the VNC framebuffer, keyboard/mouse input, SSH, Tailscale, and networking operational. The system must not idle-sleep while a protected VNC session is active. When the last session ends, the previous display state must be restored.

Security priority is:

1. physical display/backlight control;
2. display-sleep fallback with active watchdog;
3. explicit degraded/unsupported reporting.

A fullscreen black overlay is not a protection mechanism because it would affect the same composited framebuffer VNC is expected to view.

## Feasibility findings

### Physical-display blanking while preserving the VNC framebuffer

Public macOS APIs provide `IODisplayGetFloatParameter` and `IODisplaySetFloatParameter` for display parameters including brightness. On Intel Macs this is the least-invasive public mechanism to drive supported display brightness to zero while leaving the WindowServer framebuffer active.

The practical caveat is that mapping a `CGDirectDisplayID` to the IOKit display service normally uses `CGDisplayIOServicePort`. Apple still ships this public function, but it is deprecated and explicitly has no replacement. There is also no public API that provides an optical sensor-level proof that a panel emits no visible light. Software can verify only that the hardware/display service accepted the target value and that reading the parameter back reports the expected value.

Consequences:

- Tier 1 uses public IOKit brightness control and read-back verification.
- No private `DisplayServices` or `CoreDisplay` SPI is used in the initial implementation.
- An IOKit success code alone is not enough; read-back must confirm the target.
- Unsupported or unverifiable displays are never counted as fully protected.
- Actual optical behavior and VNC-framebuffer continuity remain part of the required manual Intel test plan.

`kIODisplayPowerStateKey` and direct display power-state manipulation were considered but rejected for the initial implementation because their user-space behavior is not a reliable documented contract for preserving Screen Sharing rendering.

### VNC session detection

Three strategies were evaluated.

#### A. Public/native connection-state API

There is no general public Network/CoreGraphics API that enumerates arbitrary established TCP sockets owned by other services. `NWPathMonitor` monitors path viability rather than the system TCP connection table. A Network Extension or Endpoint Security based design would add entitlements and operational complexity that are disproportionate to this single-purpose app.

**Result:** not suitable for the MVP.

#### B. Socket-table inspection

Darwin exposes the TCP PCB list through `sysctlbyname("net.inet.tcp.pcblist_n", ...)`, and Apple's own `netstat` implementation reads the same source. It provides local address/port, peer address/port, and TCP state, allowing a strict distinction between `LISTEN`, `SYN_RECEIVED`, and `ESTABLISHED` without depending on process names.

The drawback is that the PCB selector and associated exported kernel structures are not a stable high-level public ABI. Therefore this code must be isolated, bounds-checked, version-tolerant where possible, and covered by a real-socket integration test on macOS CI.

**Result:** chosen primary strategy because it has low overhead and does not need root/FDA.

#### C. `screensharingd` / Screen Sharing service state

Process or launchd state can show that Screen Sharing is enabled or the daemon is running, but does not reliably mean a client is connected. Basing protection only on process state would generate false positives and cannot robustly count simultaneous clients.

**Result:** diagnostics only; not an authoritative session signal.

### Detection fallback

If the native PCB parser rejects the runtime layout or `sysctl` fails, the app falls back to launching `/usr/sbin/netstat` directly with fixed arguments and parsing its output. It does not invoke a shell, does not interpolate user input, and does not poll faster than the normal one-second monitor cadence. The fallback is reported in diagnostics because it is more expensive.

## Supported platform

- Deployment target: macOS 13 or later.
- Required architecture: x86_64.
- The source is structured so arm64 can also build when the same system APIs are available, but Intel remains the release/CI requirement.
- No kernel extension, privileged daemon, root helper, Full Disk Access, Accessibility permission, Screen Recording permission, or SIP/Gatekeeper change is required by the intended design.

macOS 13 is selected because `SMAppService` is available for Launch at Login and `MenuBarExtra` is available for a compact native menu-bar UI.

## Repository structure

```text
macos-tools/
  README.md
  LICENSE
  Package.swift
  VNCPrivacyGuard/
    App/
    Core/
    VNCMonitoring/
    DisplayPrivacy/
    Power/
    SecurityState/
    UI/
    Utilities/
    CTCPSocketSnapshot/
  VNCPrivacyGuardTests/
  scripts/
  docs/
    architecture.md
    THREAT_MODEL.md
  .github/workflows/
```

Swift Package Manager is used for dependency-free builds and tests. The final application is still a native Swift/SwiftUI/AppKit executable. A small packaging script assembles the release binary and Info.plist into a `.app` bundle without requiring a development certificate. No third-party runtime or package dependency is required.

## Component model

### VNCSessionMonitor

Responsibilities:

- poll a `TCPConnectionProviding` implementation at a one-second interval;
- identify connections whose local port is configured for Screen Sharing (5900 by default);
- expose `connecting` for TCP handshake states when present;
- count only `ESTABLISHED` sockets as active VNC sessions;
- maintain monotonic first-seen times per connection tuple for connection duration;
- emit state only when the effective connection set changes;
- support multiple simultaneous clients;
- classify `100.64.0.0/10` peers as likely Tailscale peers for UI only.

It never assumes that a listening port means a session is active.

### NativeTCPConnectionProvider

A small C shim reads `net.inet.tcp.pcblist_n` and exports sanitized records to Swift. The parser validates record lengths, kinds, bounds, address family, ports, and TCP state before accepting a record. The implementation is isolated so it can be replaced if a future macOS release changes the PCB ABI.

### NetstatTCPConnectionProvider

Fallback provider. It launches `/usr/sbin/netstat` directly using `Process`, captures stdout with a fixed argument list, and parses only TCP socket rows. No shell is involved.

### DisplayPrivacyController

Public interface conceptually exposes:

```swift
activatePrivacy()
maintainPrivacy()
deactivatePrivacy()
currentState
```

On activation it:

1. enumerates online displays with CoreGraphics;
2. records a minimal recovery snapshot before any mutation;
3. reads the current brightness for each controllable display;
4. writes brightness `0.0`;
5. reads brightness back and marks that display protected only if the read-back is at or below the verification threshold;
6. records unsupported displays separately;
7. invokes the configured display-sleep fallback if required.

On maintenance it:

- reacts immediately to display reconfiguration and workspace wake notifications;
- performs a protected-state watchdog check approximately every 500 ms;
- reasserts zero brightness when drift is detected;
- rate-limits display-sleep reassertion to avoid repeatedly invoking system APIs.

On deactivation it restores the exact brightness snapshot for still-present displays. It never restores to an arbitrary 100% value.

### Protection coverage

Each display reports one of:

- `hardwareBrightnessVerified`;
- `displaySleepFallback`;
- `unsupported`;
- `offline`.

Overall UI state is derived from every online display:

- **Protected**: every online display is verified through hardware brightness control.
- **Partial Protection**: at least one display is protected but another is unsupported.
- **Protection Unverified / Warning**: only fallback sleep protects one or more displays, verification failed, or a system API error prevents trustworthy status.
- **Protection Failed**: VNC is active and no display-protection mechanism succeeded.

A successful API call without successful read-back is never reported as Protected.

### DisplaySleepFallback

When hardware brightness control is not available and fallback is enabled, the app launches `/usr/bin/pmset displaysleepnow` directly without a shell. `CGDisplayIsAsleep` and subsequent wake observations are used to decide whether reassertion is needed.

This is explicitly degraded protection because remote input can wake displays. The watchdog reissues the request after a bounded minimum interval, but a short exposure window can still exist. The UI and README must state this limitation.

### SleepAssertionManager

During an established VNC session the app creates one `IOPMAssertion` using `kIOPMAssertionTypePreventUserIdleSystemSleep`. This prevents idle system sleep while still permitting the app to blank or sleep displays. The assertion is released deterministically when the final VNC session ends, when protection is disabled, and during normal app termination.

No `caffeinate` child process is used.

### SecurityStateMachine

Security behavior is driven by an explicit reducer/state machine rather than unrelated booleans.

Primary phases:

```text
IDLE
  -> VNC_DETECTED
  -> SECURING_DISPLAY
  -> SECURED
  -> RESTORING
  -> IDLE
```

Any activation, verification, or restore failure can enter `ERROR_DEGRADED` with the failure reason and current coverage.

Events include:

- connection set changed;
- protection activated;
- protection activation failed;
- protection drift detected;
- display configuration changed;
- machine woke;
- restore completed;
- restore failed;
- protection enabled/disabled;
- manual blank/restore.

The coordinator serializes all state-changing operations so a connect/disconnect race cannot cause an old activation result to overwrite a newer restore decision.

### SecurityCoordinator

An actor owns the state machine and side-effecting protocols:

- `SessionMonitoring`;
- `DisplayControlling`;
- `PowerAssertionManaging`;
- `RecoveryStatePersisting`.

The actor tracks a monotonically increasing generation for session changes. After any awaited system operation it checks that the generation is still current before publishing a secured state. If the last VNC connection disappeared during activation, the coordinator restores immediately instead of publishing a stale Protected state.

## Recovery and fail-safe behavior

### Persisted state

Only the minimal display recovery snapshot is persisted in Application Support:

- schema version;
- display identifier;
- pre-protection brightness when readable;
- activation timestamp.

No credentials, Tailscale keys, screen content, connection history, or long-term peer history is stored.

Writes are atomic (`Data.write(..., .atomic)`). The recovery file is removed only after a successful restore.

### Startup reconciliation

At startup the app:

1. enumerates current displays;
2. reads any persisted recovery snapshot;
3. checks current VNC sessions;
4. if no VNC session is active, restores the persisted pre-protection state and clears the recovery file;
5. if VNC remains active, reuses the recovery snapshot and reapplies protection rather than overwriting the original brightness with zero.

### Normal termination

AppKit termination callbacks release the power assertion and attempt display restoration synchronously before termination completes.

### SIGTERM / SIGINT

Dispatch signal sources route controlled termination through the same emergency restore path before exiting.

### Crash / SIGKILL limitation

No user-space application can guarantee cleanup after `SIGKILL`, a process crash that prevents cleanup code, power loss, or a kernel panic. The persisted snapshot ensures the next launch can reconcile and restore. The application binary also supports a documented `--restore` command so the same signed executable can perform emergency restoration without installing a privileged helper.

## Manual controls

Menu-bar controls:

- Protection Enabled;
- Launch at Login;
- Blank Now;
- Restore Display;
- VNC Session Details;
- Diagnostics;
- About;
- Quit.

`Restore Display` is an emergency action. It restores the snapshot and disables automatic protection so the watchdog does not immediately black the screen again while a VNC session remains active. The user must explicitly re-enable protection afterward.

## Launch at Login

`SMAppService.mainApp` is used when running as a packaged application. The app presents the actual registration status and fails gracefully when registration cannot be changed. It never creates a LaunchAgent manually and does not install a privileged helper.

## Multiple displays

Every online display receives an independent capability/result record. CoreGraphics supplies display ID, built-in status, active/online status, and configuration-change callbacks.

The MVP does not implement DDC/CI. External monitors that do not expose brightness through macOS IOKit are marked unsupported. If any online external display is unsupported, the overall state cannot be fully Protected; it is Partial Protection or Warning depending on fallback behavior.

The abstraction intentionally leaves room for a future DDC/CI implementation without changing the state machine.

## Tailscale awareness

The app does not call the Tailscale CLI, daemon API, or control plane. Session details may label a peer as `Likely Tailscale peer` when its IPv4 address belongs to `100.64.0.0/10`. This is informational only.

## Privacy and logging

- no analytics;
- no telemetry;
- no external HTTP/API calls;
- no peer-IP upload;
- no VNC history database;
- no credential logging.

System diagnostics use `Logger`/unified logging with separate categories. The menu diagnostics model keeps only a bounded in-memory ring of recent non-sensitive events. Unified logging retention is managed by macOS; the app does not create an unbounded private log file.

Local diagnostics include:

- current security state;
- active VNC count;
- current peer tuples;
- display protection methods;
- selected TCP provider;
- protection activation latency;
- re-blank count;
- recent non-sensitive errors.

## Permission model

Expected permissions: none beyond ordinary user execution.

Not required:

- root;
- Full Disk Access;
- Accessibility;
- Screen Recording;
- Network Extension entitlement;
- Endpoint Security entitlement;
- kernel/system extension;
- changes to SIP, Gatekeeper, firewall, SSH, Screen Sharing, or Tailscale.

If a future API change causes a capability to require additional privilege, that capability must fail closed in status rather than silently escalating permissions.

## Resource model

- session polling: approximately 1 second;
- protected brightness watchdog: approximately 500 ms;
- display-sleep fallback: rate-limited, no more frequent than approximately 750 ms after a detected wake;
- no 100 ms busy loop;
- no continuous `lsof` process spawning;
- no background network traffic.

Polling tasks sleep asynchronously and stop when the owning monitor/coordinator stops.

## Testing strategy

System APIs are hidden behind protocols and pure reducers/parsers are tested without touching real displays.

Required unit coverage:

- LISTEN vs ESTABLISHED parsing;
- multiple simultaneous VNC sessions;
- connection-count transitions;
- rapid connect/disconnect;
- Tailscale-range classification;
- security state-machine transitions;
- stale activation generation handling;
- exact brightness snapshot/restore;
- display removal during protection;
- persisted recovery reconciliation;
- unsupported display coverage.

macOS-only integration coverage creates a temporary local TCP listener/client pair on an ephemeral port and verifies that the native PCB provider reports an ESTABLISHED connection. No VNC server is launched in CI.

Display manipulation is never executed in automated CI.

## CI and Intel verification

GitHub Actions runs on `macos-15-intel`, an x86_64 runner. CI performs:

1. `swift test`;
2. release build;
3. app bundle assembly;
4. `lipo -info` / `file` architecture verification;
5. archive of the unsigned app as a build artifact.

No signing certificate is hard-coded. Developer ID signing and notarization are documented release steps rather than prerequisites for local development.

## Manual security validation gate

Automated tests can prove socket-state logic, recovery logic, state transitions, and API-level brightness read-back. They cannot prove optical privacy or that a specific Intel GPU/display combination keeps the VNC framebuffer live while the panel is black.

Before claiming production-grade physical privacy on a Mac model, the manual Intel checklist must verify:

- physical display becomes unreadable;
- VNC continues rendering;
- remote mouse/keyboard does not make the display stay visible;
- repeated reconnects restore the original brightness;
- multiple sessions keep protection until the final disconnect;
- display hot-plug behavior matches the reported protection state.

Until that hardware test is performed, CI success means **software behavior verified**, not universal hardware privacy guaranteed.
