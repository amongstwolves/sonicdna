# SonicDNA build plan

Deadline: **Wed Nov 4, 2026, 9:00 PM ET** (reconfirm in official rules). Target submit: 8:00 PM ET.
Status values: Not started · In progress · Done · Blocked · Cut

## Go/no-go

**Wed ~1:00 AM ET:** AI + optimizer must beat optimizer-only on ≥2 of 3 held-out targets (20-render budget).
If not, keep building, but pitch the AI as *directing and explaining* the search, not outperforming it.

## Held-out rule (written before the held-out run, Nov 4 ~11:15 AM ET)

Targets: glass_pluck, fuzz_lead, echo_stack. Budget 20 renders, seeds 0-2, one run only, no tuning afterwards.
Settings frozen: muse-spark-1.3, default reasoning effort, 3 optimizer renders between planner calls.
A target is an AI win only if the hybrid's median best normalized loss is lower than **both** optimizer-only methods' (`tpe` and `restart_local`), because dev runs didn't clearly separate them.
Pass: AI wins at least 2 of 3. Otherwise stop tuning, report it, and move on to Alchemy and integration.

## Pre-code fixes

| # | Issue | Fix | Status |
|---|---|---|---|
| 1 | Demo line ("metallic, preserve the rhythmic pulse") doesn't match the synth: no LFO, no FM/ring mod | Alchemy v1 = brightness, preserve pitch. Add tremolo LFO only if time allows | Not started |
| 2 | AI's role vs baseline undefined | Model = structural choices; optimizer = continuous tuning. Compare hybrid vs optimizer-only vs random | Not started |
| 3 | Model input mode | Spectrogram PNG + descriptors to the model; pitch from f0 estimate | Not started |
| 4 | Open decisions in SPEC §15 | Locked in CLAUDE.md. Muse API access and one structured-output call confirmed Nov 4 | Done |

## Schedule

| Day | Window (ET) | Goal | Checkpoint | Status | Result notes |
|---|---|---|---|---|---|
| Tue Nov 3 | 4:30–6:00 PM | API access confirmed, decisions locked, repo scaffolded | One valid structured response from Muse | Done | Nov 4: muse-spark-1.3 returned schema- and bounds-valid JSON with spectrogram PNG + strict schema (HTTP 200, 28.3 s, 3,366 output tokens, 3,003 of them reasoning). Its structure guess was wrong on the known-answer tone: added a second oscillator and called a decaying tone sustained. |
| Tue Nov 3 | 6:00–10:00 PM | Renderer, features, loss, target generator, random-search baseline | A loss curve from the command line | Done | Nov 4: `scripts/loss_curve.py` on 9 dev targets, random search, budget 20, seed 0: median best loss 0.050 (ground-truth recipe at estimated pitch: 0.001-0.013). Pitch estimate tested within 25 cents on all 12 targets. Descriptors for the planner now include level over time (planner not built yet). |
| Tue–Wed | 10:00 PM–1:00 AM | Planner + optimizer loop, experiment logging, 3-target comparison | Hybrid beats optimizer-only on ≥2 of 3 targets (go/no-go) | Done | **No-go, Nov 4 11:19 AM ET.** Median best normalized loss (hybrid / tpe / restart_local): glass_pluck 0.2977 / 0.1950 / 0.1916, fuzz_lead 0.0313 / 0.0241 / 0.0370, echo_stack 0.0444 / 0.0732 / 0.0454. AI wins 1 of 3 under the written rule (2 of 3 against restart_local alone, 1 of 3 against tpe alone). 27 calls, no fallbacks. No further tuning; pitch the AI as directing and explaining the search. |
| Wed Nov 4 | 9:00 AM–2:00 PM | UI: upload, spectrograms, timeline, score chart, A/B, 3 sliders | End-to-end run in the browser | Done | Nov 4: real AI run on warm_pad in the browser: 20 renders (12 model, 8 optimizer), 3 planner calls, no fallback, best normalized loss 0.012, then sent to Alchemy. Audio not checked by ear through the UI. |
| Wed Nov 4 | 2:00–4:00 PM | One Alchemy transform, JSON export | One distinct variant | Done | Nov 4: rule-based brightness and atmosphere, no model call. On a real live run: ×1.21, ×1.46, ×2.02 brightness, pitch shift under the estimator's resolution of about 10 cents. JSON and WAV export buttons exist but clicking them is untested. |
| Wed Nov 4 | 4:00–6:00 PM | Deploy, final comparison chart | Public link works | In progress | Chart done (`docs/heldout_comparison.svg`). Clean-copy setup tested. Render chosen; Docker image tested locally under free and Starter limits, in public mode with no API key. Not deployed yet. |
| Wed Nov 4 | 6:00–8:00 PM | Record video, write submission | Submitted by 8:00 PM | Not started | |

## Scope cuts (vs SPEC.md)

| Area | Spec as written | Cut to | Status |
|---|---|---|---|
| Evaluation | Median over held-out set, human A/B, five measures | 3 held-out synthetic targets, 20-render budget, one chart, no human A/B | Not started |
| Stack | Next.js + FastAPI (two services) | FastAPI serving one static page; host chosen early | Not started |
| Export | WAV + JSON | JSON required; WAV optional | Not started |

## Submission checklist

- [ ] Working public link
- [ ] Repository + architecture explanation + setup instructions
- [ ] 2–3 minute video (script in SPEC §10, updated for the brightness Alchemy demo)
- [x] Disclosure of what the Meta model actually does vs the optimizer (README)
- [x] Baseline comparison chart included (`docs/heldout_comparison.svg`)
