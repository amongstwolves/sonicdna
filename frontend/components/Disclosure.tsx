export const DISCLOSURE_TEXT =
  "Live AI runs send descriptors and a spectrogram image to Meta's model API. Optimizer-only runs and replays send nothing.";

export function Disclosure() {
  return (
    <footer className="disclosure">
      <strong>Data use</strong>
      <span>{DISCLOSURE_TEXT}</span>
    </footer>
  );
}
