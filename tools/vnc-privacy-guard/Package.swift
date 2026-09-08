// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VNCPrivacyGuard",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "VNCPrivacyCore", targets: ["VNCPrivacyCore"]),
        .executable(name: "VNCPrivacyGuard", targets: ["VNCPrivacyGuardApp"]),
        .executable(name: "vncprivacy", targets: ["vncprivacy"]),
        .executable(name: "VNCPrivacyRecoveryAgent", targets: ["VNCPrivacyRecoveryAgent"]),
    ],
    targets: [
        .target(
            name: "CTCPSocketSnapshot",
            path: "Sources/CTCPSocketSnapshot",
            publicHeadersPath: "include"
        ),
        .target(
            name: "IntelBrightnessBridge",
            path: "Sources/IntelBrightnessBridge",
            publicHeadersPath: "include",
            linkerSettings: [
                .linkedFramework("CoreGraphics", .when(platforms: [.macOS])),
                .linkedFramework("IOKit", .when(platforms: [.macOS])),
            ]
        ),
        .target(
            name: "VNCPrivacyCore",
            dependencies: ["CTCPSocketSnapshot", "IntelBrightnessBridge"],
            path: "Sources/Core",
            linkerSettings: [
                .linkedFramework("CoreGraphics", .when(platforms: [.macOS])),
                .linkedFramework("IOKit", .when(platforms: [.macOS])),
            ]
        ),
        .executableTarget(
            name: "VNCPrivacyGuardApp",
            dependencies: ["VNCPrivacyCore"],
            path: "Sources/App",
            linkerSettings: [
                .linkedFramework("AppKit", .when(platforms: [.macOS])),
                .linkedFramework("ServiceManagement", .when(platforms: [.macOS])),
            ]
        ),
        .executableTarget(
            name: "vncprivacy",
            dependencies: ["VNCPrivacyCore"],
            path: "Sources/CLI"
        ),
        .executableTarget(
            name: "VNCPrivacyRecoveryAgent",
            dependencies: ["VNCPrivacyCore"],
            path: "Sources/RecoveryAgent"
        ),
        .testTarget(
            name: "VNCPrivacyCoreTests",
            dependencies: ["VNCPrivacyCore"],
            path: "Tests/VNCPrivacyCoreTests"
        ),
    ]
)
