import {
  FRAME_SAMPLES,
  WORKLET_SOURCE,
  downsample,
  floatToPcm16,
  formatLatency,
  micAvailability,
  parseVoiceEvent,
  pcm16ToFloat,
} from "./voice";

describe("PCM-Umwandlung", () => {
  it("wandelt Float in PCM16 und zurück, begrenzt Übersteuerung", () => {
    const pcm = floatToPcm16(new Float32Array([0, 0.5, -0.5, 1.5, -1.5]));
    expect(Array.from(pcm.slice(0, 3))).toEqual([0, 16383, -16384]);
    expect(pcm[3]).toBe(32767);
    expect(pcm[4]).toBe(-32768);
    const back = pcm16ToFloat(pcm);
    expect(back[1]).toBeCloseTo(0.5, 3);
    expect(back[4]).toBe(-1);
  });
});

describe("downsample", () => {
  it("lässt 16 kHz unverändert", () => {
    const input = new Float32Array([0.1, 0.2, 0.3]);
    expect(downsample(input, 16000)).toBe(input);
  });

  it("mittelt von 48 kHz auf 16 kHz (Faktor 3)", () => {
    const out = downsample(new Float32Array([0.3, 0.3, 0.3, 0.6, 0.6, 0.6]), 48000);
    expect(Array.from(out).map((v) => Number(v.toFixed(2)))).toEqual([0.3, 0.6]);
  });

  it("behandelt 44,1 kHz mit nicht ganzzahligem Faktor ohne NaN", () => {
    const out = downsample(new Float32Array(4410).fill(0.5), 44100);
    expect(out.length).toBe(1600);
    expect(out.every((v) => Math.abs(v - 0.5) < 1e-6)).toBe(true);
  });
});

describe("parseVoiceEvent", () => {
  it("erkennt bekannte Ereignisse, ignoriert unbekannte und kaputte", () => {
    expect(parseVoiceEvent('{"type":"voice.transcript","text":"Hallo"}')).toEqual({
      type: "voice.transcript",
      text: "Hallo",
    });
    expect(parseVoiceEvent('{"type":"tts.end","expects_reply":true}')).toMatchObject({ expects_reply: true });
    expect(parseVoiceEvent('{"type":"gibts.nicht"}')).toBeNull();
    expect(parseVoiceEvent("kein json")).toBeNull();
    expect(parseVoiceEvent("42")).toBeNull();
  });
});

describe("micAvailability", () => {
  it("erklärt, warum das Mikrofon nicht geht", () => {
    expect(micAvailability(false, true)).toContain("HTTPS");
    expect(micAvailability(true, false)).toContain("Browser");
    expect(micAvailability(true, true)).toBeNull();
  });
});

describe("formatLatency", () => {
  it("zeigt Zeit bis zum ersten Ton, Erkennung und Fast-Path", () => {
    const text = formatLatency({
      type: "voice.latency",
      pause_ms: 1500,
      stt_ms: 394,
      first_token_ms: 413,
      first_audio_ms: 525,
      total_ms: 525,
      via_fastpath: true,
    });
    expect(text).toBe("Antwort nach 0,5 s · Erkennung 394 ms · erstes Wort 413 ms · ohne LLM");
  });

  it("kommt ohne erstes Wort und ohne Audio aus", () => {
    const text = formatLatency({
      type: "voice.latency",
      pause_ms: 1500,
      stt_ms: 800,
      first_token_ms: null,
      first_audio_ms: null,
      total_ms: 2100,
      via_fastpath: false,
    });
    expect(text).toBe("Antwort nach 2,1 s · Erkennung 800 ms");
  });
});

describe("Worklet", () => {
  it("sendet 512er-Blöcke und kennt die Zielrate", () => {
    expect(FRAME_SAMPLES).toBe(512);
    expect(WORKLET_SOURCE).toContain("registerProcessor('cat-capture'");
    expect(WORKLET_SOURCE).toContain("sampleRate / 16000");
    expect(WORKLET_SOURCE).toContain("=== 512");
  });
});
