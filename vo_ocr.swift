// vo_ocr.swift - OCR y deteccion de recuadro de foco para iOS Simulator / VoiceOver usando Vision.framework.
// Uso: vo_ocr <imagen.png>
import Vision
import AppKit
import CoreGraphics

guard CommandLine.arguments.count > 1,
      let img = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let srcCG = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("usage: vo_ocr <image>\n", stderr)
    exit(1)
}

let width = srcCG.width
let height = srcCG.height
let bytesPerPixel = 4
let bytesPerRow = width * bytesPerPixel
var rawData = [UInt8](repeating: 0, count: height * bytesPerRow)

let colorSpace = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(
    data: &rawData,
    width: width,
    height: height,
    bitsPerComponent: 8,
    bytesPerRow: bytesPerRow,
    space: colorSpace,
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
) else {
    exit(2)
}

ctx.draw(srcCG, in: CGRect(x: 0, y: 0, width: width, height: height))

// Detectar el recuadro de foco verde de Xcode Accessibility Inspector / VoiceOver
var rowCounts = [Int: Int]()
var colCounts = [Int: Int]()
var greenPts = [(Int, Int)]()
for y in stride(from: 0, to: height, by: 2) {
    let row = y * bytesPerRow
    for x in stride(from: 0, to: width, by: 2) {
        let i = row + x * 4
        let r = Int(rawData[i])
        let g = Int(rawData[i + 1])
        let b = Int(rawData[i + 2])
        if g >= 145 && r >= 110 && b >= 115 && (g - r) >= 20 && (g - b) >= 12 && abs(r - b) <= 22 {
            rowCounts[y, default: 0] += 1
            colCounts[x, default: 0] += 1
            greenPts.append((x, y))
        }
    }
}
let validRows = Set(rowCounts.filter { $0.value >= 12 }.keys)
let validCols = Set(colCounts.filter { $0.value >= 10 }.keys)
let filtered = greenPts.filter { validRows.contains($0.1) || validCols.contains($0.0) }
if filtered.count >= 16 {
    let xs = filtered.map { $0.0 }
    let ys = filtered.map { $0.1 }
    if let x1 = xs.min(), let x2 = xs.max(), let y1 = ys.min(), let y2 = ys.max() {
        print(String(format: "BOX\t%d,%d,%d,%d", x1, y1, x2, y2))
    }
}

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.recognitionLanguages = ["es-ES", "es-MX", "en-US"]
req.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: srcCG)
do {
    try handler.perform([req])
} catch {
    fputs("OCR error: \(error)\n", stderr)
    exit(2)
}

for obs in req.results ?? [] {
    if let s = obs.topCandidates(1).first {
        let b = obs.boundingBox
        print(String(format: "%.4f,%.4f,%.4f,%.4f\t%@",
                     b.origin.x, 1.0 - b.origin.y - b.size.height,
                     b.size.width, b.size.height, s.string))
    }
}
