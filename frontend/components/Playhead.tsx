"use client";

import { useEffect, useRef } from "react";
import { playheadFraction } from "@/lib/playhead";

/** A line over a time-based picture. Updated per frame without re-rendering React. */
export function Playhead({ audioUrl }: { audioUrl: string | null | undefined }) {
  const line = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const fraction = playheadFraction(audioUrl);
      if (line.current) {
        line.current.hidden = fraction === null;
        if (fraction !== null) line.current.style.setProperty("--position", String(fraction));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [audioUrl]);

  return <div ref={line} className="playhead" data-testid="playhead" hidden aria-hidden="true" />;
}
