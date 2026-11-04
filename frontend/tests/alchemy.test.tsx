import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AlchemyResults, AlchemyScreen } from "@/components/AlchemyScreen";
import {
  ALCHEMY_RULES,
  DEMO_PROMPT,
  describeGoal,
  formatCents,
  formatHz,
  formatMultiple,
  formatTarget,
  type AlchemyResult,
  type Variant,
} from "@/lib/alchemy";
import { installAudioStub, jsonResponse, recipe } from "./helpers";

let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => search,
}));

const variant = (label: string, patch: Partial<Variant> = {}): Variant => ({
  label,
  recipe,
  target_brightness_hz: 4603.8,
  brightness_hz: 4607.7,
  brightness_change: 1.4812,
  estimated_pitch_hz: 349,
  pitch_shift_cents: 1.26,
  pitch_preserved: true,
  audio: "data:audio/wav;base64,AAAA",
  spectrogram: "data:image/png;base64,AAAA",
  ...patch,
});

const result = (variants: Variant[], note: string | null = null): AlchemyResult => ({
  goal: { direction: "brighter", atmosphere: true, preserve_pitch_requested: true, preserve_pitch: true },
  note,
  base_brightness_hz: 3683,
  base_pitch_hz: 349.07,
  renders_tested: 90,
  pitch_tolerance_cents: 25,
  variants,
});

beforeEach(() => {
  installAudioStub();
  search = new URLSearchParams();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const showResults = (value: AlchemyResult) =>
  render(<AlchemyResults result={value} startingUrl="/start.wav" filenameStem="run-alchemy" />);

describe("formatting", () => {
  it("shows brightness as a multiple", () => {
    expect(formatMultiple(1.4812)).toBe("×1.48");
    expect(formatMultiple(0.5007)).toBe("×0.50");
  });

  it.each([0.5, 1, 1.25, 2])("never shows %s as a percentage", (value) => {
    expect(formatMultiple(value)).not.toContain("%");
  });

  it("shows cents and Hz", () => {
    // Shifts below the estimator's resolution of about 10 cents aren't reported as exact.
    expect(formatCents(1.26)).toBe("under 10 cents");
    expect(formatCents(0)).toBe("under 10 cents");
    expect(formatCents(9.2)).toBe("under 10 cents");
    expect(formatCents(10)).toBe("10 cents");
    expect(formatCents(24.6)).toBe("25 cents");
    expect(formatCents(null)).toBe("n/a");
    expect(formatHz(4607.7)).toBe("4608 Hz");
  });

  it("shows a target with its multiple, or says there is none", () => {
    expect(formatTarget({ target_brightness_hz: 4603.8 }, 3683)).toBe("4604 Hz (×1.25)");
    expect(formatTarget({ target_brightness_hz: null }, 3683)).toBe("None: atmosphere only");
  });

  it("describes the goal the rules read", () => {
    expect(describeGoal(result([]).goal)).toBe("brighter, more atmospheric, pitch kept");
    expect(
      describeGoal({ direction: null, atmosphere: true, preserve_pitch_requested: false, preserve_pitch: true }),
    ).toBe("more atmospheric, pitch kept");
  });
});

describe("variant cards", () => {
  it("shows nothing but the note with 0 variants", () => {
    const { container } = showResults(result([], "Only 0 of 3 variants could change this sound and keep its pitch."));
    expect(screen.queryAllByTestId("variant-card")).toHaveLength(0);
    expect(container.textContent).toContain("Only 0 of 3 variants");
    expect(container.textContent).toContain("No variation could be made");
  });

  it("shows 1 card and the note with 1 variant", () => {
    const { container } = showResults(result([variant("subtle")], "Only 1 of 3 variants could change this sound and keep its pitch."));
    expect(screen.getAllByTestId("variant-card")).toHaveLength(1);
    expect(container.textContent).toContain("Only 1 of 3 variants");
  });

  it("shows 3 cards and no note with 3 variants", () => {
    const { container } = showResults(result([variant("subtle"), variant("medium"), variant("bold")]));
    expect(screen.getAllByTestId("variant-card")).toHaveLength(3);
    expect(container.querySelector(".alchemy-note")).toBeNull();
    expect(container.textContent).not.toContain("No variation could be made");
  });

  it("shows every required measurement, in the required form", () => {
    const { container } = showResults(result([variant("subtle")]));
    const card = screen.getByTestId("variant-card");
    for (const text of [
      "subtle",
      "Starting sound",
      "This variation",
      "×1.48",
      "4608 Hz",
      "Target brightness",
      "4604 Hz (×1.25)",
      "under 10 cents",
      "Pitch kept",
      "Yes",
      "Recipe (JSON)",
      "Audio (WAV)",
    ]) {
      expect(card.textContent).toContain(text);
    }
    expect(container.querySelector("img")?.getAttribute("src")).toContain("data:image/png");
    expect(container.textContent).not.toContain("%");
    expect(card.querySelector('a[download="run-alchemy-subtle.wav"]')).toBeTruthy();
  });

  it("says when pitch wasn't kept, and when there's no brightness target", () => {
    showResults(result([variant("subtle", { pitch_preserved: false, target_brightness_hz: null })]));
    const card = screen.getByTestId("variant-card");
    expect(card.textContent).toContain("No");
    expect(card.textContent).toContain("None: atmosphere only");
  });
});

describe("Alchemy screen", () => {
  const entry = {
    index: 3,
    timestamp: null,
    mode: "hybrid",
    seed: 0,
    source: "model",
    planner_call: 1,
    hypothesis: null,
    rationale: null,
    expected_effect: null,
    recipe,
    loss: 0.04,
    components: null,
    failure: null,
    is_best: true,
    best_loss: 0.04,
  };
  const detail = {
    id: "a-hybrid-seed0",
    target: "a",
    mode: "hybrid",
    seed: 0,
    is_replay: true,
    status: "logged",
    budget: null,
    error: null,
    total: 2,
    skipped_lines: 0,
    entries: [{ ...entry, index: 0, loss: 0.5, recipe: { oscillator: "worse" } }, entry],
  };

  function mockFetch(alchemy: () => Response) {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/runs") return jsonResponse([{ id: "a-hybrid-seed0", target: "a", mode: "hybrid", seed: 0, entries: 2, skipped_lines: 0, best_loss: 0.04, status: "logged" }]);
      if (url.startsWith("/api/runs/")) return jsonResponse(detail);
      if (url === "/api/alchemy") return alchemy();
      return new Response(new ArrayBuffer(8));
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("states the rules, prefills the prompt, and has no stub banner", async () => {
    mockFetch(() => jsonResponse(result([])));
    const { container } = render(<AlchemyScreen />);
    expect(container.textContent).toContain(ALCHEMY_RULES);
    expect(ALCHEMY_RULES).toContain("no model call");
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(DEMO_PROMPT);
    expect(container.textContent).not.toMatch(/not (yet )?connected/i);
  });

  it("needs a run on direct arrival", async () => {
    mockFetch(() => jsonResponse(result([])));
    const { container } = render(<AlchemyScreen />);
    await screen.findByRole("option", { name: /AI \+ optimizer/ });
    expect((screen.getByRole("button", { name: "Generate variations" }) as HTMLButtonElement).disabled).toBe(true);
    expect(container.textContent).toContain("Choose a run to start from");
  });

  it("sends the best render's recipe and the prompt", async () => {
    search = new URLSearchParams("run=a-hybrid-seed0");
    const fetchMock = mockFetch(() => jsonResponse(result([variant("subtle")])));
    render(<AlchemyScreen />);
    await screen.findByText("Render 4");
    fireEvent.click(screen.getByRole("button", { name: "Generate variations" }));
    await screen.findByTestId("variant-card");
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/alchemy");
    expect(JSON.parse(call?.[1]?.body as string)).toEqual({ recipe, prompt: DEMO_PROMPT });
  });

  it("shows a refusal exactly as written", async () => {
    search = new URLSearchParams("run=a-hybrid-seed0");
    const message = "Alchemy can't do this yet: metallic. It can change brightness and atmosphere.";
    mockFetch(() => jsonResponse({ detail: { code: "alchemy_refused", message, fix: null } }, 422));
    render(<AlchemyScreen />);
    await screen.findByText("Render 4");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "more metallic" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate variations" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(message));
    expect(screen.queryAllByTestId("variant-card")).toHaveLength(0);
  });
});
