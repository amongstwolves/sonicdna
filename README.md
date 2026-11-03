# SonicDNA

Autonomous sound-design lab: reconstruct a sound as an editable synth recipe through logged experiments, then transform it.
Built for the Meta Global AI Developer Hackathon (submission due Wed Nov 4, 2026, 9:00 PM ET).

## Start the Claude Code session

```bash
cd sonicdna
git init && git add -A && git commit -m "Project brief, spec and build plan"
cp .env.example .env   # add your Meta API key
claude
```

Then paste this as your first message:

> Read CLAUDE.md, docs/SPEC.md and docs/PLAN.md. We're on the first schedule block (Tue 4:30–6:00 PM ET).
> Scaffold the repo layout from CLAUDE.md, set up a Python env with FastAPI, numpy, scipy, librosa and optuna,
> then write a minimal script that makes one structured-output call to the Meta model with the planner schema
> so we can confirm API access. Stop and show me the result before moving on.

## Docs

- `CLAUDE.md` — project brief, locked decisions, architecture, rules (Claude Code loads this automatically)
- `docs/SPEC.md` — full product and technical spec
- `docs/PLAN.md` — schedule, checkpoints, status tracking
