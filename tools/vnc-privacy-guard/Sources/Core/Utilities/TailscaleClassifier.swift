import Foundation

public enum TailscaleClassifier {
    public static func isLikelyTailscaleIPv4(_ address: String) -> Bool {
        let pieces = address.split(separator: ".", omittingEmptySubsequences: false)
        guard pieces.count == 4,
              let a = UInt8(pieces[0]),
              let b = UInt8(pieces[1]),
              UInt8(pieces[2]) != nil,
              UInt8(pieces[3]) != nil else { return false }
        return a == 100 && (64...127).contains(b)
    }
}
