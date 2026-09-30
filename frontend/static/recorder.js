// Microphone capture -> 16 kHz mono 16-bit WAV (a format the on-device recogniser reads directly).
// Browsers' MediaRecorder produces WebM/Opus, which the Apple Speech framework cannot open, so we keep raw PCM.

export class Recorder {
  constructor(onLevel) {
    this.onLevel = onLevel;
    this.chunks = [];
    this.ctx = null;
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    this.ctx = new AudioContext();
    this.rate = this.ctx.sampleRate;
    const src = this.ctx.createMediaStreamSource(this.stream);
    // ScriptProcessor is deprecated but universally available and needs no extra module file.
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.chunks = [];
    this.node.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(data));
      let sum = 0;
      for (let i = 0; i < data.length; i += 16) sum += data[i] * data[i];
      this.onLevel?.(Math.min(1, Math.sqrt(sum / (data.length / 16)) * 4));
    };
    src.connect(this.node);
    this.node.connect(this.ctx.destination);
    this.startedAt = performance.now();
  }

  async stop() {
    const seconds = (performance.now() - this.startedAt) / 1000;
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close();
    this.onLevel?.(0);
    const pcm = downsample(concat(this.chunks), this.rate, 16000);
    return { wav: encodeWav(pcm, 16000), seconds };
  }
}

function concat(chunks) {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

function downsample(buf, from, to) {
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

function encodeWav(samples, rate) {
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
  return new Blob([buf], { type: "audio/wav" });
}
