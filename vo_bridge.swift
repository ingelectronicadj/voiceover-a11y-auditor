// vo_bridge.swift - Puente nativo Xcode para iOS VoiceOver / Accessibility Inspector y WebKit Remote Inspector (WKWebView).
// Conecta con CoreSimulator, AccessibilityAuditDeviceManager y WebInspector sin dependencias externas.
import Foundation
import ObjectiveC
import AppKit
import Vision

func loadXcodeFrameworks(onlyWebInspector: Bool = false, includeWebInspector: Bool = false) {
    if onlyWebInspector {
        dlopen("/System/Library/PrivateFrameworks/WebInspector.framework/WebInspector", RTLD_NOW)
        return
    }
    dlopen("/Library/Developer/PrivateFrameworks/CoreSimulator.framework/CoreSimulator", RTLD_NOW)
    dlopen("/Applications/Xcode.app/Contents/SharedFrameworks/DTXConnectionServices.framework/DTXConnectionServices", RTLD_NOW)
    dlopen("/Applications/Xcode.app/Contents/Applications/Accessibility Inspector.app/Contents/Frameworks/AccessibilityAuditDeviceManager.framework/AccessibilityAuditDeviceManager", RTLD_NOW)
    if includeWebInspector {
        dlopen("/System/Library/PrivateFrameworks/WebInspector.framework/WebInspector", RTLD_NOW)
    }
}

func detectHighlightAndScreenSig(pngPath: String) -> ([Int]?, [Int], String, Bool) {
    guard let img = NSImage(contentsOfFile: pngPath),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return (nil, [], "", false)
    }
    let w = cg.width
    let h = cg.height
    var data = [UInt8](repeating: 0, count: w * h * 4)
    guard let ctx = CGContext(
        data: &data,
        width: w,
        height: h,
        bitsPerComponent: 8,
        bytesPerRow: w * 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
    ) else {
        return (nil, [], "", false)
    }
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))

    var rowCounts = [Int: Int]()
    var colCounts = [Int: Int]()
    var greenPts = [(Int, Int)]()
    for y in stride(from: 0, to: h, by: 2) {
        let row = y * w * 4
        for x in stride(from: 0, to: w, by: 2) {
            let i = row + x * 4
            let r = Int(data[i])
            let g = Int(data[i + 1])
            let b = Int(data[i + 2])
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
    var box: [Int]? = nil
    if filtered.count >= 16 {
        let xs = filtered.map { $0.0 }
        let ys = filtered.map { $0.1 }
        if let x1 = xs.min(), let x2 = xs.max(), let y1 = ys.min(), let y2 = ys.max() {
            box = [x1, y1, x2, y2]
        }
    }

    var sig = [Int]()
    let gw = 8, gh = 12
    for gy in 0..<gh {
        for gx in 0..<gw {
            let sx = Int((Double(gx) + 0.5) * Double(w) / Double(gw))
            let sy = Int((Double(gy) + 0.5) * Double(h) / Double(gh))
            let idx = (sy * w + sx) * 4
            sig.append((Int(data[idx]) + Int(data[idx + 1]) + Int(data[idx + 2])) / 3)
        }
    }

    // OCR ligero para detectar page_title e is_skeleton
    var hdrLines = [(Double, Double, String)]()
    var bodyCount = 0
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .fast
    req.recognitionLanguages = ["es-ES", "en-US"]
    let handler = VNImageRequestHandler(cgImage: cg)
    try? handler.perform([req])
    for obs in req.results ?? [] {
        if let cand = obs.topCandidates(1).first {
            let bb = obs.boundingBox
            let topY = 1.0 - bb.origin.y - bb.size.height
            let cy = topY + bb.size.height / 2.0
            let txt = cand.string.trimmingCharacters(in: .whitespacesAndNewlines)
            if cy >= 0.05 && cy <= 0.185 {
                if txt.count >= 3 {
                    hdrLines.append((cy, bb.origin.x, txt))
                }
            } else if cy > 0.185 && cy < 0.85 {
                if txt.count >= 2 {
                    bodyCount += 1
                }
            }
        }
    }
    hdrLines.sort { $0.0 < $1.0 }
    let pageTitle = hdrLines.map { $0.2 }.joined(separator: " ")
    let isSkeleton = !pageTitle.isEmpty && bodyCount == 0
    return (box, sig, pageTitle, isSkeleton)
}

func takeSimScreenshot(udid: String, path: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
    p.arguments = ["simctl", "io", udid, "screenshot", path]
    p.standardOutput = FileHandle.nullDevice
    p.standardError = FileHandle.nullDevice
    try? p.run()
    p.waitUntilExit()
}

class AuditDelegate: NSObject {
    var connected = false
    var lastFocus: NSObject? = nil
    var focusSeq = 0
    var issuesFound = [[String: Any]]()
    var auditDone = false

    @objc(deviceIsAuthorizedForCommunication:)
    func deviceIsAuthorizedForCommunication(_ dev: AnyObject) -> Bool {
        return true
    }
    @objc(device:didSuccessfullyConnect:)
    func device(_ dev: AnyObject, didSuccessfullyConnect ok: Bool) {
        connected = ok
    }
    @objc(deviceManagerDevicesDidUpdate:)
    func deviceManagerDevicesDidUpdate(_ devs: AnyObject?) {}
    @objc(deviceAvailableApplicationsDidUpdate:)
    func deviceAvailableApplicationsDidUpdate(_ dev: AnyObject?) {}
    @objc(deviceFrontmostAppPidDidUpdate:frontmostAppPid:)
    func deviceFrontmostAppPidDidUpdate(_ dev: AnyObject?, frontmostAppPid pid: Int32) {}
    @objc(device:didUpdateAccessibilitySetting:)
    func device(_ dev: AnyObject?, didUpdateAccessibilitySetting s: AnyObject?) {}
    @objc(device:inspectorMonitoredEventTypeDidChange:)
    func device(_ dev: AnyObject?, inspectorMonitoredEventTypeDidChange t: UInt64) {}
    @objc(device:inspectorFocusDidChange:)
    func device(_ dev: AnyObject, inspectorFocusDidChange focus: NSObject?) {
        lastFocus = focus
        focusSeq += 1
    }
    @objc(device:inspectorElementPropertiesDidChange:)
    func device(_ dev: AnyObject?, inspectorElementPropertiesDidChange props: AnyObject?) {}
    @objc(device:inspectorNotificationReceived:)
    func device(_ dev: AnyObject?, inspectorNotificationReceived n: AnyObject?) {}
    @objc(device:didFindAuditIssue:)
    func device(_ dev: AnyObject?, didFindAuditIssue issue: NSObject?) {}
    @objc(device:didCompleteAuditWithIssues:)
    func device(_ dev: AnyObject?, didCompleteAuditWithIssues issues: AnyObject?) {
        if let arr = issues as? [NSObject] {
            for item in arr {
                let desc = (item.value(forKey: "elementDescription") as? String) ?? ""
                let txt = (item.value(forKey: "elementText") as? String) ?? ""
                let clsif = (item.value(forKey: "issueClassification") as? Int) ?? 0
                let extra = (item.value(forKey: "longDescExtraInfo") as? [String]) ?? []
                issuesFound.append([
                    "classification": clsif,
                    "elementDescription": desc,
                    "elementText": txt,
                    "extra": extra
                ])
            }
        }
        auditDone = true
    }
    @objc(device:runningAudit:)
    func device(_ dev: AnyObject?, runningAudit r: Bool) {
        if !r { auditDone = true }
    }
    @objc(device:didAppendAuditLog:)
    func device(_ dev: AnyObject?, didAppendAuditLog log: AnyObject?) {}
}

func connectSimulatorDevice(udid: String, delegate: AuditDelegate) -> NSObject? {
    guard let cls = objc_getClass("XDMDeviceManager") as? NSObject.Type,
          let mgr = cls.perform(NSSelectorFromString("sharedManager"))?.takeUnretainedValue() as? NSObject else {
        return nil
    }
    mgr.setValue(delegate, forKey: "delegate")
    typealias SetTypesFn = @convention(c) (AnyObject, Selector, Int) -> Void
    let sel = NSSelectorFromString("setDeviceTypesToMonitor:")
    if let imp = mgr.method(for: sel) {
        unsafeBitCast(imp, to: SetTypesFn.self)(mgr, sel, 0xFF)
    }
    _ = mgr.perform(NSSelectorFromString("startDeviceMonitors"))
    let deadline = Date().addingTimeInterval(3.0)
    var targetDev: NSObject? = nil
    while Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        if let devs = mgr.perform(NSSelectorFromString("allDevices"))?.takeUnretainedValue() as? [NSObject] {
            if let exact = devs.first(where: { (($0.value(forKey: "deviceIdentifier") as? String) ?? "").lowercased() == udid.lowercased() }) {
                targetDev = exact
                break
            }
            if udid == "booted", let sim = devs.first(where: { String(describing: type(of: $0)).contains("SIM") }) {
                targetDev = sim
                break
            }
        }
    }
    guard let sim = targetDev else { return nil }
    sim.setValue(delegate, forKey: "delegate")
    sim.setValue(delegate, forKey: "applicationsDelegate")
    _ = mgr.perform(NSSelectorFromString("attemptConnectionToDevice:"), with: sim)
    let connDeadline = Date().addingTimeInterval(4.0)
    while Date() < connDeadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        let st = (sim.value(forKey: "connectionStatus") as? Int) ?? 0
        if st == 4 || delegate.connected {
            RunLoop.current.run(until: Date().addingTimeInterval(0.4))
            break
        }
    }
    return sim
}

func setInspectorOverlay(_ sim: NSObject, enabled: Bool) {
    typealias BoolFn = @convention(c) (AnyObject, Selector, Bool) -> Void
    let order = enabled
        ? ["inspectorEnable:", "setInspectorShowVisuals:", "enableHighlight:"]
        : ["setInspectorShowVisuals:", "enableHighlight:", "inspectorEnable:"]
    for sname in order {
        let s = NSSelectorFromString(sname)
        if let imp = sim.method(for: s) {
            unsafeBitCast(imp, to: BoolFn.self)(sim, s, enabled)
        }
    }
    RunLoop.current.run(until: Date().addingTimeInterval(0.35))
}

func moveFocus(_ sim: NSObject, direction: Int, allowContainers: Bool = false, allowNonAX: Bool = false) {
    typealias MoveFn = @convention(c) (AnyObject, Selector, Int, Bool, Bool) -> Void
    let moveSel = NSSelectorFromString("inspectorMoveInDirection:allowMovingToContainers:allowMoveToNonAXElements:")
    if let imp = sim.method(for: moveSel) {
        unsafeBitCast(imp, to: MoveFn.self)(sim, moveSel, direction, allowContainers, allowNonAX)
    }
}

func fetchFocusDetails(_ sim: NSObject, focus: NSObject) -> [String: Any] {
    let caption = (focus.value(forKey: "captionText") as? String) ?? ""
    let spoken = (focus.value(forKey: "spokenDescription") as? String) ?? ""
    var details: [String: Any] = [
        "caption": caption,
        "spoken": spoken,
        "label": "",
        "value": "",
        "traits": [String](),
        "identifier": "",
        "hint": "",
        "userInputLabels": [String](),
        "className": "",
        "controller": "",
        "hierarchy": "",
        "hasActivateAction": false
    ]
    guard let el = focus.value(forKey: "element") as? NSObject,
          let secs = focus.value(forKey: "inspectorSections") as? [NSObject],
          let propCls = objc_getClass("XRCInspectorProperty") as? NSObject.Type else {
        return details
    }
    if let axId = el.value(forKey: "accessibilityIdentifier") as? String, !axId.isEmpty {
        details["identifier"] = axId
    }
    typealias FetchPropFn = @convention(c) (AnyObject, Selector, @escaping @convention(block) (AnyObject?) -> Void) -> Void
    let fsel = NSSelectorFromString("fetchValueWithCompletionBlock:")
    var pending = 0
    for s in secs {
        guard let attrs = s.value(forKey: "elementAttributes") as? [NSObject] else { continue }
        for a in attrs {
            let aname = (a.value(forKey: "attributeName") as? String) ?? ""
            let isAction = (a.value(forKey: "performsAction") as? Bool) ?? false
            if isAction {
                if aname == "AXAction-2010" {
                    details["hasActivateAction"] = true
                }
                continue
            }
            let prop = propCls.init()
            prop.setValue(a, forKey: "elementAttribute")
            prop.setValue(el, forKey: "element")
            prop.setValue(sim, forKey: "delegate")
            guard let imp = prop.method(for: fsel) else { continue }
            pending += 1
            unsafeBitCast(imp, to: FetchPropFn.self)(prop, fsel) { _ in
                let rawVal = prop.value(forKey: "value")
                switch aname {
                case "Label":
                    details["label"] = (rawVal as? String) ?? ""
                case "Value":
                    details["value"] = (rawVal as? String) ?? ""
                case "TraitsHumanReadable":
                    if let arr = rawVal as? [String] {
                        details["traits"] = arr
                    } else if let str = rawVal as? String {
                        details["traits"] = [str]
                    }
                case "Identifier":
                    if let str = rawVal as? String, !str.isEmpty {
                        details["identifier"] = str
                    }
                case "Hint":
                    details["hint"] = (rawVal as? String) ?? ""
                case "UserInputLabels":
                    if let arr = rawVal as? [String] {
                        details["userInputLabels"] = arr
                    }
                case "ElementClassName":
                    details["className"] = (rawVal as? String) ?? ""
                case "ElementViewControllerClassName":
                    details["controller"] = (rawVal as? String) ?? ""
                case "_AXHierarchyElementsAttribute":
                    if let nodeObj = rawVal as? NSObject {
                        details["hierarchy"] = nodeObj.description
                    }
                default:
                    break
                }
                pending -= 1
            }
        }
    }
    let waitUntil = Date().addingTimeInterval(0.75)
    while pending > 0 && Date() < waitUntil {
        RunLoop.current.run(until: Date().addingTimeInterval(0.04))
    }
    return details
}

func activateFocusedElement(_ sim: NSObject, focus: NSObject) -> Bool {
    guard let el = focus.value(forKey: "element") as? NSObject,
          let secs = focus.value(forKey: "inspectorSections") as? [NSObject],
          let propCls = objc_getClass("XRCInspectorProperty") as? NSObject.Type else {
        return false
    }
    typealias FetchFn = @convention(c) (AnyObject, Selector, AnyObject, @escaping @convention(block) (AnyObject?) -> Void) -> Void
    let fetchSel = NSSelectorFromString("fetchValueForProperty:completionBlock:")
    guard let fetchImp = sim.method(for: fetchSel) else { return false }
    let fetchFn = unsafeBitCast(fetchImp, to: FetchFn.self)
    for s in secs {
        guard let attrs = s.value(forKey: "elementAttributes") as? [NSObject] else { continue }
        for a in attrs {
            let isAction = (a.value(forKey: "performsAction") as? Bool) ?? false
            let aname = (a.value(forKey: "attributeName") as? String) ?? ""
            if isAction && aname == "AXAction-2010" {
                let prop = propCls.init()
                prop.setValue(a, forKey: "elementAttribute")
                prop.setValue(el, forKey: "element")
                var done = false
                fetchFn(sim, fetchSel, prop) { _ in
                    done = true
                }
                let waitUntil = Date().addingTimeInterval(1.0)
                while !done && Date() < waitUntil {
                    RunLoop.current.run(until: Date().addingTimeInterval(0.05))
                }
                return true
            }
        }
    }
    return false
}

class RWIChannelDelegate: NSObject {
    var targetId: String? = nil
    var evalResult: Any? = nil
    var evalDone = false

    @objc(channel:receivedMessage:)
    func channel(_ ch: AnyObject, receivedMessage msg: NSString) {
        let s = msg as String
        guard let data = s.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        let method = (obj["method"] as? String) ?? ""
        if method == "Target.targetCreated",
           let params = obj["params"] as? [String: Any],
           let tinfo = params["targetInfo"] as? [String: Any],
           let tid = tinfo["targetId"] as? String {
            targetId = tid
        } else if method == "Target.dispatchMessageFromTarget",
                  let params = obj["params"] as? [String: Any],
                  let innerStr = params["message"] as? String,
                  let innerData = innerStr.data(using: .utf8),
                  let innerObj = try? JSONSerialization.jsonObject(with: innerData) as? [String: Any],
                  (innerObj["id"] as? Int) == 10 {
            if let res = innerObj["result"] as? [String: Any],
               let innerRes = res["result"] as? [String: Any] {
                evalResult = innerRes["value"]
            }
            evalDone = true
        }
    }
    @objc(channelDidClose:)
    func channelDidClose(_ ch: AnyObject) {
        evalDone = true
    }
}

func evaluateWKWebViewJS(udid: String, jsExpr: String, awaitPromise: Bool = false) -> Any? {
    loadXcodeFrameworks(onlyWebInspector: true)
    guard let cls = objc_getClass("RWIManager") as? NSObject.Type,
          let mgr = cls.perform(NSSelectorFromString("sharedManager"))?.takeUnretainedValue() as? NSObject else {
        return nil
    }
    RunLoop.current.run(until: Date().addingTimeInterval(1.2))
    guard let targets = mgr.perform(NSSelectorFromString("targets"))?.takeUnretainedValue() as? Set<NSObject> else {
        return nil
    }
    let target = targets.first(where: { (($0.value(forKey: "udid") as? String) ?? "").lowercased() == udid.lowercased() })
        ?? targets.first(where: { (($0.value(forKey: "isSimulator") as? Bool) ?? false) && (($0.value(forKey: "allApplications") as? [Any])?.isEmpty == false) })
    guard let t = target,
          let apps = t.value(forKey: "allApplications") as? [NSObject] else {
        return nil
    }
    var chosenPage: NSObject? = nil
    var fallbackPage: NSObject? = nil
    for app in apps {
        guard let pages = app.value(forKey: "allDebuggables") as? [NSObject] else { continue }
        for p in pages {
            let u = ((p.value(forKey: "url") as? String) ?? "").lowercased()
            if fallbackPage == nil {
                fallbackPage = p
            }
            if !u.isEmpty && u != "about:blank" && !u.contains("utag/") && !u.contains("analytics") {
                chosenPage = p
                if u.contains("hybrid/") || u.contains("http") || u.contains("file://") {
                    break
                }
            }
        }
        if chosenPage != nil { break }
    }
    guard let page = chosenPage ?? fallbackPage else { return nil }
    typealias OpenChFn = @convention(c) (AnyObject, Selector, AnyObject, UnsafeMutablePointer<NSError?>?) -> AnyObject?
    let sel = NSSelectorFromString("openChannelForDebuggable:error:")
    var err: NSError? = nil
    guard let imp = mgr.method(for: sel),
          let ch = unsafeBitCast(imp, to: OpenChFn.self)(mgr, sel, page, &err) as? NSObject else {
        return nil
    }
    let cdel = RWIChannelDelegate()
    ch.setValue(cdel, forKey: "delegate")
    _ = ch.perform(NSSelectorFromString("start"))
    let tDeadline = Date().addingTimeInterval(1.0)
    while cdel.targetId == nil && Date() < tDeadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    guard let tid = cdel.targetId else {
        _ = ch.perform(NSSelectorFromString("close"))
        RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        return nil
    }
    let effectiveExpr: String
    if awaitPromise {
        effectiveExpr = "window.__vo_async_res = null; Promise.resolve(\(jsExpr)).then(v => { window.__vo_async_res = v || 'empty'; }).catch(e => { window.__vo_async_res = 'err:' + e; }); 'pending'"
    } else {
        effectiveExpr = jsExpr
    }
    let innerDict: [String: Any] = [
        "id": 10,
        "method": "Runtime.evaluate",
        "params": [
            "expression": effectiveExpr,
            "returnByValue": true
        ]
    ]
    let innerStr = String(data: try! JSONSerialization.data(withJSONObject: innerDict), encoding: .utf8)!
    let outerDict: [String: Any] = [
        "id": 1,
        "method": "Target.sendMessageToTarget",
        "params": [
            "targetId": tid,
            "message": innerStr
        ]
    ]
    let outerStr = String(data: try! JSONSerialization.data(withJSONObject: outerDict), encoding: .utf8)!
    _ = ch.perform(NSSelectorFromString("sendMessageToBackend:"), with: outerStr)
    let evalDeadline = Date().addingTimeInterval(5.0)
    while !cdel.evalDone && Date() < evalDeadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    if awaitPromise {
        for pollIdx in 1...120 {
            RunLoop.current.run(until: Date().addingTimeInterval(0.12))
            cdel.evalDone = false
            cdel.evalResult = nil
            let pollInner: [String: Any] = [
                "id": 10,
                "method": "Runtime.evaluate",
                "params": [
                    "expression": "window.__vo_async_res",
                    "returnByValue": true
                ]
            ]
            let pollInnerStr = String(data: try! JSONSerialization.data(withJSONObject: pollInner), encoding: .utf8)!
            let pollOuter: [String: Any] = [
                "id": 1 + pollIdx,
                "method": "Target.sendMessageToTarget",
                "params": [
                    "targetId": tid,
                    "message": pollInnerStr
                ]
            ]
            let pollOuterStr = String(data: try! JSONSerialization.data(withJSONObject: pollOuter), encoding: .utf8)!
            _ = ch.perform(NSSelectorFromString("sendMessageToBackend:"), with: pollOuterStr)
            let pDeadline = Date().addingTimeInterval(1.0)
            while !cdel.evalDone && Date() < pDeadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.03))
            }
            if let strVal = cdel.evalResult as? String, !strVal.isEmpty {
                break
            }
        }
    }
    _ = ch.perform(NSSelectorFromString("close"))
    RunLoop.current.run(until: Date().addingTimeInterval(0.30))
    return cdel.evalResult
}

let args = Array(CommandLine.arguments.dropFirst())
let cmd = args.first ?? "help"

func argVal(_ flag: String, default defVal: String = "") -> String {
    if let idx = args.firstIndex(of: flag), idx + 1 < args.count {
        return args[idx + 1]
    }
    return defVal
}

func hasFlag(_ flag: String) -> Bool {
    return args.contains(flag)
}

if cmd == "rwi-eval" {
    let udid = argVal("--udid", default: "booted")
    let jsFile = argVal("--js-file")
    let jsInline = argVal("--js")
    let awaitProm = hasFlag("--await-promise")
    let expr: String
    if !jsFile.isEmpty, let content = try? String(contentsOfFile: jsFile, encoding: .utf8) {
        expr = content
    } else {
        expr = jsInline
    }
    if let res = evaluateWKWebViewJS(udid: udid, jsExpr: expr, awaitPromise: awaitProm) {
        if let str = res as? String {
            print(str)
        } else if let data = try? JSONSerialization.data(withJSONObject: res),
                  let str = String(data: data, encoding: .utf8) {
            print(str)
        }
    } else {
        print("null")
    }
    exit(0)
}

if cmd == "reset-overlay" {
    loadXcodeFrameworks()
    let udid = argVal("--udid", default: "booted")
    let del = AuditDelegate()
    if let sim = connectSimulatorDevice(udid: udid, delegate: del) {
        setInspectorOverlay(sim, enabled: false)
    }
    print("{\"status\":\"ok\"}")
    exit(0)
}

if cmd == "tap-element" {
    loadXcodeFrameworks()
    let udid = argVal("--udid", default: "booted")
    let matchTxt = argVal("--match").lowercased()
    let coordStr = argVal("--coord")
    let maxSteps = Int(argVal("--steps", default: "40")) ?? 40
    let del = AuditDelegate()
    guard let sim = connectSimulatorDevice(udid: udid, delegate: del) else {
        print("{\"ok\":false,\"error\":\"simulator_not_connected\"}")
        exit(1)
    }
    setInspectorOverlay(sim, enabled: true)
    var activated = false
    var matchedCaption = ""
    if !coordStr.isEmpty {
        let parts = coordStr.split(separator: ",").compactMap { Double($0) }
        if parts.count == 2 {
            typealias FetchCoordFn = @convention(c) (AnyObject, Selector, CGPoint, @escaping @convention(block) (AnyObject?) -> Void) -> Void
            let csel = NSSelectorFromString("fetchElementAtNormalizedDeviceCoordinate:withCompletionBlock:")
            if let imp = sim.method(for: csel) {
                unsafeBitCast(imp, to: FetchCoordFn.self)(sim, csel, CGPoint(x: parts[0], y: parts[1])) { el in
                    if let el = el {
                        _ = sim.perform(NSSelectorFromString("inspectorFocusOnElement:"), with: el)
                    }
                }
                RunLoop.current.run(until: Date().addingTimeInterval(0.7))
                if let f = del.lastFocus {
                    matchedCaption = (f.value(forKey: "captionText") as? String) ?? ""
                    activated = activateFocusedElement(sim, focus: f)
                    RunLoop.current.run(until: Date().addingTimeInterval(0.8))
                }
            }
        }
    } else if !matchTxt.isEmpty {
        moveFocus(sim, direction: 5)
        RunLoop.current.run(until: Date().addingTimeInterval(0.6))
        for step in 1...maxSteps {
            if step > 1 {
                moveFocus(sim, direction: 4)
                RunLoop.current.run(until: Date().addingTimeInterval(0.5))
            }
            guard let f = del.lastFocus else { continue }
            let det = fetchFocusDetails(sim, focus: f)
            let cap = (det["caption"] as? String) ?? ""
            let lbl = (det["label"] as? String) ?? ""
            let ident = (det["identifier"] as? String) ?? ""
            let blob = "\(cap) \(lbl) \(ident)".lowercased()
            if blob.contains(matchTxt) {
                matchedCaption = cap
                activated = activateFocusedElement(sim, focus: f)
                RunLoop.current.run(until: Date().addingTimeInterval(0.8))
                break
            }
        }
    }
    setInspectorOverlay(sim, enabled: false)
    let out: [String: Any] = ["ok": activated, "matched": matchedCaption]
    let data = try! JSONSerialization.data(withJSONObject: out)
    print(String(data: data, encoding: .utf8)!)
    exit(0)
}

if cmd == "walk" {
    loadXcodeFrameworks()
    let udid = argVal("--udid", default: "booted")
    let maxSteps = Int(argVal("--steps", default: "80")) ?? 80
    let delaySec = Double(argVal("--delay", default: "0.75")) ?? 0.75
    let outDir = argVal("--out-dir", default: ".")
    let backward = hasFlag("--backward")
    let testModals = hasFlag("--test-modals")

    let imgDir = (outDir as NSString).appendingPathComponent("img")
    try? FileManager.default.createDirectory(atPath: imgDir, withIntermediateDirectories: true)

    let del = AuditDelegate()
    guard let sim = connectSimulatorDevice(udid: udid, delegate: del) else {
        fputs("ERROR: No se pudo conectar con XDMDeviceSIM (\(udid))\n", stderr)
        exit(1)
    }

    setInspectorOverlay(sim, enabled: true)

    // Posicionar deterministamente en el primer elemento (dir=5) o ultimo (dir=6)
    moveFocus(sim, direction: backward ? 6 : 5)
    RunLoop.current.run(until: Date().addingTimeInterval(max(0.65, delaySec)))
    if del.lastFocus == nil {
        moveFocus(sim, direction: backward ? 3 : 4)
        RunLoop.current.run(until: Date().addingTimeInterval(max(0.65, delaySec)))
    }

    var stepsOut = [[String: Any]]()
    var treeNodesOut = [[String: Any]]()
    var seenKeys = Set<String>()
    var prevSigKey = ""
    var repeats = 0
    var prevScreenSig = [Int]()
    var testedModals = Set<String>()
    var chartStreak = 0
    var linkListStreak = 0
    var skippedCoinList = false
    var stepNum = 0

    for idx in 1...maxSteps {
        stepNum += 1
        if idx > 1 {
            let prevSeq = del.focusSeq
            moveFocus(sim, direction: backward ? 3 : 4)
            let waitDeadline = Date().addingTimeInterval(max(0.45, delaySec))
            while Date() < waitDeadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.05))
                if del.focusSeq > prevSeq {
                    RunLoop.current.run(until: Date().addingTimeInterval(0.25))
                    break
                }
            }
        }

        guard let f = del.lastFocus else {
            repeats += 1
            if repeats >= 3 { break }
            continue
        }

        let det = fetchFocusDetails(sim, focus: f)
        let cap = ((det["caption"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let spk = ((det["spoken"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let lbl = ((det["label"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let val = ((det["value"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let ident = ((det["identifier"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let hint = ((det["hint"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let clsName = ((det["className"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let ctrlName = ((det["controller"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let traits = (det["traits"] as? [String]) ?? []
        let hasAct = (det["hasActivateAction"] as? Bool) ?? false

        let pngName = String(format: "step_%03d.png", stepNum)
        let pngPath = (imgDir as NSString).appendingPathComponent(pngName)
        takeSimScreenshot(udid: udid, path: pngPath)

        let (box, curScreenSig, pageTitle, isSkeleton) = detectHighlightAndScreenSig(pngPath: pngPath)
        var screenChange = false
        if !prevScreenSig.isEmpty && curScreenSig.count == prevScreenSig.count {
            let diff = zip(prevScreenSig, curScreenSig).map { abs($0 - $1) }.reduce(0, +) / curScreenSig.count
            screenChange = diff > 65
        }
        if !curScreenSig.isEmpty {
            prevScreenSig = curScreenSig
        }

        let utt = !spk.isEmpty ? spk : cap
        let boxKey = box != nil ? "\(box![0]),\(box![1]),\(box![2]),\(box![3])" : "nobox"
        let sigKey = "\(utt)|\(ident)|\(lbl)|\(boxKey)"

        if sigKey == prevSigKey {
            repeats += 1
            if idx >= 2 && repeats >= 1 {
                // En iOS VoiceOver / AXAudit, cuando inspectorMoveInDirection llega al último elemento
                // de la vista, el foco permanece en ese último nodo sin avanzar más.
                try? FileManager.default.removeItem(atPath: pngPath)
                stepNum -= 1
                fputs("      fin de la vista alcanzado en paso \(stepNum)\n", stderr)
                break
            }
        } else if idx > 18,
                  let prevStep = stepsOut.last,
                  (prevStep["is_modal"] as? Bool) != true,
                  let firstStep = stepsOut.first,
                  let firstUtt = firstStep["utterance"] as? String,
                  !utt.isEmpty && utt == firstUtt && ident == ((firstStep["node"] as? [String: Any])?["rid"] as? String ?? "") {
            try? FileManager.default.removeItem(atPath: pngPath)
            stepNum -= 1
            fputs("      ciclo completo alcanzado en paso \(stepNum)\n", stderr)
            break
        } else {
            repeats = 0
        }
        prevSigKey = sigKey

        let roleTraits = traits.joined(separator: ", ")
        let effectiveCls = !roleTraits.isEmpty ? roleTraits : (!clsName.isEmpty ? clsName : "UIAccessibilityElement")
        let nodeDict: [String: Any] = [
            "text": lbl,
            "desc": !hint.isEmpty ? "\(lbl) (\(hint))" : lbl,
            "value": val,
            "cls": effectiveCls,
            "native_cls": clsName,
            "controller": ctrlName,
            "traits": traits,
            "rid": ident,
            "hint": hint,
            "clickable": hasAct || traits.contains(where: { $0.lowercased().contains("button") || $0.lowercased().contains("link") }),
            "focusable": true,
            "checked": traits.contains(where: { $0.lowercased().contains("selected") }) ? "true" : "false",
            "bounds": box as Any,
            "pkg": ""
        ]

        let nodeUniqueKey = "\(lbl)|\(ident)|\(effectiveCls)"
        if !seenKeys.contains(nodeUniqueKey) {
            seenKeys.insert(nodeUniqueKey)
            treeNodesOut.append(nodeDict)
        }

        let stepDict: [String: Any] = [
            "i": stepNum,
            "png": pngPath,
            "node": nodeDict,
            "utterance": utt,
            "raw_caption": cap,
            "page_title": pageTitle,
            "is_skeleton": isSkeleton,
            "box": box as Any,
            "in_overlay": false,
            "label": !lbl.isEmpty ? lbl : utt,
            "screen_change": screenChange
        ]
        stepsOut.append(stepDict)
        let dispLbl = (!lbl.isEmpty ? lbl : (!ident.isEmpty ? ident : "?")).prefix(50)
        let dispUtt = utt.prefix(60)
        fputs(String(format: "      %3d. %-52@ | dice: %@\n", stepNum, String(dispLbl) as NSString, String(dispUtt) as NSString), stderr)

        // Prueba automatica de Retorno de Foco en modales/drawers (--test-modals)
        let uLow = utt.lowercased()
        if (uLow.contains("date:") && uLow.contains("value")) || (uLow.contains("fecha:") && uLow.contains("valor")) {
            chartStreak += 1
            if chartStreak == 5 {
                _ = evaluateWKWebViewJS(
                    udid: udid,
                    jsExpr: "(() => { Array.from(document.querySelectorAll('circle[data-testid=\"node-circle\"], circle.node-path-focus-border')).slice(5).forEach(c => { c.setAttribute('aria-hidden', 'true'); c.setAttribute('tabindex', '-1'); c.removeAttribute('role'); c.removeAttribute('aria-label'); }); return 'ok'; })()"
                )
                RunLoop.current.run(until: Date().addingTimeInterval(0.6))
                fputs("      [auto-skip gráfica] saltados los puntos restantes del gráfico para auditar el resto de la vista\n", stderr)
            }
        } else {
            chartStreak = 0
        }
        if !skippedCoinList && uLow.hasSuffix("link") {
            linkListStreak += 1
            if linkListStreak == 11 {
                skippedCoinList = true
                _ = evaluateWKWebViewJS(
                    udid: udid,
                    jsExpr: "(() => { Array.from(document.querySelectorAll('a[href*=\"/product/\"]')).slice(3).forEach(a => { a.setAttribute('aria-hidden', 'true'); a.setAttribute('tabindex', '-1'); const li = a.closest('li'); if (li) li.setAttribute('aria-hidden', 'true'); }); return 'ok'; })()"
                )
                RunLoop.current.run(until: Date().addingTimeInterval(0.6))
                fputs("      [auto-skip lista activos] saltadas las filas repetidas restantes para auditar Últimas órdenes, Carrusel y Pie legal\n", stderr)
            }
        } else if !uLow.contains("link") {
            linkListStreak = 0
        }
        if testModals && !utt.isEmpty && !testedModals.contains(utt) && (
            uLow.contains("más información sobre") ||
            uLow.contains("more information on") ||
            uLow.contains("select your linked account") ||
            uLow.contains("elegí qué") ||
            uLow.contains("choose a ") ||
            uLow.contains("order type") ||
            uLow.contains("tipo de orden")
        ) {
            testedModals.insert(utt)
            fputs("      [test-modals] activando '\(utt.prefix(45))' para validar Focus Return...\n", stderr)
            let cleanTarget = (lbl.isEmpty ? utt : lbl).replacingOccurrences(of: "\"", with: "").replacingOccurrences(of: "\\", with: "").replacingOccurrences(of: "\n", with: " ")
            _ = evaluateWKWebViewJS(
                udid: udid,
                jsExpr: "(() => { const q = \"\(cleanTarget)\".toLowerCase(); const btn = Array.from(document.querySelectorAll('button,[role=\"button\"]')).find(b => ((b.getAttribute('aria-label') || b.innerText || '').toLowerCase()).includes(q)); if (btn) { btn.click(); return 'clicked'; } return 'no'; })()"
            )
            if activateFocusedElement(sim, focus: f) || true {
                RunLoop.current.run(until: Date().addingTimeInterval(2.0))
                moveFocus(sim, direction: 5)
                RunLoop.current.run(until: Date().addingTimeInterval(0.8))
                stepNum += 1
                let mPng = (imgDir as NSString).appendingPathComponent(String(format: "step_%03d.png", stepNum))
                takeSimScreenshot(udid: udid, path: mPng)
                let (mBox, _, mTitle, mSkel) = detectHighlightAndScreenSig(pngPath: mPng)
                let mFocus = del.lastFocus
                let mDet = mFocus != nil ? fetchFocusDetails(sim, focus: mFocus!) : [:]
                let mUtt = (mDet["spoken"] as? String) ?? (mDet["caption"] as? String) ?? mTitle
                stepsOut.append([
                    "i": stepNum,
                    "png": mPng,
                    "node": NSNull(),
                    "utterance": mUtt,
                    "raw_caption": (mDet["caption"] as? String) ?? mUtt,
                    "page_title": mTitle,
                    "is_skeleton": mSkel,
                    "box": mBox as Any,
                    "in_overlay": false,
                    "label": !mTitle.isEmpty ? mTitle : "Modal / Drawer",
                    "screen_change": true,
                    "is_modal": true
                ])
                // Intentar cerrar modal por WKWebView o accion accesible
                _ = evaluateWKWebViewJS(
                    udid: udid,
                    jsExpr: "(() => { const el = document.querySelector('button[aria-label=\"Cerrar\"],button[aria-label=\"Close\"],button[data-testid*=\"close\"]'); if (el) { el.click(); return 'closed'; } return 'no'; })()"
                )
                RunLoop.current.run(until: Date().addingTimeInterval(1.4))
            }
        }
    }

    setInspectorOverlay(sim, enabled: false)
    let resultObj: [String: Any] = [
        "steps": stepsOut,
        "tree_nodes": treeNodesOut
    ]
    let jsonData = try! JSONSerialization.data(withJSONObject: resultObj)
    print(String(data: jsonData, encoding: .utf8)!)
    exit(0)
}

print("usage: vo_bridge <walk|rwi-eval|tap-element|reset-overlay> [options]")
