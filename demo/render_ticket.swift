// Renders the demo boarding-pass image (demo/media/ticket.png) with AppKit. Used by demo/make_media.sh.
import AppKit

let size = NSSize(width: 900, height: 420)
let image = NSImage(size: size)
image.lockFocus()
NSColor.white.setFill()
NSRect(origin: .zero, size: size).fill()
func draw(_ text: String, _ x: CGFloat, _ y: CGFloat, _ pt: CGFloat, bold: Bool = false) {
    let font = bold ? NSFont.boldSystemFont(ofSize: pt) : NSFont.systemFont(ofSize: pt)
    (text as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: [.font: font, .foregroundColor: NSColor.black])
}
draw("BOARDING PASS", 40, 340, 44, bold: true)
draw("PASSENGER  DEMO TRAVELLER", 40, 270, 30)
draw("FROM BLR", 40, 200, 40, bold: true)
draw("TO DEL", 420, 200, 40, bold: true)
draw("DATE  SATURDAY", 40, 120, 40, bold: true)
draw("GATE 12   SEAT 14C", 40, 50, 30)
image.unlockFocus()
let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
