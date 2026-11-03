# SonicDNA — The Sound Invention Engine
Product & Technical Specification | Meta Global AI Developer Hackathon | v1.0 | November 3, 2026

> Copied from Albert's Google Doc "SonicDNA — Product & Technical Specification (Hackathon MVP)".
> Where this conflicts with the "Locked decisions" in `CLAUDE.md`, CLAUDE.md wins.

## 1. Executive Summary
SonicDNA is an autonomous sound-design laboratory that analyzes a reference sound, infers an editable synthesis/effects recipe, renders candidate reconstructions, measures the difference, and iteratively improves the recipe. Its Sonic Alchemy mode then transforms a recovered recipe toward a creative goal while preserving user-selected characteristics.

The product is not a generic audio-generation chatbot. Its defining output is an inspectable, repeatable sound recipe and an observable experiment history. A successful demonstration shows a reference sound, a sequence of tested hypotheses, measurable improvement, A/B playback, and an original transformed sound.

## 2. Problem and Opportunity
Sound designers routinely reconstruct tones by ear through trial-and-error manipulation of oscillators, envelopes, filters, distortion, modulation, and delays. AI audio generators can produce compelling waveforms, but frequently do not disclose a portable, editable signal chain. SonicDNA bridges that gap by treating sound design as an inverse problem with iterative experimentation.

Primary audience: electronic musicians, sound designers, indie game/audio developers, and experimental artists. Secondary audience: audio educators and researchers studying inverse synthesis.

## 3. Product Vision and Positioning
Promise: "Understand how a sound can be made. Reconstruct it. Then invent what comes next."

Key distinction: a user receives (1) an audio rendering, (2) a parameterized recipe, (3) measured comparison against the source, and (4) a trace of the experiments that led to the result. The inferred recipe is a plausible approximation, not proof of the original artist's actual equipment or production process.

## 4. Core User Journeys
### 4.1 Decode & Reconstruct
1. User uploads or records a short reference sound (target MVP: mono, 1–5 seconds, preferably isolated and tonal).
2. System validates format, duration, signal level, and suitability; shows waveform and spectrogram.
3. Analyzer extracts features: spectral envelope, pitch or fundamental estimate where feasible, amplitude envelope, spectral centroid, onset/decay, and optional temporal descriptors.
4. Muse-powered reasoning proposes a constrained sound recipe and a specific next experiment. DSP engine renders a candidate. Evaluator computes similarity metrics and stores results.
5. Optimizer proposes additional parameters until budget, improvement threshold, or user stop condition is reached.
6. UI displays best candidate, A/B playback, experiment history, parameter controls, and exportable WAV plus JSON recipe.

### 4.2 Sonic Alchemy
1. User starts from the best reconstructed recipe (or a starter preset).
2. User states a transformation goal, such as "more metallic while keeping the pulse" or "more atmospheric while retaining the pitch contour."
3. The agent translates the instruction into editable parameters and measurable constraints. It proposes and tests variations.
4. User compares alternatives, edits the chosen recipe, and exports the transformed result.

## 5. MVP Scope (Submission Deadline: November 4, 2026, 9:00 PM ET)
### 5.1 Must Have
- Browser interface with upload and playback for short mono WAV files; normalize/sample-rate-convert in preprocessing.
- Visualization: waveform, reference spectrogram, and rendered spectrogram.
- Constrained synthesizer/effects graph: one or two oscillators (sine/saw/square), ADSR envelope, low-pass filter, waveshaping distortion, and simple delay; no arbitrary plugin support.
- Deterministic audio feature extraction and composite loss scoring; log every tested parameter vector and score.
- Meta model calls for structured hypothesis/experiment proposals, with explicit JSON schema and tool-call boundaries.
- Autonomous search with bounded iteration budget and fallback numerical optimization; retain best result even if model proposals fail.
- A/B playback; per-iteration score history; manual adjustment of at least three recipe parameters.
- One Alchemy prompt family with constrained transformations (e.g., brightness, metallicity, ambience), plus WAV/JSON export if time permits.

### 5.2 Explicitly Out of Scope
Full music separation; polyphonic transcription; unrestricted instrument/pedal identification; exact original chain attribution; real-time live-input processing; commercial DAW plugins; arbitrary text-to-audio generation; model training; guaranteed reconstruction of environmental audio.

### 5.3 MVP Reference Set
Create 8–12 short target sounds using the same synthesis engine, with known ground-truth parameters. Add 2–3 independently recorded isolated sounds as stretch tests. The synthetic set enables exact reproducibility, controlled difficulty, and unbiased evaluation. Partition examples into development and unseen demo/test cases.

## 6. Functional Requirements
- FR-01 Upload validates file type, duration, channels, size, and clipping; shows actionable errors.
- FR-02 Analysis produces feature vectors and waveform/spectrogram plots in a consistent sample rate.
- FR-03 Recipe schema lists oscillator type/frequency/mix, envelope settings, filter cutoff/resonance, distortion drive, delay time/feedback/mix, and deterministic random seed (if relevant).
- FR-04 Renderer accepts a versioned recipe and outputs a WAV with fixed settings.
- FR-05 Planner outputs a hypothesis, candidate parameters or edits, reason, and expected impact as validated structured data.
- FR-06 Evaluator returns weighted loss components and an overall normalized comparison score; the score must not be described as perceptual fidelity without listening validation.
- FR-07 Experiment log captures recipe, timestamp/order, metrics, failure state, and best-so-far status.
- FR-08 Alchemy accepts an instruction plus preserve/modify constraints and generates multiple testable alternatives.
- FR-09 Export contains rendered audio, recipe JSON, engine/schema version, and optional measurement summary.

## 7. Architecture
- Frontend: React/Next.js and Web Audio API for browser playback, waveform/spectrogram UI, experiment timeline, and editable parameters. *(Overridden: single static page served by FastAPI — see CLAUDE.md.)*
- Backend: Python/FastAPI for file ingest, preprocessing, orchestration, recipe validation, DSP rendering, signal analysis, caching, and export.
- DSP: NumPy/SciPy or equivalent deterministic offline synthesizer and effects pipeline. Use one fixed sample rate and explicit loudness normalization to keep comparisons fair.
- Signal analysis: librosa/SciPy for STFT/log-magnitude spectra, envelopes, onset data, spectral centroid/flatness, and optional pitch estimation.
- AI planner: Meta Muse Spark through available API access for high-level hypothesis generation and choosing next experiments. Confirm account model access and capability before implementation; do not make raw-audio understanding a hard dependency.
- Optimizer: bounded coordinate search, Optuna, or differential evolution over valid parameter ranges. The AI directs broad structural changes while numerical search fine-tunes continuous parameters.
- Persistence: local files/SQLite or JSON for session data; no user account system required for demo.

### 7.1 Control Flow
Reference WAV → validation/resampling → feature extraction → agent hypothesis → schema validation → DSP render → feature comparison → experiment log → next proposal or numeric refinement → best recipe → Alchemy variants → export.

### 7.2 Planner Contract
Inputs: target descriptors, allowed nodes and parameter bounds, best recipe so far, recent experiments, remaining budget, and user constraints.
Outputs: {hypothesis, action, proposed_recipe_or_delta, expected_effect, rationale}. Reject out-of-range values and unsupported nodes; retry once, then use deterministic fallback.

### 7.3 Example Recipe JSON
See CLAUDE.md ("Recipe schema v1.0").

## 8. Objective Function and Evaluation
Normalize loudness and align signals before comparison. Composite loss can combine log-magnitude STFT distance, spectral centroid difference, amplitude-envelope distance, and optional fundamental-frequency deviation. Weight components by target category and publish their definitions.

Evaluate best-of-N reconstruction loss after a fixed rendering budget (e.g., 20 or 30 trials) against random search and a deterministic numerical baseline using the same engine and budget. Report median improvement across held-out samples, not a single cherry-picked example.

Measure: (1) relative loss reduction versus initial candidate, (2) head-to-head loss versus baselines, (3) successful render/export rate, (4) seconds and model calls per candidate, and (5) human A/B preference on a small blinded set if practical.

Important: numerical spectral similarity is not equivalent to perceived similarity. Label any UI percentage as a defined normalized metric, not "92% accurate" or "92% identical".

## 9. UX and Demo Design
- Screen A — Decode: upload zone, source waveform, spectrogram, extracted descriptors.
- Screen B — Experiment Lab: live timeline of agent hypothesis, changed parameters, rendered candidate, score breakdown, best-so-far chart, and A/B controls.
- Screen C — Alchemy: text transformation prompt, preservation toggles (pitch, rhythm, envelope), variation cards, recipe sliders, and export buttons.

Keep the UI legible to non-musicians: show one plain-English hypothesis at each step and provide a "why this change?" explanation. Present the experiment log as real events, not prerecorded or fabricated AI reasoning.

## 10. Live Demo Script (2–3 Minutes)
- 0:00–0:20 — Hook: "What if AI could figure out how a sound was made, then invent a new one?" Play a short original reference sound.
- 0:20–0:40 — Upload and inspect SonicDNA descriptors; display waveform/spectrum.
- 0:40–1:25 — Run 4–8 pre-budgeted experiments, showing structured hypotheses, measurable changes, and best-so-far scoring. Use a cache or a reliable precomputed fallback if compute latency is unpredictable, and clearly disclose it.
- 1:25–1:50 — A/B playback. Reveal the editable synthesis chain and adjust a parameter manually.
- 1:50–2:20 — Alchemy prompt *(updated: "brighter and more atmospheric, keep the pitch")*; generate and compare one variation.
- 2:20–2:40 — Export WAV and JSON. Close with the core value: an intelligible, repeatable sound recipe rather than an opaque output.

## 11. Build Plan and Priority
- P0 (immediate): confirm Muse API access; generate fixed reference sounds; implement deterministic renderer, file ingest, metrics, and experiment logging. Without a working render/evaluate loop, do not expand features.
- P1: implement model-driven bounded proposals plus baseline optimizer; build basic UI with timeline, score chart, A/B playback.
- P2: implement one constrained Alchemy transformation and JSON/WAV export; run held-out evaluation and record demo.

Cut order if behind: fancy visualization → extra effects → free-form Alchemy prompts → recorded environmental audio support. Never cut deterministic rendering, evaluation, and clear provenance of model contributions.

## 12. Risks and Mitigations
- Inverse problem ambiguity: multiple chains may sound alike. Report plausible approximations, not an authenticated original production chain.
- Unbounded search/latency: cap iterations, time and API calls; use caching and retain the current best candidate.
- Model hallucinated parameters: enforce JSON schema, known effect nodes, valid parameter bounds, and deterministic fallback.
- Metric gaming: test multiple features and evaluate with listening comparisons; avoid using one score as sole evidence.
- Audio diversity: begin with monophonic synthetic references and clearly mark unsupported categories.
- Licensing/copyright: use self-created or properly licensed reference sounds; do not imply unrestricted copying of commercial recordings.
- Data handling: prefer local processing or ephemeral sessions; disclose if uploaded audio is sent to an external model/API.

## 13. Success Criteria / Definition of Done
- One previously unseen synthetic reference reconstructs through at least five logged iterations with valid, reproducible recipes.
- Best-so-far loss demonstrably improves over the first candidate; results are accompanied by an honest comparison to at least one baseline.
- A reviewer can play reference and output, inspect the parameter changes, and manually edit at least three parameters.
- One Alchemy transformation produces a distinct rendered variant while tracking one preservation constraint.
- Submission includes a working link, repository/architecture explanation, short video, setup instructions, and disclosure of actual Meta model functionality.

## 14. Post-Hackathon Roadmap
- Phase 2: richer synthesis graph, additional effects, perceptual embeddings, controlled guitar/synth sound sets, multi-objective optimization, parameter uncertainty estimates, and batch evaluation.
- Phase 3: DAW integration via a portable preset interchange format; user-defined DSP graphs; real-time previews; community recipe sharing; provenance/license metadata.

## 15. Open Decisions
Resolved in CLAUDE.md "Locked decisions", except: confirm the available Muse model/version, quota, and supported input modes in the hackathon account.
