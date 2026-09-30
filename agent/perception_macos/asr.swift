// On-device speech recognition for the local perception worker (macOS only).
// Usage: prism_asr <audio file>   -> prints the final transcript on stdout; exit != 0 on failure.
//        prism_asr --stream       -> reads raw 16 kHz mono 16-bit little-endian PCM on stdin as it is recorded and
//                                    prints one JSON line per hypothesis, {"text": ..., "final": false|true}, while
//                                    the audio is still arriving (the recogniser's own partial results); stdin EOF
//                                    ends the audio and the last line is the final transcript.
// Built by scripts/build_asr.sh; the embedded Info.plist carries the speech-recognition usage string.
import AVFoundation
import Foundation
import Speech

func fail(_ message: String, _ code: Int32) -> Never {
    FileHandle.standardError.write("\(message)\n".data(using: .utf8)!)
    exit(code)
}

let auth = DispatchSemaphore(value: 0)
var authorised = false
SFSpeechRecognizer.requestAuthorization { status in
    authorised = status == .authorized
    auth.signal()
}
auth.wait()
guard authorised, let rec = SFSpeechRecognizer(locale: Locale(identifier: "en-US")), rec.isAvailable else {
    fail("speech recognition unavailable or not authorised", 2)
}

if CommandLine.arguments.count > 1 && CommandLine.arguments[1] == "--stream" {
    let req = SFSpeechAudioBufferRecognitionRequest()
    req.requiresOnDeviceRecognition = rec.supportsOnDeviceRecognition  // never leaves the machine when supported
    req.shouldReportPartialResults = true
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
    let emit = { (text: String, final: Bool) in
        let line = try! JSONSerialization.data(withJSONObject: ["text": text, "final": final])
        FileHandle.standardOutput.write(line + "\n".data(using: .utf8)!)
    }
    let task = rec.recognitionTask(with: req) { result, error in
        if let r = result {
            emit(r.bestTranscription.formattedString, r.isFinal)
            if r.isFinal { exit(0) }
        }
        if let e = error { fail("\(e)", 3) }
    }
    _ = task
    DispatchQueue.global().async {
        var carry = Data()
        while true {
            let data = FileHandle.standardInput.availableData  // blocks; empty at EOF
            if data.isEmpty { req.endAudio(); return }
            carry.append(data)
            let frames = carry.count / 2
            if frames == 0 { continue }
            let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames))!
            buf.frameLength = AVAudioFrameCount(frames)
            carry.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
                let samples = raw.bindMemory(to: Int16.self)
                for i in 0..<frames { buf.floatChannelData![0][i] = Float(Int16(littleEndian: samples[i])) / 32768 }
            }
            carry = carry.count % 2 == 1 ? carry.suffix(1) : Data()
            req.append(buf)
        }
    }
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 120))
    fail("timed out", 4)
}

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let req = SFSpeechURLRecognitionRequest(url: url)
req.requiresOnDeviceRecognition = rec.supportsOnDeviceRecognition  // never leaves the machine when supported
req.shouldReportPartialResults = false
rec.recognitionTask(with: req) { result, error in
    if let r = result, r.isFinal {
        print(r.bestTranscription.formattedString)
        exit(0)
    }
    if let e = error {
        fail("\(e)", 3)
    }
}
RunLoop.main.run(until: Date(timeIntervalSinceNow: 30))
exit(4)
