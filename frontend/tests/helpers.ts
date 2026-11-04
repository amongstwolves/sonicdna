import { vi } from "vitest";

export const recipe = {
  schema_version: "1.0",
  sample_rate: 44100,
  duration_s: 2,
  oscillator: { type: "saw", frequency_hz: 220, gain: 0.7 },
  oscillator_2: null,
  envelope: { attack_s: 0.02, decay_s: 0.2, sustain: 0.5, release_s: 0.2 },
  filter: { type: "lowpass", cutoff_hz: 2000 },
  distortion: null,
  delay: null,
};

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/** jsdom has no Web Audio. Enough for the A/B player to load and stay idle. */
export function installAudioStub() {
  vi.stubGlobal(
    "AudioContext",
    class {
      currentTime = 0;
      destination = {};
      async decodeAudioData() {
        return { duration: 1 };
      }
      async resume() {}
      async close() {}
      createBufferSource() {
        return { connect() {}, disconnect() {}, start() {}, stop() {} };
      }
    },
  );
}
