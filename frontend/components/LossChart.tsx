"use client";

import { useState } from "react";
import {
  bestSoFarSeries,
  chartMax,
  formatLoss,
  provenanceOf,
  type ChartPoint,
  type Entry,
  type ProvenanceKey,
} from "@/lib/runs";
import { GlyphShape, ProvenanceGlyph } from "./Provenance";

const WIDTH = 760;
const HEIGHT = 230;
const MARGIN = { top: 14, right: 66, bottom: 34, left: 48 };
const PLOT_W = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom;

/** Step-after path: the best value holds until a render beats it. */
export function bestPath(points: { x: number; y: number | null }[]): string {
  let path = "";
  let last: number | null = null;
  for (const { x, y } of points) {
    if (y === null) continue;
    path += last === null ? `M${x.toFixed(1)},${y.toFixed(1)}` : `H${x.toFixed(1)}V${y.toFixed(1)}`;
    last = y;
  }
  return path;
}

export function LossChart({
  allEntries,
  revealed,
  capacity = 0,
  selectedPosition,
  onSelect,
}: {
  allEntries: Entry[];
  revealed: number;
  /** Width of the x axis for a live run, whose entries are still arriving. */
  capacity?: number;
  selectedPosition: number | null;
  onSelect: (position: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const points = bestSoFarSeries(allEntries.slice(0, revealed));
  const count = Math.max(allEntries.length, capacity, 2);
  const yMax = chartMax(allEntries);
  const x = (position: number) => MARGIN.left + (position / (count - 1)) * PLOT_W;
  const y = (value: number) => MARGIN.top + (1 - value / yMax) * PLOT_H;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);
  const xStep = count > 12 ? 5 : 1;
  const xTicks = Array.from({ length: count }, (_, i) => i).filter(
    (i) => (i + 1) % xStep === 0 || i === 0,
  );
  const present = [...new Set(allEntries.map((e) => provenanceOf(e.source).key))];
  const line = bestPath(points.map((p, i) => ({ x: x(i), y: p.best === null ? null : y(p.best) })));
  const lastBest = [...points].reverse().find((p) => p.best !== null);
  const hovered: ChartPoint | undefined = hover !== null ? points[hover] : undefined;

  function positionFromEvent(event: React.PointerEvent<SVGRectElement>): number | null {
    if (points.length === 0) return null;
    const box = event.currentTarget.getBoundingClientRect();
    const fraction = (event.clientX - box.left) / box.width;
    return Math.max(0, Math.min(points.length - 1, Math.round(fraction * (count - 1))));
  }

  return (
    <section className="panel chart-panel">
      <header className="chart-header">
        <div>
          <h2>Best-so-far normalized loss</h2>
          <p className="lower-better">
            <span aria-hidden="true">↓</span> Lower is better. 0 means the measured features match
            exactly.
          </p>
        </div>
        <ul className="legend" aria-label="Legend">
          <li>
            <span className="legend-line" aria-hidden="true" /> Best so far
          </li>
          {present.map((key: ProvenanceKey) => (
            <li key={key}>
              <ProvenanceGlyph kind={key} />{" "}
              {provenanceOf(key === "unknown" ? null : key).label}
            </li>
          ))}
        </ul>
      </header>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Best-so-far normalized loss by render number">
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y(tick)} y2={y(tick)} className="grid" />
              <text x={MARGIN.left - 8} y={y(tick) + 4} className="tick" textAnchor="end">
                {Number(tick.toFixed(3))}
              </text>
            </g>
          ))}
          {xTicks.map((i) => (
            <text key={i} x={x(i)} y={HEIGHT - MARGIN.bottom + 16} className="tick" textAnchor="middle">
              {i + 1}
            </text>
          ))}
          <text x={MARGIN.left + PLOT_W / 2} y={HEIGHT - 3} className="axis-title" textAnchor="middle">
            Render number
          </text>
          {selectedPosition !== null && selectedPosition < points.length ? (
            <line
              x1={x(selectedPosition)}
              x2={x(selectedPosition)}
              y1={MARGIN.top}
              y2={HEIGHT - MARGIN.bottom}
              className="selected-rule"
            />
          ) : null}
          {hover !== null && hover < points.length ? (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={MARGIN.top}
              y2={HEIGHT - MARGIN.bottom}
              className="crosshair"
            />
          ) : null}
          {points.map((point, i) =>
            point.failed ? (
              <text key={i} x={x(i)} y={MARGIN.top + PLOT_H - 4} className="failed-mark" textAnchor="middle">
                ×
              </text>
            ) : (
              <g key={i} className={`glyph-${point.provenance}`} data-testid="render-mark">
                <GlyphShape kind={point.provenance} x={x(i)} y={y(point.loss as number)} r={4.5} />
              </g>
            ),
          )}
          <path d={line} className="best-line" />
          {lastBest?.best != null ? (
            <text
              x={x(points.length - 1) + 8}
              y={y(lastBest.best) + 4}
              className="best-label"
            >
              {formatLoss(lastBest.best)}
            </text>
          ) : null}
          <rect
            x={MARGIN.left - 6}
            y={MARGIN.top}
            width={PLOT_W + 12}
            height={PLOT_H}
            fill="transparent"
            style={{ cursor: points.length ? "pointer" : "default" }}
            onPointerMove={(event) => setHover(positionFromEvent(event))}
            onPointerLeave={() => setHover(null)}
            onClick={(event) => {
              const position = positionFromEvent(event as unknown as React.PointerEvent<SVGRectElement>);
              if (position !== null) onSelect(position);
            }}
          />
        </svg>
        {hovered && hover !== null ? (
          <div
            className={`chart-tooltip${hover > count / 2 ? " flip" : ""}`}
            style={{ left: `${(x(hover) / WIDTH) * 100}cqw` }}
          >
            <strong>Render {hover + 1}</strong>
            <span>
              {hovered.failed ? "Failed, no loss" : `This render: ${formatLoss(hovered.loss)}`}
            </span>
            <span>Best so far: {formatLoss(hovered.best)}</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}
