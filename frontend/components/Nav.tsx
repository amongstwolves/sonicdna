"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SCREENS = [
  { href: "/decode", label: "Decode", note: "What is this sound?" },
  { href: "/lab", label: "Experiment Lab", note: "How was it rebuilt?" },
  { href: "/alchemy", label: "Alchemy", note: "What could it become?" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <header className="nav">
      <Link href="/decode" className="wordmark">
        Sonic<em>DNA</em>
      </Link>
      <nav aria-label="Screens">
        {SCREENS.map((screen, position) => (
          <Link
            key={screen.href}
            href={screen.href}
            className="nav-link"
            aria-current={pathname.startsWith(screen.href) ? "page" : undefined}
          >
            <span className="nav-number">{position + 1}</span>
            <span>
              <strong>{screen.label}</strong>
              <small>{screen.note}</small>
            </span>
          </Link>
        ))}
      </nav>
    </header>
  );
}
