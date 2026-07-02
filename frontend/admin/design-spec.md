# BM USA Proxy — Admin Console — Design Spec

Source of truth: `D:/Projects/bm-usa-proxy/demo/admin.html` (approved prototype).
This document ports the prototype's design tokens and component patterns 1:1 into
the Tailwind config and shared component library so every screen stays visually
consistent without re-deriving values. Tokens match `frontend/miniapp` where they
overlap (same brand, same backend) — the admin panel adds sidebar/table/drawer/kpi
tokens the mini-app doesn't need.

## 1. Color tokens

| Token | Hex / value | Tailwind class | Usage |
|---|---|---|---|
| `bg` | `#F3FBFF` | `bg-bg` | App background |
| `surface` | `#FFFFFF` | `bg-surface` | Cards, sidebar, topbar, table |
| `surface-2` | `#EDF3F8` | `bg-surface-2` | Hover fills, input backgrounds, track backgrounds |
| `border` | `#D8E6F0` | `border-border` | Default hairline border |
| `border-2` | `#C7DAEA` | `border-border-2` | Emphasized border (hover, focus adjacent) |
| `text` | `#14324A` | `text-text` | Primary text / headings |
| `text-2` | `#4E6B81` | `text-text-2` | Secondary text |
| `text-3` | `#7C95A8` | `text-text-3` | Tertiary / labels / placeholders |
| `accent` | `#195079` | `text-accent` / `bg-accent` | Brand deep blue — primary actions, active nav, links |
| `accent-2` | `#124063` | `bg-accent-2` | Accent hover/pressed state |
| `on-accent` | `#FFFFFF` | `text-on-accent` | Text/icons on accent-filled surfaces |
| `accent-soft` | `rgba(25,80,121,.09)` | `bg-accent-soft` | Active nav background, accent badge background |
| `accent-line` | `rgba(25,80,121,.28)` | `border-accent-line` | Focus border, accent badge border |
| `success` | `#1E9E6A` | `text-success` / `bg-success` | Positive status (online, activated, approved) |
| `warning` | `#D99021` | `text-warning` / `bg-warning` | Attention status (full, pending, expiring) |
| `danger` | `#C2413C` | `text-danger` / `bg-danger` | Negative status (banned, failed, offline-critical) — **also the fixed accent-2 brand mark** |
| `success-soft` / `warning-soft` / `danger-soft` | `rgba(...,.10)` | `bg-success-soft` etc. | Badge/chip backgrounds |

Status colors are **never** reused for brand actions — brand = blue only. This mirrors the prototype's explicit comment `/* status - separate, never brand */`.

## 2. Typography

Google Fonts, loaded via `<link>` in `index.html` (not `@import`, for perf):

```
Jost:wght@500;600;700 — display/heading font, letter-spacing -0.02em
Roboto:wght@300;400;500;600 — body font, default UI text
Roboto Mono:wght@400;500;600 — numeric font, ALWAYS for money/counts/IDs/timestamps
```

- `font-head` → `Jost, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`
- `font-body` → `Roboto, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif` (body default)
- `font-mono` → `"Roboto Mono", ui-monospace, "SFMono-Regular", "Cascadia Code", Menlo, monospace`

Rule: any element showing a number that represents money, a count, a percentage, an ID/username, or a timestamp gets `font-mono tabular-nums` (Tailwind: `font-mono` + `tabular-nums` via the `Num` component, see §6). This is what gives the dashboard its "operations console" feel instead of generic SaaS.

Headings use `font-head` with `tracking-[-0.02em]` and `font-semibold` (600). Scale:
- h1 `text-[1.953rem]` (page titles)
- h2 `text-[1.563rem]` (panel/section titles, `Dashboard`, `Clients` etc.)
- h3 `text-base` (panel-head titles)

Base body: `text-[15px] leading-[1.5] font-normal text-text` on `<body>`.

## 3. Radii, shadow, motion

```
radius-sm  = 8px   (chips, small buttons, inputs)
radius     = 12px  (buttons, panels-inner, avatar/brand-mark)
radius-lg  = 16px  (panels, cards, KPI blocks)
radius-xl  = 22px  (reserved — large modals)
```

Shadow is soft and blue-tinted, never a hard black box-shadow:
```
shadow-DEFAULT = 0 8px 24px -12px rgba(20,50,74,.18)
shadow-lg      = 0 16px 40px -16px rgba(20,50,74,.22)
```
Used on: `.panel`, `.kpi-primary`, `.kpi-cluster`, `.drawer` (lg), dropdown menus.

Motion: **all transitions use the prototype's custom ease**, never default `ease-in-out`:
```css
--ease: cubic-bezier(.16,1,.3,1)
```
Standard duration: **160ms** for hover/color/border transitions, **200ms** for drawer/modal transform, **280–300ms** for progress-bar width fills. Screen switches fade+translateY(4px)→none over 200ms. This is registered in Tailwind as `transitionTimingFunction.ease` so components just write `transition-colors duration-150 ease-brand` (see tailwind.config).

## 4. Layout

```
sidebar width = 264px (fixed, sticky, full height, collapses under 820px — mobile not a target for an ops console but the grid degrades gracefully)
topbar height = 64px (sticky, backdrop-blur, semi-transparent bg)
content max-width = 1320px inside .screens padding 26px 24px 48px
```

Grid shell: `grid grid-cols-[264px_1fr] min-h-screen`.

## 5. Core component patterns (ported from prototype, exact values)

### Sidebar nav item
- Height 40px min, padding `9px 10px`, gap 11px, radius `r-sm` (8px)
- Default: `text-text-2`, icon `text-text-3`
- Hover: `bg-surface-2`, `text-text`, icon `text-text-2`
- Active: `bg-accent-soft`, `text-accent`, icon `text-accent`, font-weight 500
- Accessory slot on the right: either a `nav-badge` (mono, accent-filled pill, for counts like pending Requests) or a `nav-dot` (7px accent dot with a 3px accent-soft ring, for "has live activity")

### Buttons
- `btn-primary`: `bg-accent text-on-accent hover:bg-accent-2`
- `btn-ghost`: `bg-surface border border-border text-text hover:bg-surface-2 hover:border-border-2`
- `btn-quiet`: transparent, `text-text-2 hover:bg-surface-2 hover:text-text`
- `btn-danger` (new, for destructive confirms — not in prototype but required by API surface: ban/revoke/reject): `bg-danger text-on-accent hover:bg-[#a8352f]`
- All buttons: min-height 40px (sm: 32px), radius 12px (sm: 8px), font-weight 600, `active:translate-y-px`

### Panel / Card
`bg-surface border border-border rounded-lg shadow` (shadow = the soft blue-tinted DEFAULT). `panel-head` has a bottom hairline + flex-between title/actions. `panel-body` padding 18px (or `tight` = 6px, used for the notification feed / dense lists).

### Badge / StatusBadge
Pill, height ~23-24px, `rounded-full`, `border`, 6px leading dot, 12px font-weight 600. Five palettes: neutral / accent / success / warning / danger — exact bg/border/text values in §1. This becomes the shared `StatusBadge` component (see §6) with a single `tone` prop mapping every backend status string.

### Table
- `thead th`: uppercase, `text-[0.7rem]` tracking `.08em`, `text-text-3`, bottom border, padding `10px 14px`
- `tbody td`: padding `12px 14px`, bottom border, `text-text-2`, vertical-middle
- Row hover: `bg-surface-2`, 140ms transition
- Strong cell (`t-strong`): `text-text font-medium`
- User/ID cell (`t-user`): `font-mono text-[0.82rem] text-text`
- Numeric cell: `font-mono tabular-nums text-text`

### KPI cards
Two patterns, both used on Dashboard:
1. **kpi-primary** (hero stat): label (uppercase, text-3) → huge mono value (`2.35rem` / `font-semibold` / `tracking-[-0.02em]`) → delta pill (up=success-soft/success, down=danger-soft/danger, mono, arrow icon) → optional sparkline (inline SVG, accent stroke + accent gradient fill).
2. **kpi-cluster** (5-up grid, dividers between cells, shared shadow container): icon+label row → mono value `1.5rem` → footer (plain text, badge, or a `linkish` button-as-link in accent that jumps to another screen).

### Slide-over drawer
`fixed top-0 right-0 h-screen w-[min(440px,92vw)] bg-surface border-l border-border shadow-lg`, `translate-x-full` → `translate-x-0` on open, 200ms ease. Head (flex-between, bottom hairline) / scrollable body (padding 20px) / foot (top hairline, right-aligned action row).

### Switch (toggle)
38×22px pill track. Off: `bg-surface-2 border-border-2`, thumb `bg-text-3`. On: track `bg-accent-soft border-accent-line`, thumb `translate-x-4 bg-accent`. Used for `is_sellable` toggle in Pools table and notification channel toggles.

### Row-item (list row, used in "Needs attention" / activity feeds)
Icon chip (34px, rounded-[9px], surface-2 bg + border-2, tone-colored icon for warn/ok/alert) + title/sub stack + trailing action (button or badge).

### Device/summary card (Pools screen signature pattern)
White card, border, `rounded-lg`, hover border→border-2. Header: mono ID (text-3) + city name (font-head, semibold) + state, with a status pill top-right (online=success-soft, offline=text-3 @ 56% opacity card, full=warning-soft + warning border tint). Carrier row with small icon. Slot-usage bar (4px track, colored fill: accent=normal load, warning=near-full, muted=offline). Footer: hairline-top, "last rotated" mono timestamp + kebab menu.

### Map hero (Dashboard signature — recreate faithfully)
Inline SVG US silhouette (`surface-2` fill, `border-2` stroke) with mesh connection lines (`accent` @ 13% opacity) and per-city pulse nodes: `online` = accent dot + radiating pulse-ring animation (staggered delay per node), `full` = static warning dot + static ring, `offline` = static text-3 dot + static ring. Legend row + right-aligned totals (Slots/Used/Free, mono). This is generated from live `/pool/summary` data — city coordinates are a static lookup table (see `mapCoordinates.ts`) keyed by `location_id`/city code, degrading gracefully (city omitted from map, still counted in totals) if a city isn't in the lookup.

### Focus & accessibility
`:focus-visible` on all interactive elements → `outline: 2px solid accent; outline-offset: 2px`. Never remove focus rings — this is an internal ops tool used for hours at a time, keyboard nav matters.

## 6. Shared building blocks → files

| Component | File | Notes |
|---|---|---|
| `Button` | `src/shared/components/Button.tsx` | variants: primary/ghost/quiet/danger, sizes: default/sm |
| `Panel` | `src/shared/components/Panel.tsx` | `Panel`, `Panel.Head`, `Panel.Body` compound |
| `StatCard` | `src/shared/components/StatCard.tsx` | kpi-cluster cell |
| `StatHero` | `src/shared/components/StatHero.tsx` | kpi-primary block w/ sparkline |
| `StatusBadge` | `src/shared/components/StatusBadge.tsx` | tone-driven pill, single source of truth for every status string → tone mapping |
| `Chip` | `src/shared/components/Chip.tsx` | neutral filter/meta chip |
| `Num` | `src/shared/components/Num.tsx` | wraps a value in `font-mono tabular-nums`, optional `$`/`%` formatting |
| `CopyField` | `src/shared/components/CopyField.tsx` | monospace value + copy-to-clipboard icon button + toast |
| `Toast` | `src/shared/components/Toast.tsx` + `ToastProvider` | success/error/info variants, bottom-right stack |
| `Modal` | `src/shared/components/Modal.tsx` | centered dialog, overlay fade, used for create/edit forms |
| `ConfirmDialog` | `src/shared/components/ConfirmDialog.tsx` | destructive-action confirm, optional required "reason" textarea |
| `SlideOver` | `src/shared/components/SlideOver.tsx` | drawer, used for dossiers (Client, Order, Request) |
| `Switch` | `src/shared/components/Switch.tsx` | toggle, react-hook-form compatible |
| `DataTable` | `src/shared/components/DataTable.tsx` | TanStack Table wrapper: server pagination, column defs, loading/empty/error states baked in |
| `EmptyState` / `ErrorState` / `Skeleton` | same folder | shared across every list screen |
| `FormField` | `src/shared/components/form/*` | Input/Select/Textarea wrappers pre-wired to react-hook-form + zod error display, label styled per `.field label` token |
| `Sidebar` / `Topbar` / `AppShell` | `src/layout/*` | the chrome, ported 1:1 from prototype markup incl. inline SVG icon set |

## 7. Icons

No icon library — **inline SVG only**, `stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"`, viewBox `0 0 24 24`, sized via Tailwind `w-[18px] h-[18px]` (nav) or `w-4 h-4` (buttons). This matches the prototype exactly (no emoji, no icon font). Icon set is centralized in `src/shared/components/icons.tsx` as named exports (`IconDashboard`, `IconClients`, …) — every path copied verbatim from `demo/admin.html` so the visual language never drifts from the approved prototype.

## 8. Screen-specific notes

- **Dashboard**: kpi-row (hero + cluster) → map-hero panel (recharts is used only for the revenue trend line chart per spec; the sparkline in the hero KPI stays hand-drawn inline SVG matching the prototype, and the US map stays hand-drawn inline SVG — recharts would fight the prototype's bespoke look here) → dash-lower 3-col (Needs attention / recent activity panels).
- **Clients**: DataTable (server-side) + SlideOver dossier (profile header, tabs or stacked sections: TOS status, accesses list, orders list, referral card, requests list) with inline actions (ban/unban, note, message, issue-access modal).
- **Pools**: `pools-summary-bar` (cell row + capacity bar) ported verbatim, then device-card grid (`pools-device-grid`) with inline `is_sellable` switch + kebab menu (edit tier/location/carrier/health-note), "Sync now" button calling `/connections/sync`.
- **Packages** (accesses): DataTable with status/city/user filters + expiring toggle, row actions (revoke w/ reason, extend w/ minutes stepper, rotate-ip, reissue).
- **Requests**: Kanban 4 columns (new/in_progress/waiting/done — exact enum confirmed against backend at implementation time) using simple status-button move (no drag library — keeps bundle small, matches "OR status buttons" instruction) + SlideOver with comment thread.
- **Tariffs**: table + Modal create/edit form incl. `max_user_swaps` field, inline toggle for active/inactive.
- **Orders/Payments**: tabbed (All / Manual review) DataTable + SlideOver (invoice, event timeline styled as a vertical stepper) + refund form (amount, reason, optional wallet/tx hash) + owner-only mark-paid action gated by `RequireRole`.
- **Referrals**: StatCard tile row (summary) + ledger DataTable + payouts queue (row-item pattern, approve/reject/mark-paid actions) + settings form (owner-only edit, read-only for non-owners).
- **Broadcasts**: list + composer Modal (title/body/audience filter builder) + schedule-or-send-now + progress bar (delivered/total, poll while sending).
- **Publications**: channels table + posts table with attribution columns (views/clicks if provided by API) + composer.
- **FAQ**: simple CRUD list, inline expand-to-edit, drag-free manual ordering deferred (no `order` field in spec) — add/edit/delete only.
- **Notifications**: two-panel layout ported verbatim from prototype (`ntf-layout` grid) — event log feed (left) + settings matrix (right, per-event TG/Email channel toggle grid grouped by category).
- **Settings**: compact — app settings form, Terms editor (question list, add/remove, publish button), Admins CRUD table, Audit log table (entity/admin filter). All owner-gated except viewing.

## 9. RBAC visual treatment

Owner-only controls are not just hidden — when hidden, the parent layout must not leave a gap (conditional render, not `disabled` + tooltip, to avoid ambiguity for a Support-role operator who should not know the feature exists). This is a security/product decision, not just visual, but documented here because it affects layout: Settings nav item and page still visible to non-owners (viewing app settings must remain readable), but the "Admins" tab and "Terms → Publish" button and payments "Mark paid" button and referral "Settings" edit are removed as whole DOM nodes, not disabled inputs.

## 10. What changed vs. the prototype (must-know deltas)

The prototype is static HTML with hardcoded example data and `data-target` screen-switching. The Frontend Developer implementation replaces:
- Screen switching → React Router (`react-router-dom`, matching miniapp convention) with routes per screen instead of `.screen.is-active` class toggling.
- Static numbers → live data via TanStack Query hooks hitting the endpoints in the task spec.
- `onclick` toggle handlers (notification channel buttons) → controlled React state wired to `PATCH /notifications/settings`.
- Kebab menus / dropdowns → still plain React state (no headless-ui dependency needed, keeps bundle small — matches the minimal-deps philosophy of `frontend/miniapp`).
