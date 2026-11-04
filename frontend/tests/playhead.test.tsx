import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ABPlayer } from "@/components/ABPlayer";
import { PlayButton } from "@/components/PlayButton";
import { Playhead } from "@/components/Playhead";
import { Spectrogram } from "@/components/Spectrogram";
import { clearNowPlaying, playheadFraction, setNowPlaying } from "@/lib/playhead";
import { installAudioStub } from "./helpers";

let frames: FrameRequestCallback[] = [];

function nextFrame() {
  const pending = frames;
  frames = [];
  act(() => pending.forEach((callback) => callback(0)));
}

beforeEach(() => {
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback));
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
});

afterEach(() => {
  cleanup();
  clearNowPlaying();
  vi.unstubAllGlobals();
});

describe("playheadFraction", () => {
  it("reports only the sound that is playing, kept between 0 and 1", () => {
    expect(playheadFraction("/a")).toBeNull();
    setNowPlaying("/a", () => 0.25);
    expect(playheadFraction("/a")).toBe(0.25);
    expect(playheadFraction("/b")).toBeNull();
    expect(playheadFraction(null)).toBeNull();
    setNowPlaying("/a", () => 1.5);
    expect(playheadFraction("/a")).toBe(1);
  });

  it("is null until the duration is known", () => {
    setNowPlaying("/a", () => NaN);
    expect(playheadFraction("/a")).toBeNull();
  });

  it("clearing another sound leaves the current one playing", () => {
    setNowPlaying("/a", () => 0.5);
    clearNowPlaying("/b");
    expect(playheadFraction("/a")).toBe(0.5);
    clearNowPlaying("/a");
    expect(playheadFraction("/a")).toBeNull();
  });
});

describe("Playhead", () => {
  it("is hidden when idle, follows the sound, then hides again", () => {
    render(<Playhead audioUrl="/a" />);
    const line = screen.getByTestId("playhead");
    nextFrame();
    expect(line.hidden).toBe(true);
    setNowPlaying("/a", () => 0.5);
    nextFrame();
    expect(line.hidden).toBe(false);
    expect(line.style.getPropertyValue("--position")).toBe("0.5");
    clearNowPlaying("/a");
    nextFrame();
    expect(line.hidden).toBe(true);
  });

  it("stays hidden on a picture of a different sound", () => {
    render(<Playhead audioUrl="/b" />);
    setNowPlaying("/a", () => 0.5);
    nextFrame();
    expect(screen.getByTestId("playhead").hidden).toBe(true);
  });
});

describe("Spectrogram", () => {
  it("has no playhead when there is no picture", () => {
    render(<Spectrogram src={null} title="Empty" audioUrl="/a" />);
    expect(screen.queryByTestId("playhead")).toBeNull();
  });
});

describe("ABPlayer", () => {
  beforeEach(() => {
    installAudioStub();
    vi.stubGlobal("fetch", async () => new Response(new ArrayBuffer(8)));
  });

  async function ready() {
    const [a, b, stop] = screen.getAllByRole("button") as HTMLButtonElement[];
    await waitFor(() => expect(a.disabled || b.disabled).toBe(false));
    return { a, b, stop };
  }

  it("moves the playhead to the side being heard, and clears it on stop", async () => {
    render(<ABPlayer referenceUrl="/ref" renderUrl="/render" renderLabel="Render" />);
    const { a, b, stop } = await ready();
    fireEvent.click(a);
    await waitFor(() => expect(playheadFraction("/ref")).not.toBeNull());
    expect(playheadFraction("/render")).toBeNull();
    fireEvent.click(b);
    await waitFor(() => expect(playheadFraction("/render")).not.toBeNull());
    expect(playheadFraction("/ref")).toBeNull();
    fireEvent.click(stop);
    expect(playheadFraction("/render")).toBeNull();
  });

  it("clears the playhead when it leaves the page", async () => {
    const { unmount } = render(<ABPlayer referenceUrl="/ref" renderUrl="/render" renderLabel="Render" />);
    const { a } = await ready();
    fireEvent.click(a);
    await waitFor(() => expect(playheadFraction("/ref")).not.toBeNull());
    unmount();
    expect(playheadFraction("/ref")).toBeNull();
  });
});

describe("PlayButton", () => {
  class FakeAudio {
    currentTime = 0;
    duration = 2;
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    async play() {}
    pause() {}
  }

  it("drives the playhead from the audio position and clears it when it ends", async () => {
    let audio: FakeAudio | null = null;
    vi.stubGlobal(
      "Audio",
      class extends FakeAudio {
        constructor() {
          super();
          audio = this;
        }
      },
    );
    render(<PlayButton src="/ref" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(playheadFraction("/ref")).toBe(0));
    audio!.currentTime = 1;
    expect(playheadFraction("/ref")).toBe(0.5);
    act(() => audio!.onended?.());
    expect(playheadFraction("/ref")).toBeNull();
  });
});
