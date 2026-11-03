# SonicDNA build plan

Deadline: **Wed Nov 4, 2026, 9:00 PM ET** (reconfirm in official rules). Target submit: 8:00 PM ET.
Status values: Not started · In progress · Done · Blocked · Cut

## Go/no-go

**Wed ~1:00 AM ET:** AI + optimizer must beat optimizer-only on ≥2 of 3 held-out targets (20-render budget).
If not, keep building, but pitch the AI as *directing and explaining* the search, not outperforming it.

## Pre-code fixes

| # | Issue | Fix | Status |
|---|---|---|---|
| 1 | Demo line ("metallic, preserve the rhythmic pulse") doesn't match the synth: no LFO, no FM/ring mod | Alchemy v1 = brightness, preserve pitch. Add tremolo LFO only if time allows | Not started |
| 2 | AI's role vs baseline undefined | Model = structural choices; optimizer = continuous tuning. Compare hybrid vs optimizer-only vs random | Not started |
| 3 | Model input mode | Spectrogram PNG + descriptors to the model; pitch from f0 estimate | Not started |
| 4 | Open decisions in SPEC §15 | Locked in CLAUDE.md. Still to do: confirm Muse API access + one structured-output call | Not started |

## Schedule

| Day | Window (ET) | Goal | Checkpoint | Status | Result notes |
|---|---|---|---|---|---|
| Tue Nov 3 | 4:30–6:00 PM | API access confirmed, decisions locked, repo scaffolded | One valid structured response from Muse | Not started | |
| Tue Nov 3 | 6:00–10:00 PM | Renderer, features, loss, target generator, random-search baseline | A loss curve from the command line | Not started | |
| Tue–Wed | 10:00 PM–1:00 AM | Planner + optimizer loop, experiment logging, 3-target comparison | Hybrid beats optimizer-only on ≥2 of 3 targets (go/no-go) | Not started | |
| Wed Nov 4 | 9:00 AM–2:00 PM | UI: upload, spectrograms, timeline, score chart, A/B, 3 sliders | End-to-end run in the browser | Not started | |
| Wed Nov 4 | 2:00–4:00 PM | One Alchemy transform, JSON export | One distinct variant | Not started | |
| Wed Nov 4 | 4:00–6:00 PM | Deploy, final comparison chart | Public link works | Not started | |
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
- [ ] Disclosure of what the Meta model actually does vs the optimizer
- [ ] Baseline comparison chart included
