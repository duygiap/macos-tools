import Foundation
import IntelBrightnessBridge

#if os(macOS)
import CoreGraphics

public struct IntelIOKitBrightnessController: DisplayBrightnessControlling {
    public init() {}

    public func displays() throws -> [DisplayDescriptor] {
        var count: UInt32 = 0
        let countResult = CGGetOnlineDisplayList(0, nil, &count)
        guard countResult == .success else {
            throw DisplayBrightnessError.enumerationFailed("CGGetOnlineDisplayList count failed: \(countResult.rawValue)")
        }
        guard count > 0 else { return [] }

        var ids = [CGDirectDisplayID](repeating: 0, count: Int(count))
        var actualCount: UInt32 = 0
        let listResult = CGGetOnlineDisplayList(count, &ids, &actualCount)
        guard listResult == .success else {
            throw DisplayBrightnessError.enumerationFailed("CGGetOnlineDisplayList failed: \(listResult.rawValue)")
        }

        return ids.prefix(Int(actualCount)).map { id in
            DisplayDescriptor(
                id: UInt32(id),
                isBuiltIn: CGDisplayIsBuiltin(id) != 0,
                isOnline: CGDisplayIsOnline(id) != 0
            )
        }
    }

    public func currentBrightness(displayID: UInt32) throws -> Float? {
        var brightness: Float = 0
        let result = vpg_iokit_get_brightness(displayID, &brightness)
        guard result == 0 else {
            return nil
        }
        guard brightness.isFinite, brightness >= 0, brightness <= 1 else {
            throw DisplayBrightnessError.readFailed(displayID, "IOKit returned brightness outside 0...1")
        }
        return brightness
    }

    public func setBrightness(displayID: UInt32, value: Float) throws {
        guard value.isFinite, value >= 0, value <= 1 else {
            throw DisplayBrightnessError.invalidBrightness(value)
        }
        let result = vpg_iokit_set_brightness(displayID, value)
        guard result == 0 else {
            throw DisplayBrightnessError.writeFailed(displayID, "IODisplaySetFloatParameter returned \(result)")
        }
    }
}
#else
public struct IntelIOKitBrightnessController: DisplayBrightnessControlling {
    public init() {}
    public func displays() throws -> [DisplayDescriptor] { throw DisplayBrightnessError.unavailablePlatform }
    public func currentBrightness(displayID: UInt32) throws -> Float? { throw DisplayBrightnessError.unavailablePlatform }
    public func setBrightness(displayID: UInt32, value: Float) throws { throw DisplayBrightnessError.unavailablePlatform }
}
#endif
