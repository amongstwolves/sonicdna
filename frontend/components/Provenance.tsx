import { provenanceOf, type ProvenanceKey } from "@/lib/runs";

/** Each source has its own shape as well as its own colour, so it survives without colour. */
export function ProvenanceGlyph({ kind, size = 12 }: { kind: ProvenanceKey; size?: number }) {
  const mid = size / 2;
  const inner = size - 2;
  return (
    <svg
      className={`glyph glyph-${kind}`}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
    >
      <GlyphShape kind={kind} x={mid} y={mid} r={inner / 2} />
    </svg>
  );
}

export function GlyphShape({
  kind,
  x,
  y,
  r,
}: {
  kind: ProvenanceKey;
  x: number;
  y: number;
  r: number;
}) {
  switch (kind) {
    case "model":
      return <polygon points={`${x},${y - r} ${x + r},${y} ${x},${y + r} ${x - r},${y}`} />;
    case "optimizer":
      return <circle cx={x} cy={y} r={r} />;
    case "fallback":
      return <polygon points={`${x},${y - r} ${x + r},${y + r} ${x - r},${y + r}`} />;
    case "random":
      return <circle cx={x} cy={y} r={r - 0.5} className="hollow" />;
    default:
      return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} className="hollow" />;
  }
}

export function ProvenanceChip({ source }: { source: string | null }) {
  const provenance = provenanceOf(source);
  return (
    <span className={`chip chip-${provenance.key}`} title={provenance.description}>
      <ProvenanceGlyph kind={provenance.key} />
      {provenance.label}
    </span>
  );
}
