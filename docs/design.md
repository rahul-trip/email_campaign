---
name: Outbound
colors:
  primary: '#2F4BFF'
  on-primary: '#FFFFFF'
  primary-container: '#E6EAFF'
  on-primary-container: '#1A2B99'
  background: '#F6F7F9'
  on-background: '#111827'
  surface: '#FFFFFF'
  on-surface: '#111827'
  surface-container-low: '#F9FAFB'
  surface-container: '#F3F4F6'
  on-surface-variant: '#6B7280'
  outline: '#D1D5DB'
  outline-variant: '#E5E7EB'
  error: '#DC2626'
  on-error: '#FFFFFF'
  error-container: '#FEE2E2'
  on-error-container: '#991B1B'
  status-working: '#0284C7'
  status-working-container: '#E0F2FE'
  on-status-working-container: '#075985'
  status-attention: '#D97706'
  status-attention-container: '#FEF3C7'
  on-status-attention-container: '#92400E'
  status-good: '#16A34A'
  status-good-container: '#DCFCE7'
  on-status-good-container: '#166534'
  status-stopped: '#64748B'
  status-stopped-container: '#F1F5F9'
  on-status-stopped-container: '#334155'
typography:
  headline-lg: {fontFamily: Inter, fontSize: 24px, fontWeight: '600', lineHeight: 32px, letterSpacing: -0.01em}
  headline-md: {fontFamily: Inter, fontSize: 18px, fontWeight: '600', lineHeight: 28px}
  title-sm: {fontFamily: Inter, fontSize: 15px, fontWeight: '600', lineHeight: 22px}
  body-base: {fontFamily: Inter, fontSize: 14px, fontWeight: '400', lineHeight: 20px}
  body-sm: {fontFamily: Inter, fontSize: 13px, fontWeight: '400', lineHeight: 18px}
  label-caps: {fontFamily: Inter, fontSize: 11px, fontWeight: '600', lineHeight: 16px, letterSpacing: 0.04em}
  stat-lg: {fontFamily: Inter, fontSize: 28px, fontWeight: '600', lineHeight: 36px}
  mono-sm: {fontFamily: JetBrains Mono, fontSize: 13px, fontWeight: '400', lineHeight: 18px}
  email-body: {fontFamily: Inter, fontSize: 15px, fontWeight: '400', lineHeight: 24px}
rounded:
  sm: 4px
  DEFAULT: 6px
  md: 8px
  lg: 12px
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
  sidebar: 240px
  side-panel: 420px
  content-max: 1440px
---

## Brand & Style
Outbound is a work tool for a B2B outreach operator who reviews AI-written emails and
unblocks leads for hours at a time. Calm, precise, trustworthy, information-dense.
The clarity of Linear or the Stripe dashboard, not a marketing-automation suite.
No gradients, no illustrations in working screens, no decorative imagery.

## Colors
Neutral greys carry the interface; brand blue is for primary actions, focus and the
selected navigation item only. Five status families give every status its meaning:
working (sky) = the engine is busy; attention (amber) = waits on a person, the most
visible family; good (green) = done or safe; stopped (slate) = ended by a choice or a
rule; error (red) = broken, used sparingly. Status text sits on the container colour
and always includes a word, never colour alone. A dark theme mirrors these roles on
near-black surfaces with the same status hues.

## Typography
Inter throughout, with tabular figures for every number and amount of money.
JetBrains Mono for domains, email addresses and ids. Email bodies use email-body on a
white surface, at most 68 characters wide, so they read like the sent email.

## Layout & Spacing
Desktop-first web app. Fixed left sidebar, 56px global header, content up to 1440px.
Lists open records in a right side panel. 4px grid. Tables have 40px compact rows
and 48px comfortable rows.

## Elevation & Depth
Flat. Borders separate surfaces; a whisper-soft shadow only on menus, dialogs and the
side panel.

## Shapes
Gently rounded: 6px on buttons and inputs, 8px on cards, pill-shaped status badges.

## Components
- Status badge: pill, container colour, a dot and a word.
- Stage bar: eight connected segments (done, next, waiting on you, failed, not reached).
- Buttons: primary filled blue; secondary outlined; destructive red, only in danger zones.
- Money: a dollar amount with a thin budget meter against $0.50.
- Banner: full width under the header; attention or error colours.
- Legal footer in emails: shaded block with a lock icon; it cannot be edited.

## Logo

The mark is **The Infinite Vector** (Stitch project `538951827606035367`, board "'O' Monogram Exploration Board", variation 3D): an indigo loop that closes into the letter O, and a teal arrow leaving it to the top right, beside the Inter wordmark "Outbound" in bold with tight tracking. In code it is `web3/src/ui/Logo.tsx::LogoMark`; the indigo is `--primary` and the teal is `--teal` (`#0d9488`, `#2dd4bf` in dark), so it follows both themes. Its detail depends on size: from 56px the loop carries a faint inner swirl, from 40px it curls round to meet the arrow, and below that it is the plain open loop with a heavier stroke, which stays clear at 16px. The favicon is `web3/public/favicon.svg`, the small version with fixed colours that switch for a dark browser. Use it bare, not in a coloured square.

## Collapsible cards

A long page keeps its detail behind collapsible cards (`Card collapsible`). The title row is one button with a chevron (down when open, right when closed) and `aria-expanded`; the subtitle stays visible when closed and carries a one-line summary (a count, a cost, the latest event). Cards the reader acts in stay open; reference cards (tables, history, research, danger actions) start closed. A card opens by itself when the page expects the reader to act there (`forceOpen`), and the reader can still close it.

## Hot and cold

A fit score above 80 is shown with the flame icon and the attention colours (`FitBadge`); any other score is muted. Never use an emoji for it.
