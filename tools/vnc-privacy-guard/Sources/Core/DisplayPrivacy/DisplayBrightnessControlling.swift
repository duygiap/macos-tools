import Foundation

public protocol DisplayBrightnessControlling: Sendable {
    func displays() throws -> [DisplayDescriptor]
    func currentBrightness(displayID: UInt32) throws -> Float?
    func setBrightness(displayID: UInt32, value: Float) throws
}

public enum DisplayBrightnessError: Error, Equatable, Sendable {
    case unsupportedDisplay(UInt32)
    case invalidBrightness(Float)
    case enumerationFailed(String)
    case readFailed(UInt32, String)
    case writeFailed(UInt32, String)
    case unavailablePlatform
}
