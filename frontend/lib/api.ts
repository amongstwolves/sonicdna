import type { AlchemyResult } from "./alchemy";
import type { Recipe, RunDetail, RunSummary } from "./runs";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly fix: string | null = null,
    public readonly code: string | null = null,
    public readonly status: number | null = null,
  ) {
    super(message);
  }
}

export interface Target {
  name: string;
  held_out: boolean;
  available: boolean;
  has_runs: boolean;
}

export type LiveMode = "hybrid" | "optimizer_only";

export interface Analysis {
  name: string;
  upload_id?: string;
  warnings: string[];
  descriptors: Record<string, number | null>;
  waveform: { min: number[]; max: number[] };
  spectrogram: string;
}

export interface Meta {
  public_mode?: boolean;
  loss_weights: Record<string, number>;
  recipe_bounds: Record<string, [number, number]>;
  upload_limits: {
    max_bytes: number;
    min_duration_s: number;
    max_duration_s: number;
    max_channels: number;
  };
}

export interface RenderResult {
  audio: string;
  spectrogram: string;
  loss: number | null;
  components: Record<string, number> | null;
  not_scored_reason: string | null;
}

const DEFAULT_MAX_UPLOAD_BYTES = 8 * 1024 * 1024;

/** Checked before sending, because the proxy stalls on a body over its own limit. */
export function oversizeError(size: number, maxBytes = DEFAULT_MAX_UPLOAD_BYTES): ApiError | null {
  if (size <= maxBytes) return null;
  return new ApiError(
    `That file is over the ${maxBytes / (1024 * 1024)} MB limit.`,
    "Trim it to 5 seconds or less and export again.",
    "file_too_large",
    413,
  );
}

const UNREACHABLE = new ApiError(
  "The SonicDNA API isn't responding.",
  "Try again in a minute. Running locally? Start it with: .venv/bin/uvicorn app.api:app --port 8000",
  "unreachable",
);

/** Turns any failed response into an ApiError with a message a person can act on. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = (await response.json())?.detail;
  } catch {
    return response.status >= 500 ? UNREACHABLE : new ApiError(`Request failed (${response.status}).`);
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const { message, fix, code } = detail as { message: string; fix?: string; code?: string };
    return new ApiError(message, fix ?? null, code ?? null, response.status);
  }
  if (response.status === 404) {
    return new ApiError("That wasn't found.", "Pick an item from the list.", "not_found", 404);
  }
  if (typeof detail === "string") return new ApiError(detail, null, null, response.status);
  return new ApiError(`Request failed (${response.status}).`, null, null, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw UNREACHABLE;
  }
  if (!response.ok) throw await errorFromResponse(response);
  return response.json();
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  targets: () => request<Target[]>("/api/targets"),
  runs: () => request<RunSummary[]>("/api/runs"),
  run: (id: string, after = -1, signal?: AbortSignal) =>
    request<RunDetail>(`/api/runs/${encodeURIComponent(id)}?after=${after}`, { signal }),
  startRun: (target: string, mode: LiveMode) =>
    request<{ id: string; status: string; budget: number }>("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, mode }),
    }),
  alchemy: (recipe: Recipe, prompt: string, signal?: AbortSignal) =>
    request<AlchemyResult>("/api/alchemy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe, prompt }),
      signal,
    }),
  analyzeTarget: (name: string) =>
    request<Analysis>(`/api/targets/${encodeURIComponent(name)}/analysis`),
  analyzeUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Analysis>("/api/analyze", { method: "POST", body: form });
  },
  render: (recipe: Recipe, target: string, signal?: AbortSignal) =>
    request<RenderResult>("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe, target }),
      signal,
    }),
};

export const urls = {
  targetAudio: (name: string) => `/api/targets/${encodeURIComponent(name)}/audio`,
  targetSpectrogram: (name: string) => `/api/targets/${encodeURIComponent(name)}/spectrogram`,
  entryAudio: (run: string, index: number) =>
    `/api/runs/${encodeURIComponent(run)}/entries/${index}/audio`,
  entrySpectrogram: (run: string, index: number) =>
    `/api/runs/${encodeURIComponent(run)}/entries/${index}/spectrogram`,
};
