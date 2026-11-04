"""Build the held-out comparison chart from demo/heldout_results.json.

    python scripts/make_chart.py            # rebuild docs/heldout_comparison.svg
    python scripts/make_chart.py --collect  # first refresh the JSON from runs/benchmark-*
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "demo" / "heldout_results.json"
CHART = ROOT / "docs" / "heldout_comparison.svg"
METHODS = (
    ("hybrid", "AI + optimizer"),
    ("tpe", "Optimizer: TPE"),
    ("restart_local", "Optimizer: restart + local"),
    ("random", "Random search"),
)
RULE = (
    "A target is an AI win only if the AI + optimizer median is lower than both "
    "optimizer-only medians. Pass: at least 2 of 3."
)
_X_MIN, _X_MAX = 0.01, 0.5
_TICKS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5)
_WIDTH, _LEFT, _RIGHT = 880, 210, 80
_ROW, _PANEL_GAP = 26, 42
_STYLE = """
.bg{fill:#fcfcfb}.t{fill:#0b0b0b}.s{fill:#52514e}.grid{stroke:#e4e3de}
.ai{fill:#2a78d6;stroke:#2a78d6}.base{fill:#52514e;stroke:#52514e}
@media (prefers-color-scheme:dark){.bg{fill:#1a1a19}.t{fill:#f0efec}.s{fill:#c3c2b7}
.grid{stroke:#3a3a37}.ai{fill:#3987e5;stroke:#3987e5}.base{fill:#c3c2b7;stroke:#c3c2b7}}
text{font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif}
"""


def collect(run_dir: Path) -> dict[str, Any]:
    """Seed-level best losses from the three benchmark files of the one held-out run."""
    def load(label: str) -> dict[str, Any]:
        path = run_dir / f"benchmark-held_out-final-{label}.json"
        return json.loads(path.read_text())["results"]

    tpe, restart, hybrid = load("tpe"), load("restart"), load("hybrid")
    seeds = lambda runs: [run["best_loss"] for run in runs]  # noqa: E731
    targets = {
        name: {
            "hybrid": seeds(hybrid[name]["hybrid"]),
            "tpe": seeds(tpe[name]["optimizer_only"]),
            "restart_local": seeds(restart[name]["optimizer_only"]),
            "random": seeds(tpe[name]["random"]),
        }
        for name in hybrid
    }
    return {"budget_renders": 20, "rule": RULE, "targets": targets}


def verdicts(results: dict[str, Any]) -> dict[str, bool]:
    wins = {}
    for name, target in results["targets"].items():
        median = {key: statistics.median(values) for key, values in target.items()}
        wins[name] = median["hybrid"] < min(median["tpe"], median["restart_local"])
    return wins


def _x(loss: float) -> float:
    span = math.log(_X_MAX) - math.log(_X_MIN)
    position = (math.log(loss) - math.log(_X_MIN)) / span
    return _LEFT + position * (_WIDTH - _LEFT - _RIGHT)


def build_svg(results: dict[str, Any]) -> str:
    wins = verdicts(results)
    targets = results["targets"]
    top = 92
    panel_height = 24 + _ROW * len(METHODS)
    bottom = top + (panel_height + _PANEL_GAP) * len(targets) - _PANEL_GAP
    height = bottom + 62
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_WIDTH} {height}" role="img" '
        f'aria-labelledby="chart-title">',
        f"<style>{_STYLE}</style>",
        f'<rect class="bg" width="{_WIDTH}" height="{height}"/>',
        f'<text id="chart-title" class="t" x="24" y="34" font-size="20" font-weight="600">'
        f"AI + optimizer won {sum(wins.values())} of {len(wins)} held-out targets</text>",
        f'<text class="s" x="24" y="58" font-size="13">Best normalized loss after '
        f"{results['budget_renders']} renders. Lower is better. Log scale; each panel uses the "
        "same axis.</text>",
        '<circle class="base" cx="30" cy="74" r="3.5" fill-opacity="0.35"/>'
        '<text class="s" x="40" y="78" font-size="12">One seed</text>'
        '<rect class="base" x="104" y="69" width="10" height="10" transform="rotate(45 109 74)"/>'
        '<text class="s" x="122" y="78" font-size="12">Median of 3 seeds</text>',
    ]
    y = top
    for name, target in targets.items():
        verdict = "AI won" if wins[name] else "AI did not win"
        parts.append(
            f'<text class="t" x="24" y="{y + 12}" font-size="14" font-weight="600">'
            f"{escape(name)}</text>"
            f'<text class="s" x="{_LEFT}" y="{y + 12}" font-size="13">{verdict}</text>'
        )
        for tick in _TICKS:
            parts.append(
                f'<line class="grid" x1="{_x(tick):.1f}" x2="{_x(tick):.1f}" y1="{y + 20}" '
                f'y2="{y + panel_height}"/>'
            )
        for row, (key, label) in enumerate(METHODS):
            cy = y + 24 + _ROW * row + _ROW / 2
            css = "ai" if key == "hybrid" else "base"
            weight = ' font-weight="600"' if key == "hybrid" else ""
            parts.append(
                f'<text class="t" x="24" y="{cy + 4:.1f}" font-size="13"{weight}>'
                f"{escape(label)}</text>"
            )
            for loss in target[key]:
                parts.append(
                    f'<circle class="{css}" cx="{_x(loss):.1f}" cy="{cy:.1f}" r="4" '
                    f'fill-opacity="0.35"><title>{escape(label)}, one seed: {loss:.4f}</title>'
                    "</circle>"
                )
            median = statistics.median(target[key])
            mx = _x(median)
            parts.append(
                f'<rect class="{css}" x="{mx - 5:.1f}" y="{cy - 5:.1f}" width="10" height="10" '
                f'transform="rotate(45 {mx:.1f} {cy:.1f})"><title>{escape(label)}, median: '
                f"{median:.4f}</title></rect>"
            )
            value_x = max(_x(max(target[key])), mx) + 10
            parts.append(
                f'<text class="s" x="{value_x:.1f}" y="{cy + 4:.1f}" font-size="12">'
                f"{median:.3f}</text>"
            )
        y += panel_height + _PANEL_GAP
    for tick in _TICKS:
        parts.append(
            f'<text class="s" x="{_x(tick):.1f}" y="{bottom + 18}" font-size="12" '
            f'text-anchor="middle">{tick:g}</text>'
        )
    parts.append(
        f'<text class="s" x="24" y="{height - 16}" font-size="12">{escape(results["rule"])}</text>'
    )
    parts.append("</svg>\n")
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--collect", action="store_true")
    args = parser.parse_args()
    if args.collect:
        RESULTS.parent.mkdir(exist_ok=True)
        RESULTS.write_text(json.dumps(collect(ROOT / "runs"), indent=2) + "\n")
    results = json.loads(RESULTS.read_text())
    CHART.parent.mkdir(exist_ok=True)
    CHART.write_text(build_svg(results))
    print(f"Wrote {CHART}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
