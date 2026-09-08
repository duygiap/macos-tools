import XCTest
@testable import VNCPrivacyCore

final class NetstatParserTests: XCTestCase {
    func testParsesEstablishedIPv4Row() throws {
        let line = "tcp4       0      0  192.168.1.10.5900      100.64.1.5.51234       ESTABLISHED 131072 131768  1234      0 0x0102 0x00000000"
        let record = try XCTUnwrap(NetstatTCPParser.parseLine(line))
        XCTAssertEqual(record.state, .established); XCTAssertEqual(record.localAddress, "192.168.1.10"); XCTAssertEqual(record.localPort, 5900); XCTAssertEqual(record.remoteAddress, "100.64.1.5"); XCTAssertEqual(record.remotePort, 51234)
    }
    func testParsesListenAndDoesNotInventRemotePort() throws {
        let record = try XCTUnwrap(NetstatTCPParser.parseLine("tcp4       0      0  *.5900                 *.*                    LISTEN      131072 131072   999      0 0x0000 0x00000000"))
        XCTAssertEqual(record.state, .listen); XCTAssertEqual(record.remotePort, 0)
    }
    func testParsesIPv6EndpointUsingLastDotAsPortSeparator() throws {
        let record = try XCTUnwrap(NetstatTCPParser.parseLine("tcp6       0      0  fe80::1%lo0.5900        fe80::2%lo0.61234       ESTABLISHED 131072 131768  1234      0 0x0102 0x00000000"))
        XCTAssertEqual(record.localAddress, "fe80::1%lo0"); XCTAssertEqual(record.remotePort, 61234)
    }
    func testRejectsNonTCPAndMalformedRows() { XCTAssertNil(NetstatTCPParser.parseLine("udp4 0 0 *.5353 *.*")); XCTAssertNil(NetstatTCPParser.parseLine("tcp4 too-short")) }
}
