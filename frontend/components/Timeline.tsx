"use client";

import { useEffect, useRef } from "react";
import { formatLoss, headline, provenanceOf, renderNumber, type Entry } from "@/lib/runs";
import { ProvenanceChip } from "./Provenance";

export function TimelineCard({
  entry,
  selected,
  isBest,
  onSelect,
}: {
  entry: Entry;
  selected: boolean;
  isBest: boolean;
  onSelect: () => void;
}) {
  const line = headline(entry);
  const provenance = provenanceOf(entry.source);
  const ref = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    // Scrolls the list only. scrollIntoView would also move the page and hide the replay label.
    const card = ref.current;
    const list = card?.closest("ol");
    if (!selected || !card || !list) return;
    const top = card.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop;
    if (top < list.scrollTop) list.scrollTop = top - 8;
    else if (top + card.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top + card.offsetHeight - list.clientHeight + 8;
    }
  }, [selected]);

  return (
    <button
      ref={ref}
      type="button"
      className={`card card-${provenance.key}${selected ? " is-selected" : ""}`}
      aria-current={selected ? "true" : undefined}
      onClick={onSelect}
    >
      <span className="card-top">
        <span className="card-number">{renderNumber(entry)}</span>
        <ProvenanceChip source={entry.source} />
        {entry.planner_call !== null ? (
          <span className="planner-tag">
            {provenance.key === "model" || provenance.key === "fallback" ? "Planner call" : "After planner call"}{" "}
            {entry.planner_call}
          </span>
        ) : null}
        <span className="card-loss">
          {entry.failure !== null || entry.loss === null ? (
            <span className="failed-tag">Failed</span>
          ) : (
            formatLoss(entry.loss)
          )}
        </span>
      </span>
      <span className={`card-line card-line-${line.kind}`}>
        {line.kind === "recipe" ? <em>No hypothesis logged. Recipe: </em> : null}
        {line.kind === "failure" ? <em>Failure: </em> : null}
        {line.text}
      </span>
      {isBest ? <span className="best-tag">Best so far</span> : null}
    </button>
  );
}

export function Timeline({
  entries,
  countLabel,
  emptyText,
  selectedPosition,
  bestIndex,
  onSelect,
}: {
  entries: Entry[];
  countLabel: string;
  emptyText: string;
  selectedPosition: number | null;
  bestIndex: number | null;
  onSelect: (position: number) => void;
}) {
  return (
    <section className="timeline" aria-label="Experiment timeline">
      <header className="timeline-header">
        <h2>Experiment log</h2>
        <span className="mono">{countLabel}</span>
      </header>
      <ol>
        {entries.map((entry, position) => (
          <li key={`${entry.index}-${position}`}>
            <TimelineCard
              entry={entry}
              selected={position === selectedPosition}
              isBest={entry.index === bestIndex}
              onSelect={() => onSelect(position)}
            />
          </li>
        ))}
      </ol>
      {entries.length === 0 ? <p className="timeline-empty">{emptyText}</p> : null}
    </section>
  );
}
