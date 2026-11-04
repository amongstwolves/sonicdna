"use client";

import { useEffect, useState } from "react";
import { Playhead } from "./Playhead";

export function Spectrogram({
  src,
  title,
  note,
  emptyText,
  audioUrl,
}: {
  src: string | null;
  title: string;
  note?: string;
  emptyText?: string;
  audioUrl?: string | null;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <figure className="spectrogram">
      <figcaption>
        <strong>{title}</strong>
        {note ? <span>{note}</span> : null}
      </figcaption>
      <div className="spectrogram-frame">
        {src && !failed ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={`Spectrogram: ${title}`} onError={() => setFailed(true)} />
        ) : (
          <div className="spectrogram-empty">
            {failed ? "This spectrogram isn't available." : (emptyText ?? "Nothing to show yet.")}
          </div>
        )}
        {src && !failed ? <Playhead audioUrl={audioUrl} /> : null}
        <span className="axis-tag axis-y">5.5 kHz ↑ higher pitch</span>
        <span className="axis-tag axis-x">0 Hz, time →</span>
      </div>
    </figure>
  );
}
