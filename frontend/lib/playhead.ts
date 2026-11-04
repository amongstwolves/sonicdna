/** Which sound is playing and how far along it is. Only one sound plays at a time. */

interface NowPlaying {
  url: string;
  fraction: () => number;
}

let now: NowPlaying | null = null;

export function setNowPlaying(url: string, fraction: () => number): void {
  now = { url, fraction };
}

export function clearNowPlaying(url?: string | null): void {
  if (!url || now?.url === url) now = null;
}

/** 0 to 1 while this sound is playing, otherwise null. */
export function playheadFraction(url: string | null | undefined): number | null {
  if (!url || now?.url !== url) return null;
  const fraction = now.fraction();
  return Number.isFinite(fraction) ? Math.min(1, Math.max(0, fraction)) : null;
}
