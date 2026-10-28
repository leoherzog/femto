# femto parity harness

This folder proves that femto reproduces Pico CSS 2.1.1. The harness loads fixture pages in the real
Chrome, Firefox and Safari on the macOS test machine, once with a 2.1.1 reference stylesheet and once
with femto, and compares every computed style, every token and every interactive state. Any
difference that is not registered in `tests/divergences/` fails the run.

Nothing here ships. `PLAN.md` (Parity harness, macOS test rig) is the spec.

## Quick start

```sh
uv run tests/run.py rig                                  # verify the three browsers on this machine
uv run tests/run.py selftest                             # prove detection with negative controls
uv run tests/run.py self --pages kitchen-sink.html       # 2.1.1 against itself (criterion 1)
uv run tests/run.py fast --modules forms/basics          # a module agent's check (hybrid build)
uv run tests/run.py full                                 # the whole matrix, three browsers
uv run tests/run.py coverage --css /tests/reference/femto.css --entry default
uv run tests/run.py registry                             # validate tests/divergences/
```

Every run writes `tests/results/<run-id>/result.json`, `summary.txt` and `log.txt`, prints the
summary, and exits 0 only when nothing unregistered differs and no harness error occurred.

Python runs only through `uv`: `tests/run.py` carries PEP 723 metadata pinning
`selenium==4.51.0` and `pillow==13.0.0`. Selenium Manager fetches chromedriver and geckodriver into
`~/.cache/selenium`; Safari uses `/usr/bin/safaridriver`.

## Layout and ownership

| Path | Owner | Contents |
|---|---|---|
| `README.md` | harness | this file |
| `run.py` | harness | CLI: `uv run tests/run.py <mode> [options]` |
| `harness/` | harness | Python modules, `page.js` (fixture loader), `differ.js` (in-page collector and differ), `host.html` (top-level host page), `probe.html` (rig probe) |
| `variants.json` | harness | comparison presets |
| `divergences/` | harness (schema, seeds); module agents add entries | divergence registry, `schema.json` |
| `pages/` | fixtures | fixture pages, `pages.json` manifest, `assets/` |
| `reference/` | refs | renamed 2.1.1 CSS (gitignored, rebuilt from tag `v2.1.1` by `run.py` when missing) and committed option references, provenance in `reference/README.md` |
| `sections.json` | refs | 2.1.1 banner sections of the default entry mapped to femto files |
| `static_checks.py` | refs | mechanical checks for acceptance criteria 4 to 7, 10, 11 |
| `build/`, `results/` | generated | gitignored |

Python modules in `harness/`: `cli.py` (modes and planning), `matrix.py` (presets, pages, full-matrix
reductions), `runner.py` (worker pool, session start-up and rig verification), `compare.py` (one
comparison cell, state input, pixel diff), `browsers.py` (drivers and the color-scheme, pointer and
keyboard mechanisms), `registry.py`, `build.py` (reference splitting and hybrid entries),
`report.py`, `coverage.py`, `negative.py` (selftest), `rig.py`, `locks.py`, `server.py`, `paths.py`.

## How one comparison works

A **cell** is one comparison: browser × preset × page × page variant × scheme leg × width ×
direction, with a reference stylesheet list and a test stylesheet list.

1. The harness serves the repository root at `http://127.0.0.1:<free port>/` (text types carry
   `charset=utf-8`; every 404 except `/favicon.ico` becomes a harness error).
2. Each browser session opens `/tests/harness/host.html` once. The host page holds `differ.js` and a
   20 px strip where the pointer parks, outside the fixture.
3. For each side (reference, then test) the host creates a **fresh iframe** of exactly the cell's
   width and 800 px high, loads `/tests/pages/<page>?css=...&theme=...&dir=...&class=...`, and waits
   for `window.__femto.ready` (every stylesheet in the document and in shadow roots loaded or failed).
4. It checks the environment inside the fixture document: `innerWidth` equals the width, and
   `(width: Wpx)` matches both through `matchMedia` and through a temporary CSS media rule;
   `prefers-color-scheme` matches the leg through `matchMedia` and through CSS; `data-theme` on
   `<html>` is what the leg asked for. Any mismatch is a harness error.
5. It finishes transitions and finite animations, pauses infinite ones at `currentTime` 0, collects
   every element's computed style and pseudo-elements, collects and resolves tokens, and keeps the
   snapshot in the host page's memory.
6. On the test side it diffs against the reference snapshot **in the page**, matches each difference
   against the registry entries that apply to the cell, and returns only counts and the unregistered
   records (up to `--max-records`, default 300) to Python.
7. Interactive states are replayed with real input on both sides (see States).
8. Both sides are screenshotted (iframe viewport; `[aria-busy=true]` and `video[controls]`,
   `audio[controls]` covered on both sides) and pixel-diffed.
   Pixel differences are reported, never gating.

### Collection

- Every element in tree order, open shadow roots included (an element, then its shadow tree, then
  its light children). `head`, `meta`, `title`, `script`, `link`, `style`, `template`, `base` and
  `noscript` are skipped, so the different number of `<link>`s on each side never shifts indexes.
- Each element is keyed by its document index, with a readable label
  (`input#fb-text[type=text] "..."`) and a CSS path from its `[data-module]` wrapper
  (`[data-module="forms/basics"] > form > input#fb-text`, `>>>` marks a shadow boundary).
- Properties: every name `getComputedStyle()` enumerates, minus custom properties (Chrome 157: 480,
  Firefox 160: 394, Safari 27: 419 longhands; none of them enumerate shorthands).
- Pseudo-elements: `::before` and `::after` on every element (when `content` computes to `none` or
  `normal` on both sides it is skipped; on one side only it is a difference on `content`);
  `::marker` on `li`, `summary` and anything whose `display` contains `list-item`; `::placeholder`
  on elements with a `placeholder` attribute; `::file-selector-button` on `input[type=file]`;
  `::backdrop` on every `dialog`. Each session verifies on `harness/probe.html` which of these
  `getComputedStyle()` supports; an unsupported one is skipped and recorded as the skipped check
  `pseudo:<name>`, which must be registered (kind `skipped-check`, category `browser-limit`).
- Animations: `document.getAnimations()` plus each shadow root's. Finite animations and transitions
  are `finish()`ed, infinite ones paused at 0, three rounds until nothing changes. Chrome and Safari
  run `::file-selector-button` transitions on a UA shadow element that `getAnimations()` does not
  return, so the harness cancels them with a transient
  `input[type=file]::file-selector-button { transition: none !important }` and removes it again
  (cancelling jumps to the end value; removing it changes no animated value, so nothing restarts).

### Tokens

- **Names**: every `--femto-*` custom property declared in either side's stylesheets: a CSSOM walk
  through `document.styleSheets`, `@import`ed sheets, nested rules, conditional rules,
  `@property`, and every shadow root's (and adopted) sheets.
- **Surface**: names only in the reference are `surface-missing`, names only in the test are
  `surface-added`. Both must be registered. Resolution is compared only for names on both sides.
- **Anchors**: `html`, `body`, every `[data-theme]` element, every `article`, `dialog` and
  `[data-module]` wrapper, and each shadow host's shadow root. When an anchor element is itself a
  shadow host, its probes go in its shadow root: a light-DOM child of a host is unslotted, and
  `getComputedStyle()` returns empty values for it (found in Phase 1 on `tokens-schemes.html`, where
  a host's own anchor read every token as `""` whenever its probe group started there).
- **Resolution**: under each anchor the harness appends a hidden `femto-probe` container with
  `all: initial; color-scheme: inherit; display: none` and one child per token whose inline style
  sets each probe property to `var(<token>)`: `color`, `background-color`, `border-top-color`,
  `outline-color`, `box-shadow`, `background-image`, `filter`, `backdrop-filter`, `opacity`,
  `font-size`, `font-family`, `font-weight`, `line-height`, `letter-spacing`, `width`,
  `padding-top`, `margin-top`, `border-top-width`, `border-top-left-radius`, `outline-width`,
  `outline-offset`, `text-decoration-line`, `text-underline-offset`, `transition`, `content`. The
  computed values are compared per token, anchor and probe property (kind `token`). Resolution
  depends only on the anchor's token values and its `color-scheme`, so anchors with the same
  signature share one probe set.
- **Raw text**: `getPropertyValue(<token>)` at each anchor, compared exactly (kind `token-raw`).

### States

Put `data-states="hover focus focus-visible active"` (any subset) on fixture elements. For each
target and state, on both sides, in the same order:

| State | Input | Asserted |
|---|---|---|
| `hover` | scroll the target into view inside the iframe (wait two frames if it scrolled), move the pointer to the centre of its largest hit-testable line box | `:hover` |
| `active` | the same point, pointer down; collect; pointer up at the same point | `:active` |
| `focus` | `element.focus()` | `:focus` |
| `focus-visible` | focus the preceding keyboard-focusable element (or the document), then a real Tab key press; if that misses, the following element and Shift+Tab. Safari uses Option+Tab, because plain Tab skips links and buttons there | `:focus-visible` |

A state that does not match is a harness error (pointer states retry once; a pointer target whose
point lies outside the iframe viewport after scrolling is reported as such and never moved to). A
state a browser can never give an element is a registered skipped check instead: the harness names
it `state:<state>:<tag>[type=<type>]` and skips it only when a `skipped-check` entry matches
(`rig.json` has one: Safari and `:focus-visible` on date-family inputs). Safari's Option+Tab never
lands on `summary` or `input[type=color]`; there, after Tab and Shift+Tab miss, the harness calls
`focus()` right after those key presses, which matches `:focus-visible` (keyboard modality). After the state is
applied the harness finishes transitions, collects the subtree of the target's closest
`[data-module]` ancestor (shadow trees included, so `:focus-within` parents and tooltip
pseudo-elements are caught) and diffs it against the reference snapshot of the same state. Between
states the pointer parks on the host strip and the focused element is blurred.

Activation is cancelled in the fixture document while the harness runs: capture-phase listeners
`preventDefault()` every `click`, `auxclick` and `submit` (no navigation, toggles or submits), and
every `mousedown` on a `select` (otherwise the native picker opens, stays open in Firefox and
swallows later input; so `select:active` is checked without the focus a real click would add).

### Diff rule

Values compare as exact strings, except colors: `rgb()`, `rgba()`, `color(srgb ...)`, hex and
named colors are parsed and compared numerically with a tolerance of 1/255 per channel and 0.004
alpha, and the rest of the value (with each color replaced by a placeholder) must be identical.
Colors inside quoted strings and `url()` are text. No other tolerance exists; the selftest proves
that a 2/255 change is detected and a 1/255 change is not.

## Modes

Common options: `--browsers chrome,firefox,safari`, `--presets`, `--pages`, `--widths`,
`--schemes light,dark,theme-light,theme-dark`, `--dirs ltr,rtl`, `--variants plain,class=...`,
`--no-states`, `--no-shots`, `--workers chrome=2,firefox=2`, `--max-records N`, `--run-id`,
`--label`, `--registry DIR`. Lists are comma-separated, except section titles, which contain commas
and are separated by `;`.

| Mode | What it runs |
|---|---|
| `fast` | For module agents. `--modules forms/basics,...` or `--sections "Basics form elements;Input type file"`: the manifest pages of those modules or sections, Chrome and Firefox, widths 390 and 1280, legs `light` and `dark` (media), ltr plus rtl on pages with `rtl: true`, with states. By default the test side is a hybrid build of the preset's reference with those sections replaced by their femto files; `--direct` compares the preset's own test list instead. A section is replaced as a whole, so every femto file `tests/sections.json` maps to it must exist (Styles needs `tokens/base.css`, `tokens/breakpoints.css` and `layout/elements.css`); missing files stop the run with exit 2. `--kitchen-sink` adds the kitchen sink; `--presets` picks entries (default `default`). Phase 1 example: `fast --sections "Styles;Color schemes;Document"`. |
| `full` | The whole matrix below. Chrome and Firefox run 2 workers each, Safari 1, all at once (subject to the slot lock). `--self` compares every preset's reference against itself; `--control` compares every preset that has hybrid settings (all but `colors`, which has no banners) against its chunk control; `--states-only` keeps only the cells that run interactive states and `--stateless-only` only the others, so a Safari leg can be split into two invocations whose union is the matrix. Command-line filters (`--pages`, `--widths`, ...) cut the matrix and are logged as a cap. |
| `compare` | Direct comparison: `--ref` against `--test` (root-relative lists), or each `--presets` preset's own lists. `--entry` picks pages for `--ref`. Defaults to the fast axes; `--full-widths` and `--all-legs` widen them. |
| `self` | A reference against itself (acceptance criterion 1). |
| `hybrid` | A preset's reference against a hybrid build: `--modules`, `--sections`, or `--control` (no section replaced: the chunk control). Defaults to the fast axes; `--full-widths` and `--all-legs` widen them to every width and leg on every page, with states everywhere, which is far heavier than the full matrix. `--full-plan` instead plans the full matrix's own cells and reductions (below) for `--presets` (default `default`), with the hybrid build as the test side, and takes the same command-line filters as `full`. Use `--full-plan` for a phase's wide check: on Phase 1's sections it runs 3,296 cells in Chrome and Firefox where `--full-widths --all-legs` ran 9,576 per preset. |
| `coverage` | `--css <stylesheet> --entry <entry>`: selector coverage (below). |
| `rig` | Starts each browser and reports versions, pseudo-element support, input verification, widths, color-scheme mechanisms and screenshot timing to `results/<run>/rig.json`. |
| `selftest` | The negative controls (below), each a real `run.py` subprocess. `--cases`, `--browsers`, `--no-states`. |
| `registry` | Validates `tests/divergences/` and lists the entries. |
| `build` | Writes a hybrid entry (`--preset`, `--modules`/`--sections`/`--control`) and prints its URL. |

### Scheme legs

| Leg | `prefers-color-scheme` | `data-theme` on `<html>` |
|---|---|---|
| `light` | light | none |
| `dark` | dark | none |
| `theme-light` | dark | light (forced light on a dark OS) |
| `theme-dark` | light | dark (forced dark on a light OS) |

Nested `[data-theme]` islands in every fixture are checked in every leg. Safari cannot emulate the
media query (see Rig notes): it runs the OS scheme in every leg, skips the leg whose media differs
from the OS when no `data-theme` is set, and records `media:<scheme>` as a skipped check, registered
in `divergences/rig.json`. Every Safari gate therefore runs twice, once with macOS light and once
with macOS dark (see Safari dark pass); together the two passes run every leg.

### Safari dark pass

Agents never change the macOS appearance, so the owner switches it:

```sh
osascript -e 'tell application "System Events" to tell appearance preferences to set dark mode to true'
```

Then run the gate's Safari commands again, for example Phase 0's:

```sh
uv run tests/run.py full --self --browsers safari --stateless-only
uv run tests/run.py full --self --browsers safari --states-only
uv run tests/run.py full --control --browsers safari --stateless-only
```

Check that every session's `log.txt` line says `OS scheme dark` and that the skipped checks show
`media:light`, not `media:dark`; a session that read a light OS skips the dark cells instead of
passing them. Then the owner switches back with `set dark mode to false`. The light-leg selftest
controls (`color-2-of-255` and the others pinned to `--schemes light`) skip on a dark OS, so run
`selftest --browsers safari` in the light pass; in the dark pass only `self`, `chunk-control`,
`dark-only-token` and `theme-dark-only` compare anything.

### The full matrix and its reductions

Widths: one inside each band, 375, 640, 900, 1150, 1400 and 1700, plus 575/576/577, 767/768/769,
1023/1024/1025, 1279/1280/1281 and 1535/1536/1537 (21 widths). Every reduction is printed as a
`cap:` line in `log.txt` and stored in `result.json` (`caps`):

- Entry `default`: the kitchen sink and pages with `"media": true` run all 21 widths in all four
  legs; other pages and non-plain page variants run widths 390 and 1280 in all four legs.
- rtl runs only on pages with `"rtl": true`: band widths for the kitchen sink and media pages, 390
  and 1280 otherwise, in legs `light` and `theme-dark`.
- Interactive states and screenshots run at widths 375 and 1280 for wide pages (every ltr leg),
  every width for the others, and 1280 for rtl.
- `colors`: its pages at 1280 in every leg.
- Options (`option-responsive-spacings`, `option-no-transitions`, `option-fixed-typography`): the
  kitchen sink at all widths in `light` (states at 1280), and 390 and 1280 in the other legs; plus
  every other page of the entry, in every page variant, at 1280 in `light` (with states) and
  `theme-dark`. The other pages are needed because `femto.no-transitions.css` changes rules the
  kitchen sink cannot hold: the `modal-is-opening`/`-closing` animations (`classes-modal.html`
  variants), the open dropdown list, and the left and right tooltip slides in hover.
- Themes (`theme-<color>`, 20 presets): the kitchen sink only, 1280, every leg, with states. Every
  rule whose declarations differ between a theme reference and `femto.css` has a selector that
  matches on the kitchen sink (checked 2026-10-27).

That is 2,089 cells per browser, 606 of them with states (2,085 and 602 in `--control`, which has
no `colors` cells): `default` 1,648, `colors` 4, each option 119 and each theme 4. Counted on
2026-10-27 with the harness's own planner (`harness.cli.plan`, which starts no browser) after the
classless presets were removed. See Measured throughput.

## Presets: `tests/variants.json`

`presets.<name>`: `entry` (selects pages whose manifest `entries` include it), `ref` and `test`
(root-relative stylesheet lists, loaded in order), optional `group` (`option`, `theme`) and
`hybrid` (`sections`: the `tests/sections.json` entry used to split `ref`; `append`: URLs imported
after the chunks once any section is replaced, for theme and option files). There are 25 presets:
`default`, `colors`, 3 options and 20 themes.

- `default`: `tests/reference/femto.css` against `css/femto.css`.
- `colors`: `tests/reference/femto.colors.css` against `css/femto.colors.css`.
- `option-<option>`: `tests/reference/options/femto.<option>.css` against `css/femto.css` plus
  `css/options/<option>.css`.
- `theme-<color>`: `tests/reference/femto.<color>.css` against `css/femto.css` plus
  `css/themes/<color>.css`. Azure is built into `tokens/`, so its reference is `femto.css` itself.

## Hybrid builds and `tests/sections.json`

`harness/build.py` splits a reference at its banner comments (`/**`, one or more ` * <title>` lines,
` */`) into `tests/build/chunks/<reference>/NN-<slug>.css`, with a `(preamble)` chunk for the
`@charset` and copyright comment, and checks that the chunks reassemble the file byte for byte. A
hybrid entry `tests/build/hybrid/<reference>/<name>.css` `@import`s the chunks in order, replacing
the chosen sections with their femto files from `tests/sections.json`
(`entries.<entry>.sections[].files`, relative to `files_root`), plus the preset's `append` files.
The banner titles of the reference must equal the sections of the chosen entry, in order. Missing
femto files stop the run before any browser starts. With nothing replaced it is the chunk control,
which must compare clean. Files are written atomically and only when they change, so concurrent
runs can share them.

The name is `hybrid-<section slugs joined by +>`, followed by `--<appended file slugs>` when the
preset appends files (`/css/` and `.css` dropped; a long tail is cut and hashed), so the name fixes
the content: for example `hybrid-styles+color-schemes+document.css` for `default` and
`hybrid-styles+color-schemes+document--themes-azure.css` for `theme-azure`. Until Phase 1's review
the name left out the append list, so `default` and `theme-azure`, which share
`tests/reference/femto.css`, wrote one file, and in a run planning both, the `default` cells also
loaded `themes/azure.css`. A run now stops with a build error if it would write one hybrid path with
two contents.

## Fixture page contract

- Static HTML5, `<html lang="en">` with no `data-theme`, `dir` or `class` in the file. `<head>`
  holds `<meta charset="utf-8">`, the viewport meta, a `<title>`, and exactly one script:
  `<script src="/tests/harness/page.js"></script>`. No other stylesheets or `<style>`, no inline
  `style` attributes unless a module needs one, no network resources (use `data:` URIs or
  `tests/pages/assets/`), no web fonts, no other scripts. Deterministic: no randomness, time or
  autoplay.
- `page.js` reads the query string: `css` (comma-separated root-relative URLs, written as blocking
  `<link rel="stylesheet">`s with `document.write`), `theme=light|dark` (`data-theme` on `<html>`),
  `dir=rtl`, `class` (comma-separated classes on `<html>`). After `DOMContentLoaded` it sets
  `.indeterminate = true` on every `[data-indeterminate]`, calls `showModal()` on every
  `dialog[data-show-modal]`, and gives every `[data-shadow]` host an open shadow root holding the
  same stylesheets followed by a clone of its `<template>` child. `window.__femto.ready` resolves
  when every stylesheet has loaded or failed; `window.__femto.errors` lists failures (a failed
  stylesheet is a harness error).
- Content sits in `<div data-module="<module id>">` wrappers. Landmark pages put `data-module` on
  `body > header`, `main` and `footer`.
- Every page has a light island `<div data-theme="light">` and a dark island
  `<div data-theme="dark">` inside its wrapper, repeating the module's color-bearing elements.
- `data-states` as above: one target per distinct selector and state combination. Avoid
  `focus-visible` on a radio that is not the first or checked one of its group (Tab cannot land on
  it), and pointer states on elements covered by an open modal's backdrop.

## Manifest contract: `tests/pages/pages.json`

A JSON array with one object per page: `page` (file name), `modules` (module ids), `sections`
(2.1.1 banner titles), `entries` (`default` or `colors`),
`variants` (query variants besides theme and dir; `{}` is the plain load, e.g.
`{"class": "modal-is-open"}`; a variant may not set `css`, `theme` or `dir`), `rtl` (the module has
`[dir=rtl]` rules), `media` (its CSS has media queries), and optional `stateless_variants`
(variant labels whose cells never run states, because the variant puts the state targets where no
input reaches them: `classes-modal.html` in `class=modal-is-open,modal-is-closing` ends the closing
animation with the article at `translateY(-100%)`, above the viewport). Variant labels in results
and in the registry are `plain` or `k=v` pairs joined by `&`, e.g.
`class=modal-is-open,modal-is-opening`.

## Divergence registry: `tests/divergences/`

Each `<folder>-<name>.json` (plus `tokens.json`, `rig.json`, ...) is a JSON array of entries;
`schema.json` is the JSON Schema. `uv run tests/run.py registry` validates them, and every run
validates them again (a registry error is a harness error).

| Field | Meaning |
|---|---|
| `id` | unique across all files, `^[a-z0-9][a-z0-9._-]*$` |
| `module` | module id (`forms/basics`), or `tokens`, `rig` |
| `kind` | `style`, `token`, `token-raw`, `surface-added`, `surface-missing`, `skipped-check` |
| `selector` | `style` (required): a CSS selector the differing element must match **in the test document** (`*` for any). `token`, `token-raw` (optional): a selector the anchor element must match |
| `token` | token kinds (required): name or `/regex/` |
| `pseudo` | `style`: `""` for the element itself, `::before`, `::after`, `::marker`, `::placeholder`, `::file-selector-button`, `::backdrop`, `*` or `/regex/`; omitted means any |
| `property` | `style`: longhand; `token`: the probe property; exact, `*` or `/regex/` |
| `reference`, `femto` | the two values: exact (compared with the color tolerance), `*` or `/regex/` |
| `check` | `skipped-check` (required): `media:dark`, `media:light`, `pseudo:::backdrop`, ...; exact or `/regex/` |
| `where` | optional filters, all of which must match the cell: `browsers`, `presets`, `entries`, `variants` (matches the preset name, entry, page variant label or comparison kind `direct`/`self`/`hybrid`/`control`), `pages`, `schemes` (legs), `widths` (integers or `{"min", "max"}`), `dirs`, `states` (`base`, `hover`, `focus`, `focus-visible`, `active`) |
| `category` | `natural-fix`, `dropped-hack`, `new-token`, `option-mechanism`, `browser-limit` (skipped checks must use `browser-limit`) |
| `reason` | non-empty |
| `notes` | optional |

Patterns: a plain string matches exactly, `*` anything, `/body/flags` is a JavaScript regular
expression (flags `i`, `m`, `s`, `u`). A difference is registered when at least one entry matches;
every entry that matches counts a hit. The summary lists entries with no hit in the run as unused
(informational; in a fast run most entries are naturally unused). Unregistered differences, and
unregistered skipped checks, fail the run.

Seed entries (from PLAN, written broadly; later phases tighten them): `tokens.json`
(`tokens-light-dark-raw-text`, `tokens-group-island-focus-ring`, `tokens-root-user-override-style`/`-token`
for a future `user-root-override` preset, `tokens-new-names`), `components-group.json` (the island
focus-ring style), `forms-basics.json` (Firefox focus ring after dropping `:-moz-focusring`), and
`rig.json` (`safari-no-media-dark`). Phase 1 narrowed the tokens and island entries to what its runs
reported. Its review added `tokens-author-color-scheme-dark` and `-light`: an author's inline
`color-scheme` on an element without `data-theme` now switches femto's `light-dark()` colors in that
subtree, where 2.1.1's literals kept the page's colors (fixtures `#cs-dark` and `#cs-light` in
`tokens-schemes.html`). Its second round added `tokens-own-data-theme-style`, `-token` and `-raw`
for Decision 12: color tokens are declared once on `:root, :host`, so an element that carries
`data-theme` itself (`<button data-theme=dark>`, the inputs under "Elements with their own
data-theme" in `tokens-schemes.html`) keeps its own color tokens in its scheme, where 2.1.1
redeclared the page's. It also pinned the two island focus-ring entries to a single-ring value and
moved the author `color-scheme` entries to `natural-fix`. After the third round, the Decision 12
entries were narrowed to the 11 tokens, the color, background and box-shadow properties and the
page that runs report, and `tokens-schemes.html` gained a dark `select`, `textarea`, `h1`, links
and a `role=button` so each element kind in their selector is exercised (a `summary` carrying
`data-theme` shows no difference, so it is not listed). `tokens-dark-shadow-host-input-focus`
records the one flat `input:is(...)` rule that replaces 2.1.1's three per-scheme copies of
`--femto-form-element-focus-color`: in a shadow root whose host carries `data-theme=dark`, a
focused checkbox or radio now draws the `primary-focus` ring like every other one (fixtures
`shadow-dark-host-c1` and `shadow-dark-host-r`, with `data-states="focus"`).
The owner then chose that a shadow host carrying `data-theme=dark` is dark (Decision 12): the
forced-dark rules add `:host([data-theme=dark])`, and `tokens-dark-shadow-host-contrast-filter`
records its one harness-visible effect, the contrast summary and busy contrast icons in the
`shadow-dark-host` template taking the dark filter.

## Output

`tests/results/<run-id>/` (run id `YYYYMMDD-HHMMSS-<mode>-<pid>` unless `--run-id`):

- `result.json`: `run_id`, `mode`, `argv`, `git`, `status` (`PASS`/`FAIL`), `duration_s`,
  `totals` (cells per browser, differences, unregistered, registered, harness errors, unregistered
  skipped checks, pixel-diff cells, states run), `caps`, `rig` (one record per session: versions,
  launch time, OS scheme, pseudo-element support, input checks, whether states could run),
  `harness_errors`, `skipped_checks` (check, browser, cells, matching entries), `registered_by_entry`,
  `registered_samples` (up to 3 records per entry), `unused_entries`, `pixels`, `groups` (per
  browser, preset and page), and `cells` (every cell with its unregistered records, registered counts,
  errors, timings, element/token/anchor counts and pixel result).
- `summary.txt`: status line, unregistered differences first (5 records per cell, 40 cells), harness
  errors, skipped checks, registered counts per entry, unused entries, matrix caps, pixel diffs,
  then one line per browser, preset and page.
- `log.txt`: one line per cell as it finishes.
- `shots/`: for each cell with a pixel difference, the reference and test screenshots and a mask.

Exit status: 0 PASS; 1 unregistered differences, harness errors, unregistered skipped checks or
registry errors; 2 a setup error before any browser started (missing reference, femto file,
manifest or sections entry).

Unregistered record shapes: `style` {`state`, `el`, `label`, `path`, `pseudo`, `prop`, `ref`,
`test`}, `token` {`anchor`, `label`, `path`, `token`, `prop`, `ref`, `test`}, `token-raw`
{`anchor`, `label`, `path`, `token`, `ref`, `test`}, `surface-added`/`surface-missing` {`token`}.

## Selector coverage

`uv run tests/run.py coverage --css /tests/reference/femto.css --entry default [--pages ...]` parses
the stylesheet (banner sections, conditional at-rules, nested rules resolved against their parent),
strips pseudo-elements and dynamic pseudo-classes from every selector (a `:not()` containing one is
dropped whole, an `:is()`/`:where()` argument left empty becomes `*`), and evaluates it with
`querySelectorAll` in Chrome on every page of the entry, every manifest variant and rtl for rtl
pages, shadow roots included (`:host` selectors count shadow hosts). It reports selectors that match
nothing anywhere, grouped by section, and rules with `:hover`, `:active`, `:focus`, `:focus-visible`
or `:focus-within` whose candidate elements declare no matching `data-states` (hover and active may
come from a descendant; a focus state inside `:has()` counts as focus-within). Output:
`results/<run>/coverage.json` and `coverage.txt`. It is a report and always exits 0.

## Selftest: proving detection

`uv run tests/run.py selftest [--browsers ...] [--no-states]` runs these controls (`--no-states` leaves out the four that need states: `hover-only`, `active-only`, `focus-only`, `focus-visible-only`; stylesheets in
`tests/build/negative/`), each through the real CLI:

| Case | Expectation |
|---|---|
| `self` | the reference against itself: zero differences, no errors |
| `chunk-control` | the reference split at its banners and re-imported: zero differences |
| `color-2-of-255` | h1 color `#2d3138` to `#2f3138`: detected in styles and tokens |
| `color-1-of-255` | `#2d3138` to `#2e3138`: tolerated; only the raw token text differs |
| `hover-only` | `a:hover:not(:active) { word-spacing }`: differs only in the hover state |
| `dark-only-token` | a token changed in the media-dark block only: differs only in leg `dark` |
| `breakpoint-577` | every `(min-width: 576px)` moved to 577px: differs at 576 only, not 575 or 577 |
| `rtl-only` | `html[dir=rtl] h1 { word-spacing }`: differs only in rtl |
| `placeholder`, `backdrop` | a change on that pseudo-element only: detected on it |
| `active-only` | `a:active { word-spacing }`: differs only in the active state (needs states) |
| `focus-only` | `a:focus { word-spacing }`: differs in focus (and in focus-visible, which is also `:focus`, and in active where a press focuses links), never in base or hover (needs states) |
| `focus-visible-only` | `a:focus-visible { word-spacing }`: differs in the Tab-driven focus-visible state (and in focus where programmatic focus is visible), never in base, hover or active (needs states) |
| `theme-dark-only` | `html[data-theme=dark] h1 { word-spacing }`: differs only in leg `theme-dark` |
| `variant-only` | `html.modal-is-open body { word-spacing }`: differs only in the `class=modal-is-open` page variant |
| `after-only`, `before-only`, `marker-only`, `file-selector-button-only` | a change on that pseudo-element only (`outline-offset`, or `color` for `::marker`): detected on it |
| `shadow-only` | `:host { accent-color }` (it applies only from the stylesheets inside shadow roots): differs on the shadow hosts and inside the shadow trees only |
| `token-surface` | a token only the test side declares: one `surface-added` record and nothing else |
| `token-resolution` | `--femto-text-selection-color` (used only by `::selection`): only token differences |
| `registry-suppression` | entries for the h1 change absorb exactly the differences the h1-only control produced, and the h2 change stays unregistered |
| `missing-stylesheet` | a 404 stylesheet is a harness error |

## Concurrency and locks

- **Slots**: at most `FEMTO_HARNESS_SLOTS` (default 4) browser sessions run at once on the machine,
  across all harness processes. Each worker (one WebDriver session, including coverage and rig)
  holds a slot for its lifetime and waits, logging once a minute, when all are taken.
- **Safari**: one Safari session at a time machine-wide (`safari.lock`). Only the harness starts
  Safari, and only through this lock.
- **Driver start**: WebDriver start-up is serialized (`driver-start.lock`), because concurrent
  Selenium Manager runs corrupt `~/.cache/selenium/se-metadata.json`.
- Locks are `flock`s on files in `FEMTO_HARNESS_LOCK_DIR` (default `~/.cache/femto-harness/locks`);
  each holds the pid and label of its owner and is released when the process exits.

Environment variables: `FEMTO_HARNESS_SLOTS`, `FEMTO_HARNESS_LOCK_DIR`, `FEMTO_CHROME_BINARY`
(default `/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta`),
`FEMTO_FIREFOX_BINARY` (default `/Applications/Firefox.app/Contents/MacOS/firefox`),
`FEMTO_SAFARIDRIVER` (default `/usr/bin/safaridriver`).

## Rig notes

Verified on 2026-10-27 on this machine (macOS, 10 CPUs, 16 GB, one 1920×1080 display at device
pixel ratio 1, appearance Light) with Google Chrome Beta 157.0.8103.15 and chromedriver
157.0.8103.15, Firefox 160.0b1 and geckodriver 0.37.1, Safari 27.0.1 and its safaridriver, Selenium
4.51.0. `uv run tests/run.py rig` repeats the checks and writes `rig.json`.

**Chrome Beta (headless).**
- Options: `--headless`, window 1800×1000 (inner 1800×857), `--force-device-scale-factor=1`,
  `--force-color-profile=srgb`, `--hide-scrollbars`, no background throttling.
  `Emulation.setFocusEmulationEnabled` keeps `:focus` working.
- `prefers-color-scheme`: CDP `Emulation.setEmulatedMedia` applies inside the same-origin iframe
  (checked with `matchMedia` and a CSS media rule in the fixture document). It overrides the
  iframe's own rule that its `prefers-color-scheme` follows the embedding element's used
  `color-scheme`, which is why the host leaves the iframe at `color-scheme: normal`.

**Firefox beta (headless).**
- `prefers-color-scheme`: pref `layout.css.prefers-color-scheme.content-override`, an integer:
  0 dark, 1 light, 2 follow the system (the default), 3 follow the browser theme. The harness sets it
  at runtime from the chrome context, which needs geckodriver's `--allow-system-access` (passing
  Firefox's `-remote-allow-system-access` as a capability argument is rejected). The new value
  reaches content asynchronously (5 to 11 ms measured), so the harness polls `matchMedia` in the host
  page before loading the fixture. Within one session the pref is switched per cell; cells are
  sorted by media to keep switches rare.
- An iframe's `prefers-color-scheme` follows its embedding element's used `color-scheme`
  (`color-scheme: light` on the iframe element gives light even with the pref at dark; `normal`
  follows the pref). The host keeps `normal`.
- Window 1800×1000 gives an inner 1800×915.

**Safari (visible, serialized).**
- Starts in about 1.4 s; window 1800×1000 at y 30, inner 1800×948. The iframe gives exact widths
  (375, 577, 1700 verified), so Safari's minimum window width never matters.
- No `prefers-color-scheme` emulation. The OS scheme is read with `matchMedia` in the host page at
  session start (Light here). An iframe whose element has `color-scheme: dark` reports dark through
  `matchMedia`, but its stylesheets' media queries and `light-dark()` still follow the OS, so that
  is not usable as emulation. The other media leg is a registered skipped check.
- All six pseudo-elements are readable with `getComputedStyle()`.
- Pointer input, focus and `:focus-visible` need the Safari window visible and focused. For most
  of this date the screen was locked (`lsappinfo front` reported `loginwindow`): the page reported
  `visibilityState: hidden` and `document.hasFocus() == false`, W3C pointer actions dispatched no
  DOM events at all, keyboard actions reached `body`, `requestAnimationFrame` never ran, and a
  `::file-selector-button` transition never advanced (the transient `transition: none` handles that).
  `getComputedStyle`, `getAnimations().finish()` and element screenshots all worked.
- While the screen was briefly unlocked, a Safari session passed the rig probe's input checks and
  ran every state of `classes-buttons.html` (hover, active, focus and focus-visible through
  Option+Tab on buttons; 82 state applications per cell, two cells) with no error and no difference.
  Shortly after, another app came to the front: from then on every state failed to match, until the
  session stopped answering (each command hung until the HTTP timeout). Afterwards new sessions
  were refused with "The Safari instance is already paired with a different session" until the
  orphaned `Safari --automation` instance was terminated.
- A false `hasFocus()` is not always a lost window. Each fixture load replaces the iframe, and when
  the old iframe held focus (after any focus state) Safari leaves the host document without focus:
  `document.hasFocus()` turns false although the window is key and input still arrives. Found on
  2026-10-27 by the prove run: without a fix every state cell after the first focus state was
  skipped. The harness now calls `window.focus()` in the host page first (which cannot make a
  window key behind another app or a lock screen), then asks safaridriver to switch to the
  session's window, and only then gives up. It also terminates any leftover `--automation` Safari
  before starting a session (it holds the Safari lock, so none can be live): a reused instance
  keeps the dead session's windows and opens the new one behind them.
- Real input disturbs Safari states: during the proving runs the owner looked in over Screen
  Sharing, and in the cells that ran meanwhile hover, focus and focus-visible stopped matching on one
  side or both (never a false difference). safaridriver's synthesized input does not reset the
  `HIDIdleTime` of `IOHIDSystem`, but local and Screen Sharing input do. So when a Safari states
  cell has state errors and `HIDIdleTime` is shorter than the cell took, the harness logs "real input
  during the cell", waits until the machine has been idle for 10 s (at most 10 minutes) and runs the
  cell once more; the result records `retried_after_input`.
- So the harness checks `visibilityState` and `hasFocus()` before every Safari cell that asks for
  states. When they do not hold, it skips that cell's states and reports a harness error ("interactive
  states not run"), so a Safari run without working input can never pass. WebDriver commands time
  out after 90 s. Before each session the harness terminates leftover `Safari ... --automation`
  processes (only safaridriver starts Safari with that flag; the user's Safari is never touched),
  and a session refused as "already paired" is retried once after terminating them again. Run the Safari leg with the screen unlocked, the automation window in
  front, and nobody using the machine; or pass `--no-states` and accept that Safari states stay
  unverified.

**All three.**
- The iframe gives `innerWidth` equal to the width and `(width: Wpx)` matching in both `matchMedia`
  and CSS at 375, 577 and 1700.
- `getComputedStyle()` returns an empty declaration (length 0) for an unknown pseudo-element, reads
  `::backdrop` on a closed dialog too, and accepts single-colon `:before`.
- Selenium's default pointer move lasts 250 ms; the harness uses duration 0 (32 kitchen-sink states
  went from 5.3 s to 0.4 to 0.6 s per side).
- Headless Chrome and Firefox draw overlay scrollbars that fade after scrolling; screenshots hide
  them (the viewport's and every scroll container's) with a transient `* { scrollbar-width: none }` (plus `--hide-scrollbars` in Chrome).
- Firefox applies `scrollTo()` asynchronously, and a scroll-into-view queued by a keyboard focus can
  land after it; before a screenshot the harness scrolls to the top until the position holds for two
  frames. Pointer states wait two frames after scrolling the target into view.
- Chrome's raster varies by 1/255 in some dark-scheme areas between identical loads, and Chrome
  self runs also show isolated cells above 8/255 (three in Phase 1's gate self run, comparing the
  reference with itself), so isolated cells above 8/255 in hybrid runs are rig noise, not CSS. The
  summary counts pixels off by more than 8/255 separately, and images are saved only for those.
- `select`: pointer down opens the native picker in Chrome and Firefox (`:open`), and Firefox keeps
  it open after release, which made later states nondeterministic until `mousedown` on `select` was
  cancelled.

## Measured throughput

The harness agent's first measurements, on 2026-10-27, on the 4,693-cell matrix of that time (numbers
from `result.json` timings). The proving runs on the 4,969-cell matrix of Phase 0 are in Harness proof
below; the current matrix has 2,089 cells per browser (see The full matrix and its reductions).

| Run | Cells | Wall clock | Notes |
|---|---|---|---|
| `full --self --browsers chrome,firefox` | 9,386 (4,693 each) | 989 s (16.5 min) | 2 Chrome + 2 Firefox sessions; 32,880 states per side; zero differences, zero harness errors. Per cell: Chrome 0.15 s without states, 1.76 s with; Firefox 0.15 s and 1.24 s |
| `full --self --browsers safari --presets default` (screen unlocked at first) | 1,295 of 1,648 before it was stopped | 879 s | Safari 0.15 s per cell without states (754 cells). The two state cells that ran while the window had focus took 3.3 to 3.5 s for 82 state applications (Chrome: 3.2 s for the same cells). Then the window lost focus and the session hung; see Rig notes |
| `full --self --browsers safari --no-states` (screen locked) | 4,693 (3,572 run, 1,121 media-dark skipped) | 1,731 s (28.9 min) | One Safari session on a hidden page; zero differences, zero harness errors, the media-dark skip registered (2,242 cells counting the theme-light half). Screenshot waits fell back to 150 ms timeouts because a hidden page never runs `requestAnimationFrame`; the harness now skips those waits on hidden pages |
| `fast --modules forms/basics` (hybrid) | 32 | 49 s | forms-basics and kitchen sink, Chrome and Firefox, 1,008 states per side |
| `self` on every default page, fast axes | 456 | 276 s | Chrome and Firefox, one session each |
| `selftest` (13 controls) | 13 runs | about 100 s | Chrome and Firefox |

Estimates from those numbers:

- A full direct run in Chrome and Firefox should take about the same 17 minutes as the self run:
  the work per cell does not depend on the stylesheets. Differences add only the records returned.
- A full Safari run (3,572 cells to run, 1,121 media-dark cells skipped, 880 with states) should take
  about 26 minutes: about 1,140 s for the state cells (Chrome's 1,066 s for the same non-dark state
  cells, times Safari's measured 1.07 ratio) plus about 400 s for the other cells at 0.15 s. Running it
  alongside Chrome and Firefox in one `full` invocation takes 5 sessions; with the default 4 slots one
  worker waits for a slot.
- Both are well inside the targets (45 minutes for Chrome and Firefox, 3 hours for Safari), so the
  matrix keeps every width for media pages in every leg rather than cutting further.

## Harness proof

Acceptance criterion 1 (the harness compares 2.1.1 against itself with zero differences in all three
browsers), proved on **2026-10-27** on the test machine: macOS, 10 CPUs, 16 GB, one 1920×1080 display,
appearance Light; Google Chrome Beta 157.0.8103.15 with chromedriver 157.0.8103.15, Firefox 160.0b1
with geckodriver 0.37.1, Safari 27.0.1 with its safaridriver, Selenium 4.51.0. Run ids are folders
in `tests/results/` (gitignored, so they exist only on the test machine). Chrome and Firefox are
the beta channels installed there; that was accepted for this gate.

Later on 2026-10-27, after these runs, the classless and fluid classless presets, references, fixture
page, sections and seed divergence were removed from `tests/` under the amended PLAN (Decision 2), so
the classless rows and commands below are a record of what ran and can no longer be rerun.

### What changed while proving

- **Fixtures.** `content-button.html`: the `input[type=button]` target gains `active`, and a new
  `input[type=file][aria-current=true]` carries `focus` (the Button section's
  `[type=file]::file-selector-button:is([aria-current]...)` selectors had no element).
  `classes-links.html`: the `[role=link].secondary` and `.contrast` targets gain `active`.
  `pages.json`: `classes-modal.html` lists `stateless_variants` (see Manifest contract).
- **Matrix.** Option presets also run every other page of their entry at 1280 (see The full matrix):
  `femto.no-transitions.css` changes nine rules the kitchen sink cannot hold.
- **Safari focus.** Three fixes, each found by a failed proving run (Rig notes and States): `window.focus()`
  before a states cell, a fresh automation instance per session, and `focus()` after Tab for
  `summary` and `input[type=color]`. One registered skipped check: `:focus-visible` on date-family
  inputs (`rig.json`, `safari-no-focus-visible-date-input`).
- **Robustness.** A pointer target outside the iframe viewport is reported instead of crashing the
  WebDriver session; a session start that times out is retried twice; a session whose set-up fails
  is quit; a Safari states cell with state errors during which real input arrived (`HIDIdleTime`) is
  retried once after the machine goes idle. That last one was added after the runs below, which is
  why their disturbed cells were rerun by hand.
- **Modes.** `full --control`, `full --states-only`, `full --stateless-only`.
- **Selftest.** Eleven more controls (`active-only` to `token-surface`), 24 in all.

### Fixture coverage

`uv run tests/run.py coverage --css <reference> --entry <entry>`:

| Reference | Entry | Pages (loads) | Selectors | Match nothing | Dynamic rules without `data-states` | Run id |
|---|---|---|---|---|---|---|
| `femto.css` | default | 43 (57) | 715 | 1 | 0 | `prove-cov2-default` |
| `femto.classless.css` | classless | 35 (44) | 633 | 1 | 0 | `prove-cov2-classless` |
| `femto.fluid.classless.css` | fluid-classless | 35 (44) | 618 | 1 | 0 | `prove-cov2-fluid-classless` |
| `femto.colors.css` | colors | 1 (1) | 802 | 0 | 0 | `prove-cov-colors` |
| `options/femto.responsive-spacings.css` | default | 43 (57) | 740 | 1 | 0 | `prove-cov-opt-responsive-spacings` |
| `options/femto.no-transitions.css` | default | 43 (57) | 685 | 1 | 0 | `prove-cov-opt-no-transitions` |
| `options/femto.fixed-typography.css` | default | 43 (57) | 705 | 1 | 0 | `prove-cov-opt-fixed-typography` |

The one selector left is `progress:indeterminate[value]::-webkit-progress-value` (Progress, under
`prefers-reduced-motion: no-preference`). It cannot match in any browser: a `progress` with a `value`
attribute is never `:indeterminate`. Before the fixture changes the default entry had 4 unmatched
selectors and 3 dynamic rules without states (`prove-cov-default`).

Theme and option presets run the kitchen sink (options also the other pages). Every rule whose
declarations differ between a theme reference and its entry reference (3 or 4 rules per theme, 38
references) has a selector that matches on the kitchen sink. For the option references, only
`femto.no-transitions.css` has rules the kitchen sink does not match: the `modal-is-opening` and
`-closing` animations, the open dropdown list, and the left and right tooltip slides. That is why
option presets now run every page.

### Criterion 1: every reference against itself, full matrix

`uv run tests/run.py full --self --browsers chrome,firefox` and, in Safari, the same matrix split
into `--states-only` and `--stateless-only`. Every preset in `tests/variants.json`: `default`,
`classless`, `fluid-classless`, `colors`, 40 theme presets (20 for the default entry, 20 for
classless), 3 option presets.

| Browser | Run ids | Cells | Elements + pseudo-element snapshots | Style values | Token values | State applications per side | Differences | Harness errors | Wall clock |
|---|---|---|---|---|---|---|---|---|---|
| Chrome | `prove-full-self-cf-2` | 4,969 | 785,690 + 175,992 | 461.6 M | 56.7 M | 17,912 | **0** | 0 | 1,164 s (with Firefox) |
| Firefox | `prove-full-self-cf-2` | 4,969 | 785,690 + 177,598 | 379.5 M | 56.7 M | 17,912 | **0** | 0 | same run |
| Chrome (determinism) | `prove-full-self-chrome-3` | 4,969 | 785,690 + 175,992 | 461.6 M | 56.7 M | 17,912 | **0** | 0 | 1,469 s |
| Safari, state cells | `prove-full-self-safari-states-4` + `-4-rerun` | 1,297 (1,017 run, 279 media-dark skipped, 1 WebDriver error) | 140,710 + 32,209 | 72.5 M | 10.6 M | 14,016 | **0** | 367 in 10 cells, rerun clean (see below) | 1,424 s + 34 s |
| Safari, other cells | `prove-full-self-safari-stateless` | 3,683 (2,839 run, 844 media-dark skipped) | 466,465 + 104,161 | 239.1 M | 33.3 M | 0 | **0** | 0 | 520 s |

Style values are elements and pseudo-element snapshots times the longhands each browser enumerates
(480, 394, 419), base snapshots only; each state application re-collects its module subtree on top.
Token values are tokens times (25 probe properties per anchor group, plus one raw text per anchor).

- **Chrome and Firefox pass.** `prove-full-self-cf-1` (2,577 s, on a machine loaded by another
  workload) also had zero differences, but two harness errors: in `option-responsive-spacings`,
  `classes-modal.html` `class=modal-is-open,modal-is-closing`, the finished closing animation leaves
  the article at `translateY(-100%)`, and with responsive spacings the `.close` link sits above the
  viewport, so the pointer move threw. Fixed by the outside-the-viewport check and by
  `stateless_variants`; `prove-full-self-cf-2` then passed clean.
- **Determinism.** `prove-full-self-cf-2` against `prove-full-self-chrome-3` (same code): all 4,969
  Chrome cells have identical element, pseudo-element, token, anchor, group and state counts and zero
  differences in both. Only screenshot noise varies (cells with pixels off by more than 8/255: 26 and
  31 cells, never gating). `prove-full-self-cf-1` against `-cf-2` differs only in the 11 closing
  variant cells that no longer run states and the one cell that errored.
- **Safari passes, with one honest caveat.** Its media-dark leg is the registered skip
  `safari-no-media-dark`: 1,123 cells skipped outright (leg `dark`) and the dark-media half of the
  1,123 `theme-light` cells, which run with the OS's light media (2,246 cells carry the skip). The states pass ran 1,286 cells of the
  current matrix plus the 11 closing-variant cells (old matrix). 10 cells had state errors on both
  sides (hover, focus and focus-visible not matching) between 15:04:42 and 15:05:38, exactly while
  the owner was using the machine over Screen Sharing (`pmset -g assertions`: "Remote user active");
  the closing-variant cell in `option-responsive-spacings` threw like the Chrome and Firefox one. The
  10 cells rerun alone passed (`prove-full-self-safari-states-4-rerun`, 316 states, 0 errors), the
  closing-variant cells are in the stateless run, and no cell anywhere had a difference.
  `:focus-visible` on `input[type=date]` was skipped as registered in 27 cells.

### Chunk control

`uv run tests/run.py full --control`: every preset with banner sections (all but `colors`, which has
none) against its reference split at the banners and re-imported (`tests/build/hybrid/<ref>/control.css`;
each split reassembles its file byte for byte and its banner titles equal `tests/sections.json`).

| Browser | Run id | Cells | Differences | Harness errors | Wall clock |
|---|---|---|---|---|---|
| Chrome, Firefox | `prove-full-control-cf` | 4,965 each, 17,912 states per side | **0** | 0 | 1,596 s |
| Safari | `prove-full-control-safari-states` + `-states-rerun`, `prove-full-control-safari-stateless` | 1,282 state cells (1,006 run, 276 media-dark skipped; 13,928 states) and 3,683 other cells (2,839 run, 844 skipped) | **0** | states run: 717 state errors in 21 theme kitchen-sink cells between 16:08:53 and 16:10:46, while the owner was connected over Screen Sharing; those 22 cells rerun alone: 0 (704 states). Other cells: 0 | 1,504 s + 61 s + 434 s |

### Sass-compiled control

`uv run tests/reference/build_references.py options --work <dir>` (Sass 1.85.1) and
`... options --sass 1.106.1 --work <dir>` recompile unmodified `pico.scss` and `pico.classless.scss`
from tag `v2.1.1` with the 2.1.1 autoprefix step. The renamed outputs went to
`tests/build/sass-control/femto[.classless].sass-<version>.css`, and each was compared against the
shipped reference: `compare --ref /tests/reference/femto[.classless].css --test <control> --entry
<entry> --all-legs --no-states` (every page of the entry, widths 390 and 1280, all four legs, rtl on
rtl pages).

| Control | Bytes vs reference | Chrome + Firefox | Safari |
|---|---|---|---|
| Sass 1.85.1, default | identical | 912 cells, **0** (`prove-sass-control-default-1.85.1-cf`) | 456 cells, **0** (`...-safari`) |
| Sass 1.85.1, classless | identical | 704 cells, **0** | 352 cells, **0** |
| Sass 1.106.1, default | 33 lines (fractional `rgb()` channels written as percentages) | 912 cells: **0** style and **0** resolved-token differences; 145,920 `token-raw` records on 25 tokens | 456 cells: **0** style and token; 54,720 `token-raw` |
| Sass 1.106.1, classless | 33 lines | 704 cells: **0** style and token; 117,808 `token-raw` on 24 tokens | 352 cells: **0** style and token; 44,486 `token-raw` |

The 1.106.1 runs report FAIL by design: the raw text of a custom property is compared exactly
(`rgb(19, 22.5, 30.5)` against `rgb(7.4509803922%, 8.8235294118%, 11.9607843137%)`), while what the
tokens resolve to, and every computed style, is equal. Only the 1.85.1 compile is the oracle's own
build.

### Negative controls

`uv run tests/run.py selftest --browsers chrome,firefox` (`prove-selftest-cf`, plus
`prove-selftest-cf-surface` after fixing a name clash in the `token-surface` case) and
`uv run tests/run.py selftest --browsers safari` (`prove-selftest-safari-2`, run once nobody had touched
the machine for 60 s; the first attempt, `prove-selftest-safari`, ran during Screen Sharing and was
stopped):

| Control | Chrome + Firefox | Safari |
|---|---|---|
| `self` | PASS: 0 differences, 0 errors | PASS: 0 differences, 0 errors |
| `chunk-control` | PASS: 0 differences, 0 errors | PASS: 0 differences, 0 errors |
| `color-2-of-255` | PASS: h1 color diffs 4, token diffs 40, total 116 | PASS: h1 color diffs 2, token diffs 20, total 57 |
| `color-1-of-255` | PASS: 10 unregistered, kinds ['token-raw'] | PASS: 5 unregistered, kinds ['token-raw'] |
| `hover-only` | PASS: states with diffs ['hover'] | PASS: states with diffs ['hover'] |
| `dark-only-token` | PASS: legs with diffs ['dark'] | PASS: legs with diffs []; media-dark cells skipped and registered: True |
| `breakpoint-577` | PASS: widths with diffs [576] | PASS: widths with diffs [576] |
| `rtl-only` | PASS: directions with diffs ['rtl'] | PASS: directions with diffs ['rtl'] |
| `placeholder` | PASS: pseudo-elements with diffs ['::placeholder'] | PASS: pseudo-elements with diffs ['::placeholder'] |
| `backdrop` | PASS: pseudo-elements with diffs ['::backdrop'] | PASS: pseudo-elements with diffs ['::backdrop'] |
| `active-only` | PASS: states with diffs ['active'] | PASS: states with diffs ['active'] |
| `focus-only` | PASS: states with diffs ['active', 'focus', 'focus-visible'] (must include focus, may include ['active', 'focus', 'focus-visible']) | PASS: states with diffs ['focus', 'focus-visible'] (must include focus, may include ['active', 'focus', 'focus-visible']) |
| `focus-visible-only` | PASS: states with diffs ['focus', 'focus-visible'] (must include focus-visible, may include ['focus', 'focus-visible']) | PASS: states with diffs ['focus', 'focus-visible'] (must include focus-visible, may include ['focus', 'focus-visible']) |
| `theme-dark-only` | PASS: legs with diffs ['theme-dark'] | PASS: legs with diffs ['theme-dark'] |
| `variant-only` | PASS: variants with diffs ['class=modal-is-open'] of ['class=modal-is-open', 'plain'] | PASS: variants with diffs ['class=modal-is-open'] of ['class=modal-is-open', 'plain'] |
| `after-only` | PASS: pseudo-elements with diffs ['::after'] | PASS: pseudo-elements with diffs ['::after'] |
| `before-only` | PASS: pseudo-elements with diffs ['::before'] | PASS: pseudo-elements with diffs ['::before'] |
| `marker-only` | PASS: pseudo-elements with diffs ['::marker'] | PASS: pseudo-elements with diffs ['::marker'] |
| `file-selector-button-only` | PASS: pseudo-elements with diffs ['::file-selector-button'] | PASS: pseudo-elements with diffs ['::file-selector-button'] |
| `shadow-only` | PASS: 46 records inside shadow trees, 2 on hosts (['div']), properties ['accent-color'] | PASS: 23 records inside shadow trees, 1 on hosts (['div']), properties ['accent-color'] |
| `token-surface` | PASS: kinds ['surface-added'], tokens ['--femto-zz-added'] | PASS: kinds ['surface-added'], tokens ['--femto-zz-added'] |
| `token-resolution` | PASS: kinds ['token', 'token-raw'], tokens ['--femto-text-selection-color'] | PASS: kinds ['token', 'token-raw'], tokens ['--femto-text-selection-color'] |
| `registry-suppression` | PASS: unregistered h1 0, h2 248; registered {'neg-h1-color': 66, 'neg-h1-token': 40, 'neg-h1-token-raw': 10}; h1-only control had 116 differences, entrie... | PASS: unregistered h1 0, h2 121; registered {'neg-h1-color': 32, 'neg-h1-token': 20, 'neg-h1-token-raw': 5}; h1-only control had 57 differences, entries ... |
| `missing-stylesheet` | PASS: 1 errors | PASS: 1 errors |

What Safari cannot run, and how each is registered:

| Check | Why | Registry entry (`browser-limit`) |
|---|---|---|
| The media leg other than the OS scheme (`media:dark` on a light OS, including the dark-media half of `theme-light`) in a single pass | no WebDriver emulation of `prefers-color-scheme`, and agents never change the macOS appearance; the owner-run dark pass below covers it | `rig.json` `safari-no-media-dark` |
| `:focus-visible` on `input[type=date]` (and the other date-family types) | keyboard focus lands on an inner date field; the input itself never matches | `rig.json` `safari-no-focus-visible-date-input` |
| `dark-only-token` | consequence of the first row: the dark leg is skipped, which the control accepts only when every dark cell is a registered skip | `safari-no-media-dark` |

Everything else runs in Safari: all six pseudo-elements read through `getComputedStyle()`, exact
iframe widths, `data-theme` legs, rtl, page variants, shadow roots, hover, active, focus and
focus-visible (Option+Tab, or `focus()` after the key presses for `summary` and color inputs).
Safari interactive states need an unlocked screen, the automation window in front and nobody using
the machine, including over Screen Sharing.

### Safari dark pass results

Run on 2026-10-27 from 16:53 to 17:38, after the owner switched macOS to dark (see Safari dark pass).
Every Safari session logged `OS scheme dark`, and no run had a harness error.

| Run | Run id | Cells | Differences | Skipped checks |
|---|---|---|---|---|
| Every reference against itself, no states | `dark-full-self-safari-stateless` | 3,683 | **0** | `media:light` 1,995 cells |
| Every reference against itself, states | `dark-full-self-safari-states` | 1,286 (12,128 states) | **0** | `media:light` 732 cells; date-input `:focus-visible` 21 cells |
| Chunk control, no states | `dark-full-control-safari-stateless` | 3,683 | **0** | `media:light` 1,995 cells |
| Sass 1.85.1 control, default | `dark-sass-control-default-safari` | 456 | **0** | `media:light` 228 cells |
| Sass 1.85.1 control, classless | `dark-sass-control-classless-safari` | 352 | **0** | `media:light` 176 cells |
| Selftest | `dark-selftest-safari` | 24 controls | `dark-only-token` PASS: legs with diffs `['dark']`; `theme-dark-only`, `self`, `chunk-control` PASS | 19 light-leg controls compare nothing on a dark OS and report FAIL; all 24 passed in the light pass |

The chunk control's state cells were not rerun in dark. With the light pass, Safari has now run
every leg of criterion 1: `light`, `dark`, and `theme-light` and `theme-dark` on both a light and a
dark OS.

### Static checks and lint

`uv run tests/static_checks.py` runs (exit 1, 0 of 8 pass) and `npx eslint css` runs (exit 2, "all
of the files matching the glob pattern are ignored", because `css/` holds only the 2.1.1 files the
config ignores). Both are expected before any femto CSS exists.

## Known limits

- One Safari pass compares only the OS scheme's media leg (registered `media:*` skip), so each
  Safari gate needs the owner to switch macOS to dark for a second pass. Safari never gives a
  date-family input `:focus-visible` (registered `state:focus-visible:input[type=...]` skip), and
  Safari interactive states need an unlocked screen.
- 19 of the 24 selftest controls run only the `light` leg, so on a dark OS Safari skips them and
  they report FAIL without comparing anything. Run Safari's selftest in the light pass.
- No fixture loads femto only inside a shadow root: every page loads the stylesheet in the outer
  document too, so a shadow host's own scheme is never the only one in play. Phase 1 checked that
  case with a standalone Selenium script (five hosts, every computed longhand of 230 elements and
  their `::before`, Chrome and Firefox, light and dark media). Hosts without `data-theme`, with
  `data-theme=light` and inside a dark island match 2.1.1 exactly. Hosts with `data-theme=dark` are
  dark, where 2.1.1 gave them no color tokens at all (Decision 12).
- Computed styles cannot show `::-webkit-*`/`::-moz-*` vendor pseudo-elements (range thumbs and
  tracks, progress bars, spin buttons, calendar pickers, details markers), `:visited`, or
  `:user-invalid`; token resolution and screenshots are the only signal for those. `::selection` is
  reported by `getComputedStyle` in all three browsers, but the harness does not collect it; Phase
  1's review compared it by hand, on the page and in both islands, in Chrome, Firefox and Safari.
- The loading spinner is an SVG whose internal animation cannot be frozen; screenshots cover every
  `[aria-busy=true]` element on both sides. Media controls draw their time display asynchronously
  (Firefox), so `video[controls]` and `audio[controls]` are covered too.
- Screenshots cover the iframe viewport (the top 800 px after scrolling to the top), not the full page.
- `select:active` is checked without focus and without the native picker (see States).
- `prefers-reduced-motion` is not an axis; both sides run with the OS setting (no preference).
- Hover and active move the real (synthesized) pointer: in Safari, moving the physical mouse over the
  automation window during a run, or using the machine over Screen Sharing, disturbs them (seen in
  the proving run: every state in the cells that ran during that minute failed to match on one side
  or both; nothing was misreported as a difference). The harness now retries such a cell once when
  `HIDIdleTime` shows real input during it; otherwise rerun the affected cells with `--presets`,
  `--pages`, `--schemes` and `--widths` filters.
- Theme presets run only on the kitchen sink. That covers every rule a 2.1.1 theme changes, but a
  femto theme file that wrongly styled an element only other pages hold would go unseen there.
- The `progress:indeterminate[value]::-webkit-progress-value` selector can never match, so no
  fixture covers it.
- Safari 27 paints a color that arrives through `light-dark()` slightly differently from the same
  literal: a fractional channel is truncated instead of rounded (`rgb(26, 30.5, 40.25)` paints as
  30, not 31, in the green channel; `rgb(251, 251.5, 252.25)` as 251, not 252), and composited
  overlays drift by up to 5/255 (the open modal backdrop). `getComputedStyle` reports identical values on
  both sides, so only screenshots see it. Found in Phase 1's review: every Safari
  `tokens-breakpoints.html` cell (the page with the open dialog) has pixel differences, none above
  8/255, while Safari's self run of the same page has none. Pixel diffs do not gate, and flat areas
  stay within the 1/255 tolerance; Chrome and Firefox show none of it. Do not chase these in triage.
