import XCTest
@testable import VNCPrivacyCore

final class TCPProviderTests: XCTestCase {
    func testFallbackProviderUsesPrimaryWhenPrimarySucceeds() async throws {
        let expected = [TCPConnectionRecord(state: .established, localAddress: "127.0.0.1", localPort: 5900, remoteAddress: "100.64.1.2", remotePort: 50000)]
        let primary = StubTCPProvider(result: .success(expected))
        let fallback = StubTCPProvider(result: .success([]))
        let provider = FallbackTCPConnectionProvider(primary: primary, fallback: fallback)

        let records = try await provider.snapshot()

        XCTAssertEqual(records, expected)
        let mode = await provider.currentMode
        XCTAssertEqual(mode, .nativeSysctl)
        let fallbackCalls = await fallback.callCount
        XCTAssertEqual(fallbackCalls, 0)
    }

    func testFallbackProviderUsesNetstatAfterPrimaryFailure() async throws {
        let expected = [TCPConnectionRecord(state: .listen, localAddress: "*", localPort: 5900, remoteAddress: "*", remotePort: 0)]
        let primary = StubTCPProvider(result: .failure(TCPConnectionProviderError.unavailable("sysctl unavailable")))
        let fallback = StubTCPProvider(result: .success(expected))
        let provider = FallbackTCPConnectionProvider(primary: primary, fallback: fallback)

        let records = try await provider.snapshot()

        XCTAssertEqual(records, expected)
        let mode = await provider.currentMode
        XCTAssertEqual(mode, .netstatFallback)
        let fallbackCalls = await fallback.callCount
        XCTAssertEqual(fallbackCalls, 1)
    }

    func testNativeStateMappingRejectsUnknownValues() {
        XCTAssertEqual(NativeTCPStateMapper.map(0), .closed)
        XCTAssertEqual(NativeTCPStateMapper.map(1), .listen)
        XCTAssertEqual(NativeTCPStateMapper.map(2), .synSent)
        XCTAssertEqual(NativeTCPStateMapper.map(3), .synReceived)
        XCTAssertEqual(NativeTCPStateMapper.map(4), .established)
        XCTAssertEqual(NativeTCPStateMapper.map(5), .closeWait)
        XCTAssertEqual(NativeTCPStateMapper.map(6), .finWait1)
        XCTAssertEqual(NativeTCPStateMapper.map(7), .closing)
        XCTAssertEqual(NativeTCPStateMapper.map(8), .lastAck)
        XCTAssertEqual(NativeTCPStateMapper.map(9), .finWait2)
        XCTAssertEqual(NativeTCPStateMapper.map(10), .timeWait)
        XCTAssertEqual(NativeTCPStateMapper.map(999), .unknown)
    }
}

private actor StubTCPProvider: TCPConnectionProviding {
    private let result: Result<[TCPConnectionRecord], Error>
    private(set) var callCount = 0

    init(result: Result<[TCPConnectionRecord], Error>) {
        self.result = result
    }

    func snapshot() async throws -> [TCPConnectionRecord] {
        callCount += 1
        return try result.get()
    }
}
