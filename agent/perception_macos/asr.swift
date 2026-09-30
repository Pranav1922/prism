// On-device speech recognition for the local perception worker (macOS only).
// Usage: prism_asr <audio file>   -> prints the final transcript on stdout; exit != 0 on failure.
// Built by scripts/build_asr.sh; the embedded Info.plist carries the speech-recognition usage string.
import Foundation
import Speech

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let auth = DispatchSemaphore(value: 0)
var authorised = false
SFSpeechRecognizer.requestAuthorization { status in
    authorised = status == .authorized
    auth.signal()
}
auth.wait()
guard authorised, let rec = SFSpeechRecognizer(locale: Locale(identifier: "en-US")), rec.isAvailable else {
    FileHandle.standardError.write("speech recognition unavailable or not authorised\n".data(using: .utf8)!)
    exit(2)
}
let req = SFSpeechURLRecognitionRequest(url: url)
req.requiresOnDeviceRecognition = rec.supportsOnDeviceRecognition  // never leaves the machine when supported
req.shouldReportPartialResults = false
rec.recognitionTask(with: req) { result, error in
    if let r = result, r.isFinal {
        print(r.bestTranscription.formattedString)
        exit(0)
    }
    if let e = error {
        FileHandle.standardError.write("\(e)\n".data(using: .utf8)!)
        exit(3)
    }
}
RunLoop.main.run(until: Date(timeIntervalSinceNow: 30))
exit(4)
