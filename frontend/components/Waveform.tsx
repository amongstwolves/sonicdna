export function Waveform({ min, max }: { min: number[]; max: number[] }) {
  const width = 960;
  const height = 120;
  const mid = height / 2;
  const peak = Math.max(1e-6, ...max.map(Math.abs), ...min.map(Math.abs));
  const scale = (mid - 2) / peak;
  const step = width / Math.max(1, max.length);
  const top = max.map((v, i) => `${(i * step).toFixed(1)},${(mid - v * scale).toFixed(1)}`);
  const bottom = min
    .map((v, i) => `${(i * step).toFixed(1)},${(mid - v * scale).toFixed(1)}`)
    .reverse();
  return (
    <svg
      className="waveform"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Waveform of the sound, loudness over time"
    >
      <line x1="0" x2={width} y1={mid} y2={mid} className="waveform-axis" />
      <polygon points={[...top, ...bottom].join(" ")} className="waveform-fill" />
    </svg>
  );
}
