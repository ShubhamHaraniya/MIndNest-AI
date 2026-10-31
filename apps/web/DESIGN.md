# MindNest AI — design system and working notes

The reference implementations are the **dashboard** (`src/components/dashboard/workbench.tsx`) and the
**chat workspace** (`src/components/chat/*`). Read both before designing a page. Look at their screenshots
(see "Looking at the app") — the result for every page should feel like the same product.

## Principles
1. A page is a **working surface**, not a poster. Lead with the thing the student is working on (their
   files, their questions, their schedule); put controls beside the data they act on.
2. **Dense but calm.** Compact controls (h-7 / h-8 / h-9), 13px body text in lists and tables, 14–15px for
   reading text, thin 1px rules instead of boxes inside boxes. Whitespace is spent between groups, not inside rows.
3. **Lists and tables over cards.** Use `Panel` + rows/tables. No tile grids of icons, no oversized KPI
   numbers, no coloured subject tiles. Numbers are inline facts (`Facts`, table cells, a short sentence).
4. **Colour means something.** Forest green (`primary`) is for the one primary action and the selected
   state. Status uses the semantic tones (`success`, `warning`, `danger`, `info`) in `Badge` or text. Everything
   else is neutral ink / muted / faint on warm paper.
5. **Flat.** No gradients, glows, glass, shadows on cards, or big radii (the Tailwind radii are already
   flattened to 2–6px). Shadows only for popovers (`shadow-pop`). No decorative icons-in-circles.
   Icons are 14–16px, line style (lucide), always next to a label or with an `aria-label`/`title`.
6. **Every element works.** No placeholder buttons, no fake charts, no sample data. If the backend lacks
   something the brief needs, build it (route + tests); never fake it in the UI.
7. **States are part of the design:** loading (skeleton, not a spinner page), empty (says what this place is
   for and offers the first step), error (message + retry), success (toast), disabled (explain why via
   `title` or helper text), permission denied (`PermissionDenied`).
8. **Typography:** `font-display` (Source Serif 4) only for page titles (`text-2xl`), panel/section titles
   in prose areas, and quoted passages. Everything else is Inter. Micro-labels: `text-[11px] font-medium
   uppercase tracking-wide text-faint rtl:tracking-normal`. Use `tabular` (tabular-nums) for numbers.
   Never use bold for whole paragraphs.
9. **Accessible:** real `<button>`/`<a>`, labels on inputs (`sr-only` if not visible), `aria-pressed` /
   `aria-selected` / `aria-current`, focus rings are global (don't remove), colour is never the only signal.
10. **Responsive:** design the phone layout deliberately (stack columns, tables scroll inside `Table`,
    hide secondary columns with `hidden sm:table-cell`). No horizontal page scroll at 360px.
11. **Hindi and Gujarati** are first-class: every visible string through `t()`, no text baked into icons or
    widths that assume English length, allow wrapping/truncation with `title`, check the page at `--lang hi`
    and `--lang gu`.

## Tokens (CSS variables in `src/app/globals.css`, mapped in `tailwind.config.ts`)
Tailwind colour names: `bg`, `surface` (+`surface-2`, `surface-3`), `ink`, `muted`, `faint`, `border`
(+`border-strong`), `primary` (+`hover`, `soft`), `brand` (coloured text on the page), `success|warning|danger|info`
(+`-soft`). Opacity modifiers work (`bg-warning/60`). Light and dark are both defined — **never hard-code a
colour**; check every page in `--theme dark`. Legacy classes (`.bg-brand`, `.glass`, `.text-gradient`,
`.bg-hero-mesh`, `.card-hover`) exist only to keep old pages from breaking: **remove them from any file you
touch.**

## Kit (`@/components/kit`)
`Panel` (titled working area; `PanelLink`; `Facts`), `Table/THead/TBody/Tr/Th/Td`, `Badge` (tones),
`Button` / `ButtonLink` (variants primary|secondary|soft|ghost|danger, sizes sm|md|lg|icon),
`Input`, `Select`, `Textarea`, `FormRow`, `SearchField`, `Segmented`, `inputClass/selectClass/textareaClass`,
`Tabs` (+`tabPanelProps`), `Popover`, `ConfirmDialog`, `EmptyState/ErrorState/NoResults/PermissionDenied`,
`ProgressBar/ProgressRing`, `Skeleton*`, `useToast()` (`.success/.error/.info`), `Tooltip`, `Avatar`, `ThemeToggle`.
Legacy but fine: `@/components/ui` (`Field`, `Alert`), `@/components/dialog` (`Dialog`), `@/components/page`
(`PageHeader`). Prefer the kit for new work; restyle or replace legacy usage in the files you own.
`@/lib/format` has `relativeTime`, `formatDay`, `percent`, `formatBytes`, `formatMinutes`.
If you need a new shared primitive, ADD a new file under `src/components/kit/` (don't change the behaviour of
existing kit files — other people are using them right now).

## Layout
`(app)/layout.tsx` provides sidebar, top bar and `PageFrame`. Normal pages are a centred column
(max 1200px, `px-4 sm:px-6 py-5`); build them as `PageHeader` + one or two column grid of `Panel`s
(`grid gap-4 lg:grid-cols-[minmax(0,1fr)_21rem]`). Pages that need the whole area (like chat) are listed in
`shell/page-frame.tsx`'s `full` check. The "current course" is the cookie `mindnest_course` (see
`shell/course.ts`, read server-side with `cookies()` and validated against the student's subjects — see
`app/(app)/chat/page.tsx`); pages that list per-course things should default to it but let the student see all.

## i18n
Catalogs: `src/i18n/messages/{en,hi,gu}.json`. **Do not edit them by hand.** Create a module
`/tmp/cmp/i18n/k_<NN>_<yourarea>.py` (use your assigned number) containing
`KEYS = {"key": ("English", "हिन्दी", "ગુજરાતી"), ...}` and run `python3 /tmp/cmp/i18n/apply.py` (idempotent; it
merges every module, so re-run it after other people add theirs and before you type-check). Keys are typed
(`MessageKey`), so `tsc` fails on a missing key. Reuse existing keys where the meaning is the same
(`grep` the en.json). Write natural Hindi and Gujarati (not transliteration); keep `{placeholders}` intact.
Old keys that no longer have a caller can stay.

## Looking at the app (the dev environment is already running — don't restart anything)
* Web: http://localhost:3000 (next dev, hot reload). API: http://localhost:8000 (uvicorn, **no reload**: if you
  change Python code, tell me in your report; for backend work use pytest, and for UI against new endpoints
  ask for a restart by stopping — see "Backend" below).
* Signed-in demo student: `raj.demo@example.com` / `Correct-Horse-9` (data: 3 courses — Operating Systems
  CS301, Linear Algebra MA201, Organic Chemistry CH210 — with materials (real PDFs in a fake S3 on :9000),
  planner tasks, exams, assignments, 4 quiz attempts, 3 conversations). Ids are in `/tmp/seed.json`.
  Create more data with the real API (log in with `requests`) or SQL (psql `postgresql://mindnest:mindnest@localhost:5432/mindnest`,
  the owner role bypasses RLS). Add rows; don't delete rows you didn't create.
* Screenshots: `python3 /tmp/shot.py <name> <path> [--w 1440 --h 900 --theme dark --lang hi|gu --course <id>
  --actions "<async playwright code using page>"]` → `/tmp/shots/<name>.png` (view with the Read tool). The
  app's scroll area is inside `<main>`, so use a tall `--h` (e.g. 1800) to see a whole page. Prefix your names
  with your area. First compile of a page in dev takes 10–40s; the script waits.
  Look at: desktop light, desktop dark, 390px phone, hi, gu — and every state you built (empty, loading,
  error, filled, dialogs open). Headless Chromium cannot draw PDFs in iframes (real Chrome can).
* Mocking the model: there is no LLM key. `/tmp/stream_test.py` shows how to intercept the SSE endpoint with
  Playwright when you need a streamed chat answer.
* Type-check: `cd /home/claude/web && npx tsc --noEmit` (other people's half-done files can produce errors in
  files you don't own — only fix your own). Lint-ish rule: no `any`, no unused code.

## Backend (when the brief needs something the API doesn't have)
Python in `/home/claude/work/services/api/mindnest_api/routes/*.py` (FastAPI, raw SQL via
`sqlalchemy.text`, `AuthUser`, `UserDbDep` / `db.session()` for per-user RLS — copy the patterns in
`dashboard.py`, `materials.py`, `quizzes.py`). Add a new route module and register it in `main.py` (additive
edit only). Schema changes: only if your area has an assigned placeholder migration (see your brief); edit
its `UPGRADE`/`DOWNGRADE` lists with `sa.text` statements, include RLS policies like the other tables,
then `cd /home/claude/work && alembic upgrade head`. Tests: `services/api/tests/test_<area>.py` using the
`make_user` fixture (see `test_dashboard.py`), run with `cd /home/claude/work && python -m pytest
services/api/tests/test_<area>.py -q`; `ruff check services` and `mypy services/api` must stay clean for
files you touched. Do **not** regenerate `packages/contracts/openapi.json` (the lead does it at the end).
The dev API does not auto-reload: after your pytest passes, run `/tmp/restart_api.sh` (applies migrations,
restarts uvicorn on :8000, takes ~5s; other people share it, so only call it when your change is tested) and
then exercise the new endpoints from the real UI.

## Files you must not rewrite wholesale
`src/app/globals.css`, `tailwind.config.ts`, `src/components/kit/*` (existing), `src/components/shell/*`,
`src/components/dashboard/*`, `src/components/chat/*`, `src/i18n/*` (except via the module + apply.py),
`src/lib/types.ts` and `src/lib/api.ts` (additive `Edit`s only — never overwrite the file).

## Done means
`tsc` clean for your files; every state looked at in a real rendered screenshot in light + dark and at 390px,
plus hi and gu; interactions exercised with Playwright (click through, submit, error path); backend tested;
no leftover purple-era classes (`bg-brand`, `glass`, `text-gradient`, `bg-hero-mesh`, `shadow-glow`,
`rounded-3xl` etc.) in the files you touched; no hard-coded strings.
