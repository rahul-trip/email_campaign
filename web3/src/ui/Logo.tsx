/**
 * The Outbound mark: "The Infinite Vector" (Stitch project 538951827606035367, board "'O' Monogram
 * Exploration Board", variation 3D). An indigo loop that closes into the letter O, and a teal arrow
 * that leaves it to the top right. The colours are tokens, so it follows the light and dark themes.
 *
 * Detail depends on size, as on the board: from 56px the loop carries a faint inner swirl; from
 * 40px it curls round to meet the arrow; smaller, the plain open loop and a heavier stroke, which
 * stay clear at 16px. public/favicon.svg is the small one with fixed colours.
 */
import { cx } from "../lib/cx";

const LOOP = "M42 74C25 74 14 62 14 46C14 30 25 18 42 18";
const CURL = "C52 18 58 22 62 28";
const SWIRL = "M22 34C28 24 38 20 48 24C56 27 60 36 56 46C53 54 44 60 36 60C30 60 26 56 28 50C30 44 38 40 48 40";

export function LogoMark({ size = 36, className }: { size?: number; className?: string }) {
  const curl = size >= 40;
  const swirl = size >= 56;
  const stroke = size >= 56 ? 7.5 : size >= 40 ? 7 : 8;
  const common = { strokeWidth: stroke, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <svg viewBox="0 0 88 88" width={size} height={size} fill="none" aria-hidden data-brand-mark className={cx("shrink-0", className)}>
      <path d={curl ? `${LOOP}${CURL}` : LOOP} stroke="var(--primary)" {...common} />
      {swirl && <path d={SWIRL} stroke="var(--primary)" strokeOpacity={0.3} strokeWidth={6.5} strokeLinecap="round" />}
      <path d="M36 52L68 20" stroke="var(--teal)" {...common} />
      <path d="M48 20H68V40" stroke="var(--teal)" {...common} />
    </svg>
  );
}
