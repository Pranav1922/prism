// Push-to-talk microphone capture -> 16 kHz mono 16-bit PCM WAV, a format the on-device recogniser reads directly.
// (MediaRecorder produces WebM/Opus, which the Apple Speech framework cannot open, so we keep raw PCM.)
// The encoding functions are pure and exported so tests/test_microphone.py can check them outside a browser.

export const TARGET_RATE = 16000;
export const MAX_SECONDS = 15;          // auto-stop: push-to-talk is for short requests and corrections
export const MIN_SECONDS = 0.4;         // shorter than this is a click, not speech
export const SILENCE_PEAK = 0.02;       // below this peak amplitude nothing was captured (muted / wrong input)
export const START_TIMEOUT_MS = 3000;   // the microphone must be running by then, or we give up cleanly

/** Why the microphone cannot be used here, or null if it can. */
export function unsupportedReason(win = globalThis) {
  if (!win.isSecureContext) return "the page is not a secure context (open it via http://127.0.0.1, not a LAN address)";
  if (!win.navigator?.mediaDevices?.getUserMedia) return "this browser does not allow microphone access";
  if (!(win.AudioContext || win.webkitAudioContext)) return "this browser has no Web Audio support";
  return null;
}

export class Recorder {
  constructor(onLevel) {
    this.onLevel = onLevel;
    this.chunks = [];
    this.peak = 0;
    this.starting = null;
    this.cancelled = false;
  }

  /** Must be called from the user gesture (pointerdown / keydown): the AudioContext is created synchronously here,
   *  so browsers do not start it suspended. Resolves when capture is running. */
  start() {
    const Ctx = globalThis.AudioContext || globalThis.webkitAudioContext;
    this.ctx = new Ctx();
    this.rate = this.ctx.sampleRate;
    // never await resume(): without a real user gesture it can stay pending forever, and nothing may wait on it
    this.ctx.resume().catch(() => {});
    this.starting = (async () => {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      if (this.cancelled) return;  // released during the permission prompt
      const src = this.ctx.createMediaStreamSource(this.stream);
      // ScriptProcessor is deprecated but universally available and needs no extra module file. Its output is
      // silent (we never write to it); connecting it to the destination is what makes it run.
      this.node = this.ctx.createScriptProcessor(4096, 1, 1);
      this.node.onaudioprocess = (e) => {
        const data = e.inputBuffer.getChannelData(0);
        this.chunks.push(new Float32Array(data));
        let sum = 0, peak = 0;
        for (let i = 0; i < data.length; i += 8) { sum += data[i] * data[i]; peak = Math.max(peak, Math.abs(data[i])); }
        this.peak = Math.max(this.peak, peak);
        this.onLevel?.(Math.min(1, Math.sqrt(sum / (data.length / 8)) * 4));
      };
      src.connect(this.node);
      this.node.connect(this.ctx.destination);
      this.startedAt = performance.now();
    })();
    return this.starting;
  }

  /** Stops capture and releases the microphone in every case. Returns {wav, seconds, peak} or {error}. */
  async stop() {
    this.cancelled = true;
    let started;
    try {
      started = await Promise.race([this.starting.then(() => true),
        new Promise((r) => setTimeout(() => r(false), START_TIMEOUT_MS))]);
    } catch (e) { this.release(); return { error: e }; }
    if (!started) { this.release(); return { error: Object.assign(new Error("the microphone did not start"), { name: "StartTimeout" }) }; }
    if (this.ctx.state !== "running") { this.release(); return { error: Object.assign(new Error("audio capture was blocked by the browser"), { name: "Suspended" }) }; }
    const seconds = this.startedAt ? (performance.now() - this.startedAt) / 1000 : 0;
    this.release();
    const pcm = downsample(concat(this.chunks), this.rate, TARGET_RATE);
    return { wav: new Blob([encodeWav(pcm, TARGET_RATE)], { type: "audio/wav" }), seconds, peak: this.peak };
  }

  release() {
    try { this.node?.disconnect(); } catch { /* already disconnected */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    if (this.ctx && this.ctx.state !== "closed") this.ctx.close().catch(() => {});
    this.onLevel?.(0);
  }
}

export function concat(chunks) {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

/** Box-filter decimation (averaging) from `from` Hz to `to` Hz; adequate for speech recognition. */
export function downsample(buf, from, to) {
  if (!(from > 0) || !(to > 0)) throw new RangeError(`bad sample rates ${from} -> ${to}`);
  if (from === to) return buf;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(buf.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio), end = Math.min(buf.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = start; j < end; j++) s += buf[j];
    out[i] = s / Math.max(1, end - start);
  }
  return out;
}

/** RIFF/WAVE, PCM (format 1), mono, 16-bit little-endian. Returns an ArrayBuffer. */
export function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const x = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return buf;
}
