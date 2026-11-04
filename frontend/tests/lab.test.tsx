import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LabScreen } from "@/components/LabScreen";
import { installAudioStub, jsonResponse, recipe } from "./helpers";

let search = new URLSearchParams();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => search,
}));

const entry = (index: number, patch = {}) => ({
  index,
  timestamp: new Date().toISOString(),
  mode: "hybrid",
  seed: 0,
  source: "model",
  planner_call: 1,
  hypothesis: `Mock hypothesis ${index}`,
  rationale: null,
  expected_effect: null,
  recipe,
  loss: 0.5 - index / 100,
  components: null,
  failure: null,
  is_best: true,
  best_loss: 0.5 - index / 100,
  ...patch,
});

const detail = (patch = {}) => ({
  id: "warm_pad-hybrid-seed1793808000000",
  target: "warm_pad",
  mode: "hybrid",
  seed: 1793808000000,
  is_replay: false,
  status: "running",
  budget: 20,
  error: null,
  total: 0,
  skipped_lines: 0,
  entries: [] as ReturnType<typeof entry>[],
  ...patch,
});

const targets = [
  { name: "warm_pad", held_out: false, available: true, has_runs: true },
  { name: "echo_stack", held_out: true, available: true, has_runs: false },
];

type Handler = (url: string, init?: RequestInit) => Response | undefined;

function mockFetch(handler: Handler) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const handled = handler(url, init);
    if (handled) return handled;
    if (url === "/api/runs") return jsonResponse([]);
    if (url === "/api/targets") return jsonResponse(targets);
    if (url === "/api/meta") return jsonResponse({
        loss_weights: {},
        recipe_bounds: {
          "filter.cutoff_hz": [20, 20000],
          "envelope.attack_s": [0.001, 2],
          "envelope.decay_s": [0.001, 2],
          "envelope.sustain": [0, 1],
          "distortion.drive": [0, 1],
        },
        upload_limits: {},
      });
    return new Response(new ArrayBuffer(8));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const label = () => document.querySelector(".replay-label")?.textContent ?? "";

beforeEach(() => {
  installAudioStub();
  replace.mockClear();
  search = new URLSearchParams();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("run labelling on screen", () => {
  it("labels a replay as a replay, with replay controls and paced reveal", async () => {
    search = new URLSearchParams("run=a-hybrid-seed0");
    mockFetch((url) =>
      url.startsWith("/api/runs/")
        ? jsonResponse(detail({ id: "a-hybrid-seed0", seed: 0, is_replay: true, status: "logged", budget: null, entries: [entry(0)] }))
        : undefined,
    );
    render(<LabScreen />);
    await screen.findByRole("button", { name: /Play replay/ });
    expect(label()).toContain("Replay of a logged run.");
    expect(document.querySelectorAll(".card")).toHaveLength(0);
    expect(screen.getByText("0 of 1 renders")).toBeTruthy();
  });

  it("shows a running live run with no replay wording or controls, and reveals entries at once", async () => {
    search = new URLSearchParams("run=warm_pad-hybrid-seed1793808000000");
    mockFetch((url) => (url.startsWith("/api/runs/") ? jsonResponse(detail({ entries: [entry(0)] })) : undefined));
    render(<LabScreen />);
    await waitFor(() => expect(label()).toContain("Live run in progress."));
    expect(document.querySelector(".replay-bar")?.textContent).not.toMatch(/replay/i);
    expect(screen.queryByRole("button", { name: /Play replay/ })).toBeNull();
    expect(document.querySelectorAll(".card")).toHaveLength(1);
    expect(label()).toContain("descriptors and a spectrogram image");
    expect(document.body.textContent).toContain("Mock hypothesis 0");
  });

  it("says a live run finished", async () => {
    search = new URLSearchParams("run=warm_pad-hybrid-seed1793808000000");
    mockFetch((url) => (url.startsWith("/api/runs/") ? jsonResponse(detail({ status: "finished", entries: url.endsWith("after=-1") ? [entry(0), entry(1)] : [] })) : undefined));
    render(<LabScreen />);
    await waitFor(() => expect(label()).toContain("Finished live run."));
    expect(label()).toContain("2 renders");
    expect(label()).not.toMatch(/replay/i);
    expect(screen.getByRole("link", { name: /best to Alchemy/ }).getAttribute("href")).toContain("/alchemy?run=");
  });

  it("shows a failed run and its error", async () => {
    search = new URLSearchParams("run=warm_pad-hybrid-seed1793808000000");
    mockFetch((url) => (url.startsWith("/api/runs/") ? jsonResponse(detail({ status: "failed", error: "RuntimeError" })) : undefined));
    render(<LabScreen />);
    await waitFor(() => expect(label()).toContain("This live run failed."));
    expect(label()).toContain("RuntimeError");
    expect(document.body.textContent).not.toContain("Waiting for");
  });
});

describe("polling and waiting", () => {
  it("shows the waiting state with real elapsed time, then reveals what arrives", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    // Reading a Response body needs real event-loop turns between fake-clock advances.
    const advance = async (ms: number) => {
      for (let spent = 0; spent <= ms; spent += 100) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(spent === 0 ? 0 : 100);
          for (let turn = 0; turn < 10; turn += 1) await new Promise((done) => setImmediate(done));
        });
      }
    };
    vi.setSystemTime(1793808000000);
    search = new URLSearchParams("run=warm_pad-hybrid-seed1793808000000");
    let ready = false;
    const fetchMock = mockFetch((url) => {
      if (!url.startsWith("/api/runs/") || url.includes("/entries/")) return undefined;
      return jsonResponse(detail({ entries: ready && url.endsWith("after=-1") ? [entry(0)] : [] }));
    });
    render(<LabScreen />);
    await advance(100);
    expect(document.querySelector(".live-status")?.textContent).toContain("Waiting for the model");

    await advance(12000);
    const status = document.querySelector(".live-status")?.textContent ?? "";
    expect(status).toContain("12 s since the run started");
    expect(status).toContain("about 30 s");
    expect(document.querySelectorAll(".card")).toHaveLength(0);

    ready = true;
    await advance(1100);
    expect(document.querySelectorAll(".card")).toHaveLength(1);
    expect(document.querySelector(".live-status")?.textContent).toContain("Receiving renders");

    const polls = fetchMock.mock.calls.map(([url]) => url).filter((url) => url.includes("after="));
    expect(polls.at(-1)).toContain("after=-1");
    await advance(1100);
    const after = fetchMock.mock.calls.map(([url]) => url).filter((url) => url.includes("after="));
    expect(after.at(-1)).toContain("after=0");
  });
});

describe("starting a live run", () => {
  const open = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Start live run" }));
    return screen.findByRole("region", { name: "Start a live run" });
  };

  it("never starts from a link, and needs a mode choosing", async () => {
    search = new URLSearchParams("new=warm_pad");
    const fetchMock = mockFetch(() => undefined);
    render(<LabScreen />);
    const start = await screen.findByRole("button", { name: "Choose a mode to start" });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === "/api/targets")).toBe(true));
    expect((start as HTMLButtonElement).disabled).toBe(true);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("shows the disclosure at the point of starting a hybrid run, and posts it (mocked)", async () => {
    search = new URLSearchParams("new=warm_pad");
    const fetchMock = mockFetch((url, init) =>
      url === "/api/runs" && init?.method === "POST" ? jsonResponse({ id: "warm_pad-hybrid-seed1", status: "running", budget: 20 }, 202) : undefined,
    );
    render(<LabScreen />);
    expect(document.querySelector(".start-disclosure")).toBeNull();
    fireEvent.click(await screen.findByRole("radio", { name: "AI + optimizer" }));
    expect(document.querySelector(".start-disclosure")?.textContent).toContain(
      "descriptors and a spectrogram image to Meta's model API",
    );
    fireEvent.click(screen.getByRole("button", { name: "Start live AI run" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/lab?run=warm_pad-hybrid-seed1"));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ target: "warm_pad", mode: "hybrid" });
  });

  it("uses an upload id as the target, without naming it", async () => {
    search = new URLSearchParams("new=upload_0123456789ab");
    const fetchMock = mockFetch((url, init) =>
      url === "/api/runs" && init?.method === "POST" ? jsonResponse({ id: "x-optimizer_only-seed1", status: "running", budget: 20 }, 202) : undefined,
    );
    render(<LabScreen />);
    fireEvent.click(await screen.findByRole("radio", { name: "Optimizer only" }));
    expect(document.querySelector(".start-disclosure")).toBeNull();
    expect(document.querySelector(".start-panel")?.textContent).toContain("Uploaded sound");
    fireEvent.click(screen.getByRole("button", { name: "Start optimizer-only run" }));
    await waitFor(() => expect(replace).toHaveBeenCalled());
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ target: "upload_0123456789ab", mode: "optimizer_only" });
  });

  it.each([
    ["no_api_key", 503, "Live AI runs need a Meta API key on the server.", "Set META_API_KEY in .env, or replay a logged run."],
    ["run_in_progress", 409, "A live run is already going.", "Wait for it."],
    ["no_pitch", 422, "No clear pitch was found in this sound, so it can't be reconstructed.", "Use an isolated, tonal sound."],
  ])("shows %s with its fix", async (code, status, message, fix) => {
    search = new URLSearchParams("new=warm_pad");
    mockFetch((url, init) => (url === "/api/runs" && init?.method === "POST" ? jsonResponse({ detail: { code, message, fix } }, status) : undefined));
    render(<LabScreen />);
    fireEvent.click(await screen.findByRole("radio", { name: "Optimizer only" }));
    fireEvent.click(screen.getByRole("button", { name: "Start optimizer-only run" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(message);
    expect(alert.textContent).toContain(fix);
    expect(replace).not.toHaveBeenCalled();
  });

  it("links to the run already going", async () => {
    search = new URLSearchParams("new=warm_pad");
    mockFetch((url, init) => {
      if (url !== "/api/runs") return undefined;
      if (init?.method === "POST") return jsonResponse({ detail: { code: "run_in_progress", message: "A live run is already going.", fix: "Wait for it." } }, 409);
      return jsonResponse([{ id: "busy-optimizer_only-seed1793808000000", target: "busy", mode: "optimizer_only", seed: 1793808000000, entries: 0, skipped_lines: 0, best_loss: null, status: "running" }]);
    });
    render(<LabScreen />);
    fireEvent.click(await screen.findByRole("radio", { name: "Optimizer only" }));
    fireEvent.click(screen.getByRole("button", { name: "Start optimizer-only run" }));
    const link = await screen.findByRole("link", { name: "Open the run that is going" });
    expect(link.getAttribute("href")).toBe("/lab?run=busy-optimizer_only-seed1793808000000");
  });

  it("opens the panel from the bar on a loaded run", async () => {
    search = new URLSearchParams("run=a-hybrid-seed0");
    mockFetch((url) => (url.startsWith("/api/runs/") ? jsonResponse(detail({ id: "a-hybrid-seed0", seed: 0, is_replay: true, status: "logged", entries: [] })) : undefined));
    render(<LabScreen />);
    await open();
    expect(screen.getByRole("radio", { name: "AI + optimizer" })).toBeTruthy();
  });
});
