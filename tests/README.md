# femto parity harness

This folder proves that femto reproduces Pico CSS 2.1.1. The harness loads fixture pages in the real
Chrome, Firefox and Safari on the macOS test machine, once with a 2.1.1 reference stylesheet and once
with femto, and compares every computed style, every token and every interactive state. Any
difference that is not registered in `tests/divergences/` fails the run.

Nothing here ships.

## Quick start

```sh
uv run tests/run.py rig                                  # verify the three browsers on this machine
uv run tests/run.py selftest                             # prove detection with negative controls
uv run tests/run.py self --pages kitchen-sink.html       # 2.1.1 against itself
uv run tests/run.py fast --modules forms/basics          # one module's check (hybrid build)
uv run tests/run.py full                                 # the whole matrix, three browsers
uv run tests/run.py coverage --css /tests/reference/femto.css --entry default
uv run tests/run.py registry                             # validate tests/divergences/
```

Every run writes `tests/results/<run-id>/result.json`, `summary.txt` and `log.txt`, prints the
summary, and exits 0 only when nothing unregistered differs and no harness error occurred.

Python runs only through `uv`: `tests/run.py` carries PEP 723 metadata pinning
`selenium==4.52.0` and `pillow==13.0.0`. Selenium Manager fetches chromedriver and geckodriver into
`~/.cache/selenium`; Safari uses `/usr/bin/safaridriver`.

## Layout

| Path | Contents |
|---|---|
| `README.md` | this file |
| `run.py` | CLI: `uv run tests/run.py <mode> [options]` |
| `harness/` | Python modules, `page.js` (fixture loader), `differ.js` (in-page collector and differ), `host.html` (top-level host page), `probe.html` (rig probe) |
| `variants.json` | comparison presets |
| `divergences/` | divergence registry, `schema.json` |
| `pages/` | fixture pages, `pages.json` manifest, `assets/` |
| `reference/` | renamed 2.1.1 CSS (gitignored, rebuilt from tag `v2.1.1` by `run.py` when missing) and committed option references, provenance in `reference/README.md` |
| `sections.json` | 2.1.1 banner sections of the default entry mapped to femto files |
| `static_checks.py` | mechanical checks on the repository, the shipped files and `dist/` (`coverage` reads the tables in Coverage below; `dist` compares `dist/` with a fresh `npm run build`) |
| `build/`, `results/` | generated, gitignored |

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
  `getComputedStyle()` returns empty values for it (on `tokens-schemes.html`, a host's own anchor
  read every token as `""` whenever its probe group started there).
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
| `fast` | For checking one module. `--modules forms/basics,...` or `--sections "Basics form elements;Input type file"`: the manifest pages of those modules or sections, Chrome and Firefox, widths 390 and 1280, legs `light` and `dark` (media), ltr plus rtl on pages with `rtl: true`, with states. By default the test side is a hybrid build of the preset's reference with those sections replaced by their femto files; `--direct` compares the preset's own test list instead. A section is replaced as a whole, so every femto file `tests/sections.json` maps to it must exist (Styles needs `tokens/base.css`, `tokens/breakpoints.css` and `layout/elements.css`); missing files stop the run with exit 2. `--kitchen-sink` adds the kitchen sink; `--presets` picks entries (default `default`). Example: `fast --sections "Styles;Color schemes;Document"`. `layout/grid` reads `--femto-grid-template-columns` from `tokens/breakpoints.css` (Styles), so name `tokens/breakpoints` with `layout/grid`; without it the hybrid keeps 2.1.1's Styles and `.grid` stays one column at 768px and wider. |
| `full` | The whole matrix below. Chrome and Firefox run 2 workers each, Safari 1, all at once (subject to the slot lock). `--self` compares every preset's reference against itself; `--control` compares every preset that has hybrid settings (all but `colors`, which has no banners, and `user-root-override`, which loads two stylesheets) against its chunk control; `--states-only` keeps only the cells that run interactive states and `--stateless-only` only the others, so a Safari leg can be split into two invocations whose union is the matrix. Command-line filters (`--pages`, `--widths`, ...) cut the matrix and are logged as a cap. |
| `compare` | Direct comparison: `--ref` against `--test` (root-relative lists), or each `--presets` preset's own lists. `--entry` picks pages for `--ref`. Defaults to the fast axes; `--full-widths` and `--all-legs` widen them. |
| `self` | A reference against itself, which must find no difference. |
| `hybrid` | A preset's reference against a hybrid build: `--modules`, `--sections`, or `--control` (no section replaced: the chunk control). Defaults to the fast axes; `--full-widths` and `--all-legs` widen them to every width and leg on every page, with states everywhere, which is far heavier than the full matrix. `--full-plan` instead plans the full matrix's own cells and reductions (below) for `--presets` (default `default`), with the hybrid build as the test side, and takes the same command-line filters as `full`. Use `--full-plan` for a wide check of a hybrid: on Styles, Color schemes and Document it runs 3,296 cells in Chrome and Firefox where `--full-widths --all-legs` ran 9,576 per preset. |
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
in `divergences/rig.json`. A complete Safari run therefore takes two passes, one with macOS light and
one with macOS dark (see Safari dark pass); together the two passes run every leg.

### Safari dark pass

The harness never changes the macOS appearance, so switch it by hand:

```sh
osascript -e 'tell application "System Events" to tell appearance preferences to set dark mode to true'
```

Then run the Safari commands again, for example:

```sh
uv run tests/run.py full --browsers safari --stateless-only
caffeinate -d -i uv run tests/run.py full --browsers safari --states-only
```

Check that every session's `log.txt` line says `OS scheme dark` and that the skipped checks show
`media:light`, not `media:dark`; a session that read a light OS skips the dark cells instead of
passing them. Then switch back with `set dark mode to false`. The light-leg selftest
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
- Themes (`theme-<color>`, 20 presets, and `user-root-override`, which is in the same group): the
  kitchen sink only, 1280, every leg, with states. Every rule whose declarations differ between a
  theme reference and `femto.css` has a selector that matches on the kitchen sink (checked
  2026-10-27).

That is 2,093 cells per browser, 610 of them with states (2,085 and 602 in `--control`, which has
no `colors` or `user-root-override` cells): `default` 1,648, `colors` 4, each option 119, each theme
4 and `user-root-override` 4, as counted by the harness's own planner (`harness.cli.plan`, which
starts no browser).

## Presets: `tests/variants.json`

`presets.<name>`: `entry` (selects pages whose manifest `entries` include it), `ref` and `test`
(root-relative stylesheet lists, loaded in order), optional `group` (`option`, `theme`) and
`hybrid` (`sections`: the `tests/sections.json` entry used to split `ref`; `append`: URLs imported
after the chunks once any section is replaced, for theme and option files). There are 26 presets:
`default`, `colors`, 3 options, 20 themes and `user-root-override`.

- `default`: `tests/reference/femto.css` against `css/femto.css`.
- `colors`: `tests/reference/femto.colors.css` against `css/femto.colors.css`.
- `option-<option>`: `tests/reference/options/femto.<option>.css` against `css/femto.css` plus
  `css/options/<option>.css`.
- `theme-<color>`: `tests/reference/femto.<color>.css` against `css/femto.css` plus
  `css/themes/<color>.css`. Azure is built into `tokens/`, so its reference is `femto.css` itself.
- `user-root-override`: `tests/reference/femto.css` against `css/femto.css`, each followed by
  `tests/pages/assets/user-root-override.css`, a page author's own primary color on plain `:root`
  (registered as natural fixes in `divergences/tokens.json`). It is in the `theme` group, so the full matrix runs it like
  a theme, and it has no `hybrid` settings: a hybrid splits a single reference stylesheet, so
  `hybrid` and `full --control` leave it out.

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
`hybrid-styles+color-schemes+document--themes-azure.css` for `theme-azure`. The append list must be
part of the name because `default` and `theme-azure` share `tests/reference/femto.css`. A run stops
with a build error if it would write one hybrid path with two contents.

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
  `.indeterminate = true` on every `[data-indeterminate]`, calls `requestSubmit()` on every
  `form[data-user-invalid]` (validation puts its invalid fields in `:user-invalid` without typing,
  fires no `submit` and focuses the first invalid field, which `page.js` blurs again), calls
  `showModal()` on every `dialog[data-show-modal]`, and gives every `[data-shadow]` host an open
  shadow root holding the same stylesheets followed by a clone of its `<template>` child.
  `window.__femto.ready` resolves when every stylesheet has loaded or failed;
  `window.__femto.errors` lists failures (a failed stylesheet is a harness error).
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
`{"class": "modal-is-open"}`; a variant may not set `css`, `theme` or `dir`), `rtl` (the page also
runs with `dir=rtl` on `<html>`: set where the module has `[dir=rtl]` rules, and on the three modal
pages, whose close controls and footers use logical properties that move them in right-to-left
text), `media` (its CSS has media queries), and optional `stateless_variants`
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

### What is registered

Each entry's `reason` says what changed for a user of 2.1.1 and why; `category` sorts the entries
into natural fixes, dropped hacks, new tokens, option mechanisms and browser limits.

- `tokens.json`: what follows from declaring every color token once, on `:root, :host`, with
  `light-dark()`, while `data-theme` sets only `color-scheme`.
  - `tokens-light-dark-raw-text`: the raw text of tokens whose femto value is a `light-dark()` pair.
    It accepts any `light-dark()` text, so `static_checks.py --only themes` compares each theme
    file's ten tokens with its reference as text.
  - `tokens-group-island-focus-ring`: the group focus-ring tokens inside `data-theme` islands.
  - `tokens-author-color-scheme-dark` and `-light`: an author's inline `color-scheme` on an element
    without `data-theme` now switches femto's colors in that subtree, where 2.1.1's literals kept the
    page's colors (fixtures `#cs-dark` and `#cs-light` in `tokens-schemes.html`).
  - `tokens-own-data-theme-style`, `-token` and `-raw`: an element that carries `data-theme` itself
    (`<button data-theme=dark>`, the elements under "Elements with their own data-theme" in
    `tokens-schemes.html`) keeps its own color tokens in its scheme, where 2.1.1 redeclared the
    page's. They are limited to the 11 tokens, the color, background and box-shadow properties and
    the page that runs report; `tokens-schemes.html` has a dark `select`, `textarea`, `h1`, links and
    a `role=button` so each element kind in their selector is exercised (a `summary` carrying
    `data-theme` shows no difference, so it is not listed).
  - `tokens-dark-shadow-host-input-focus`: one flat `input:is(...)` rule replaces 2.1.1's three
    per-scheme copies of `--femto-form-element-focus-color`, so in a shadow root whose host carries
    `data-theme=dark`, a focused checkbox or radio draws the `primary-focus` ring like every other one
    (fixtures `shadow-dark-host-c1` and `shadow-dark-host-r`, with `data-states="focus"`).
  - `tokens-dark-shadow-host-contrast-filter`: a shadow host carrying `data-theme=dark` is dark. The
    forced-dark rules add `:host([data-theme=dark])`, and this entry records the one harness-visible
    effect, the contrast summary and busy contrast icons in the `shadow-dark-host` template taking the
    dark filter.
  - `tokens-root-user-override-style`, `-token` and `-raw`: a page author's own
    `:root { --femto-primary: ... }` now takes effect everywhere, including inside `data-theme`
    islands. They are scoped to the `user-root-override` preset and limited to the colors of
    `tests/pages/assets/user-root-override.css`.
  - `tokens-input-focus-color-author-override`: documentation only, scoped to a
    `user-element-override` preset that does not exist. The flat `input:is(...)` rule sets
    `--femto-form-element-focus-color` at (0,1,1), so an author rule loaded after femto, from (0,1,1)
    up to the matching 2.1.1 scheme copy at (0,2,1) or (0,3,1), now sets a checkbox's or radio's focus
    ring color.
  - `tokens-new-names`: `--femto-primary-inverse-filter`, the spinner filter that 2.1.1 picked at
    compile time.
- `tokens-breakpoints.json` (`breakpoints-new-tokens`): `--femto-grid-template-columns`, which
  `tokens/breakpoints.css` sets from 768px for `.grid`. `.container` and the modal keep 2.1.1's
  literal media queries: a token-read `max-width` would be declared at every width and override
  `img`, `legend` and author rules below 576px (guard fixtures `img.container` and `legend.container`
  in `classes-container.html`).
- `forms-basics.json`: `firefox-focus-ring-restored`, limited to the `[data-tooltip][tabindex]`
  targets of `components-tooltip.html` in the focus state, the only fixture elements that set no
  outline of their own, and `firefox-user-invalid-focus-ring-restored`, limited to the "Left
  invalid" form of `forms-basics.html` (`form[data-user-invalid]`), whose fields `page.js` puts in
  `:user-invalid`. `fieldset-min-width-auto`, limited to the nine pages that have a fieldset, with
  `fieldset-narrow-column-geometry`, limited to `forms-input-date.html` from 768px: 2.1.1 kept the
  browsers' `min-width: min-content` on `fieldset`, so a fieldset grew past a narrow column to fit a
  date field, a long word or a table; femto's `min-width: auto` sizes it like a div (fixture: the
  fieldset in `#date-narrow-grid`).
- `forms-input-date.json`: `group-date-input-min-width`, with `-narrow-column-geometry` from 768px,
  limited to `forms-input-date.html`. 2.1.1 left a date-family input in `[role=group]` or
  `[role=search]` at a flex item's `min-width: auto`, so it kept the native field's width and pushed
  the group's button past a narrow column; femto sets `min-width: 0` there, and the field clips its
  text instead (fixture: `#date-narrow-grid`, a four-column `.grid` holding a datetime-local group
  and a fieldset with another).
- `components-group.json`: the island focus ring, split by the island's scheme
  (`group-island-focus-ring-style` and `-light-island`), and `group-hidden-child-corners`, with
  `-margin`, `-geometry` and `-hidden-input`, limited to `components-group.html`. 2.1.1 found a
  group's outer controls with `:first-child` and `:last-child`, which count a `[hidden]` element or
  an `<input type=hidden>`; femto skips them, so the first and last visible controls keep their
  rounded corners and the first one loses the negative overlap margin (fixtures: the last group of
  "Role group", with a `<span hidden>` first and a hidden input last, and the last search of "Role
  search", with a hidden input first). `group-rtl-logical-corners`, limited to
  `components-group.html`, `components-nav.html` and `kitchen-sink.html`: 2.1.1 rounded the ends and
  placed the overlap margin with left and right properties, so a right-to-left group rounded its
  inner corners, drew a double border at one seam and pushed its end item one border width out;
  femto uses logical properties, which follow each item's own direction, so a right-to-left group
  mirrors a left-to-right one (fixtures: the "Right to left" block of `components-group.html`, and
  the kitchen sink's groups and the nav groups of `components-nav.html` in their rtl legs).
  `group-invalid-field-above-next-item`, limited to `components-group.html`: 2.1.1 left every item
  at `z-index: auto`, so the next item painted over the border an `aria-invalid="true"` or `"false"`
  field shares with it; femto gives that field `z-index: 1`, so its whole red or green border shows,
  and a focused item stays above it at 2 (fixtures: the invalid text input and button after "Two
  inputs" in "Role group", and the valid select, search input and submit in "Role search").
- `options-no-transitions.json`: six entries limited to the `option-no-transitions` preset. 2.1.1
  builds that option by compiling the gated `transition` declarations, the modal animations and the
  tooltip slides out; an appended file can only reset them, so `options/no-transitions.css` sets
  `--femto-transition: 0s` and repeats each dropped rule's selector list with a reset. What a reset
  cannot undo is `option-mechanism`: the token's raw text and resolved value, the two tooltip slide
  tokens (reset but still declared), and `transition-property: all` on a submit, reset or button
  input, dropdown list or modal close button that also carries `role=group` or `role=search`
  (fixture: the submit button with `role=group` in `components-group.html`). The group's own
  transition, which 2.1.1 does not gate, follows the token to 0s (`natural-fix`). The four
  `@keyframes` stay defined; no record kind can show an at-rule.
- `components-progress.json`: `firefox-indeterminate-progress-reduced-motion`, documentation only
  (no run applies `reduce`; see Known limits). Firefox's bar on an indeterminate progress is
  transparent whatever the motion preference, where 2.1.1 left a full bar with reduced motion.
- `components-dropdown.json`: `nav-dropdown-no-negative-margin`, on the nav dropdowns of the six
  pages that have one, and `nav-dropdown-summary-padding`, on their plain summaries. 2.1.1's
  negative vertical margin on `nav details.dropdown` does nothing where `<details>` honors
  `display: inline`, but Firefox 128 to 142 lays it out as a block container and lifted the dropdown
  above the nav links; femto sets it to 0. The summary's padding subtracts one border width instead
  of two, so its text lines up with the link text instead of one border width above it. The lift
  needs the old details layout, so it was probed outside the harness. `nav-dropdown-block-details`,
  on the same six pages: 2.1.1's `display: inline` split the details around its block summary, and
  Firefox 143 and later placed the open list against an empty fragment of it; femto makes the
  details a block, so only its own display, size and origins change in the harness, and in Firefox
  (and Safari, per picocss/pico#671) `nav-dropdown-open-list-placement` records the open lists of
  `classes-dropdown-open.html` lining up under their summaries (fixtures: its two `dir="rtl"` nav
  lists and the left-aligned nav list below them).
- `components-nav.json`: `rtl-breadcrumb-backslash`, with `-geometry` and `-divider-inset`, limited to
  `components-nav.html` and `kitchen-sink.html`. 2.1.1's rtl rule gave the `::after` of every element
  inside a breadcrumb item but the last a backslash; femto drops it, so an rtl breadcrumb shows only
  its mirrored divider, and its links, items and list are as narrow as in ltr. `where.dirs` is not
  set: the `<div dir="rtl">` breadcrumb in `components-nav.html` shows the change in its ltr cells.
  `nav-group-margin`, with `-geometry` and `-page-shift`, limited to `components-nav.html`. 2.1.1
  kept the 1rem bottom margin of a `[role=group]` or `[role=search]` in a nav item, so the group sat
  half a rem above the other items and the nav was a rem taller; femto zeroes it when the group ends
  its parent, so the item, its nav and lists, the module wrapper, the body and the document are a
  rem shorter (fixture: the "Groups" nav; the "Group helper" nav above it, a group followed by
  `<small>`, keeps the margin and shows no difference). `nav-role-button-link-margin-top`, with
  `nav-role-button-link-item`, limited to `components-nav.html`. 2.1.1 reset the side and bottom
  margins of an `<a role="button">` in a nav item but not the links' negative top margin, so it sat
  about 0.25rem above a `<button>` beside it; femto zeroes it with `nav li :where([role=button])`, so
  the link lines up and its item is as tall as a button's (fixture: `#cta` in the first nav).
  At 390 its text wraps and its item is the tallest in the nav, so `-wrap-geometry`, `-page-shift`
  and `-breadcrumb-shift` record that nav, its lists, the module wrapper, the body and the document
  growing by 8px and the breadcrumb dividers below moving down with them.
- `content-typography.json`: `nested-list-margins`, with `-container-size` and `-breadcrumb-shift`,
  limited to `content-typography.html` and `kitchen-sink.html`. 2.1.1's
  `:where(dl, ol, ul) :where(dl, ol, ul)` has zero specificity and loses to the earlier list rule, so
  a list nested in another list kept a margin-top of 0 and the full typography spacing below it;
  femto writes the second half as `:is(dl, ol, ul)`, as 1.x did, so nested lists get the
  quarter-spacing top margin and no bottom margin. Their containers up to the document get shorter,
  and the absolutely positioned breadcrumb dividers below them in `kitchen-sink.html` move up
  (fixtures: the nested `ul`, `ol` and `dl` of both pages' typography blocks).
- `content-table.json`: `striped-row-data-theme`, with `-image`, limited to
  `classes-table-striped.html`. 2.1.1 painted an odd body cell of a `.striped` table with the
  translucent stripe alone, so under a `data-theme` on the table, its `tbody`, the row or the cell
  the page showed through behind the other scheme's text; femto gives those cells the scheme's
  background color and draws the stripe over it as a one-color gradient (fixtures: the tables under
  "Rows and cells with their own data-theme").
- `components-modal.json`: `modal-dialog-backdrop-tint`, on `dialog:modal`. 2.1.1 left a modal
  dialog's `::backdrop` to the browser, whose `rgba(0, 0, 0, 0.1)` tint lay under the overlay, so a
  dialog opened with `showModal()` looked darker than one with the `open` attribute and stayed grey
  with a transparent overlay token; femto clears it with `:where(dialog)::backdrop`, which an
  author's own `::backdrop` rule still overrides (fixtures: the three dialogs of
  `components-modal-show.html`). `non-modal-dialog-backdrop-computed`, on `dialog:not(:modal)` in
  Firefox and Safari: they report the default on every dialog's `::backdrop` but draw it only for a
  modal one, so closed and open-attribute dialogs change in computed style only.
  `modal-footer-button-gap-rtl`: the gap before each footer button after the first is
  `margin-inline-start`, so in right-to-left text it falls between the buttons instead of after each
  one, and a `[role=group]` in the footer keeps its own overlap margin (fixtures: the footers of the
  three modal pages, in their rtl legs). `modal-close-float-inline-end`, with
  `modal-close-inline-end-rtl` and `modal-footer-text-align-end`: 2.1.1 floated the close control
  right with its spacing on its left (`margin-left: auto` outside a header) and aligned the footer
  right, so in right-to-left text the control sat against the start of the title and the footer
  buttons stayed on the start side; femto uses `float: inline-end`, `margin-inline-start` and
  `text-align: end`, so a right-to-left modal mirrors a left-to-right one, and in left-to-right text
  only the computed `float` and `text-align` values change (fixtures: the close controls and footers
  of `components-modal.html`, `components-modal-show.html` and `classes-modal.html` in ltr and rtl,
  and the kitchen sink's closed dialogs). `modal-mobile-viewport-height`, documentation only (scoped
  to a `mobile-dynamic-toolbar` preset that does not exist; the harness iframes have no dynamic
  toolbar, see Known limits): the card's `max-height` uses `100svh` where 2.1.1 used `100vh`, so on a
  phone whose browser toolbar shows, a tall card fits the visible viewport instead of running past
  both edges.
- `components-accordion.json`: `accordion-summary-flow-root`, on every summary. 2.1.1 floats the
  chevron at the end of the summary's last line but leaves the summary a list item, which does not
  contain floats, so a chevron that wraps below a full last line hung out of the summary, half
  outside a `role=button` background or against the content of an open accordion; femto makes the
  summary a flow root, which holds the chevron and grows by a row.
  `accordion-full-last-line-geometry` and `-page-shift`, limited to `components-accordion.html`,
  record that growth (fixture: `#full-last-line`, a 17rem wrapper whose plain and `role=button`
  summaries fill their line at every width). A select-like nav dropdown whose label wraps still
  paints its chevron below its fixed-height summary, but the summary now contains it for layout:
  `accordion-nav-dropdown-item`, with `-page-shift` and `-breadcrumb-shift` for the rest of
  `kitchen-sink.html`, records the nav item no longer growing to hold the chevron, and
  `accordion-nav-dropdown-list-width` the closed list that the escaped chevron no longer narrows
  (fixtures: the nav dropdowns of `kitchen-sink.html` at 375 to 640, and of `classes-dropdown.html`
  and `classes-dropdown-open.html` at 390).
- `components-card.json`: `table-cells-in-card-background`, limited to `components-card.html`.
  2.1.1 filled every `th` and `td` with the page background, so in the dark scheme a table in a
  card, which is lighter, showed as a darker block, and in a `.striped` table the translucent odd
  rows showed the card while the head and even rows showed the page; femto fills cells inside an
  `article` with `--femto-card-background-color`, at the cell rule's specificity, so the stripe and
  an author's own cell background still win (fixtures: `#card-table`, a striped table in a card,
  whose head and even cells change in the dark legs, and `#card-table-light` and `#card-table-dark`
  in the islands' cards, of which only the dark one changes).
- `forms-checkbox-radio-switch.json`: `radio-uncheck-no-background-fade`, limited to the five pages
  that have an unchecked radio. 2.1.1 faded a radio's background from the dot's color after its
  border had already thinned, so for about 150ms an unchecked radio was a full disc in that color,
  white in the dark scheme and black in the light scheme with the six themes whose dot is black;
  femto leaves `background-color` out of an unchecked radio's `transition-property` with
  `input:where([type=radio]:not(:checked))`, at (0,0,1), so an author's transition rule loaded after
  femto still wins and the no-transitions option's `input` reset still restores `all`. The harness
  finishes transitions, so it shows only the computed property, and the flash was probed outside it
  (fixtures: every unchecked radio, such as `#r-2` and `#r-3` in `forms-checkbox-radio-switch.html`
  and `#ks-r2` in `kitchen-sink.html`).
- `rig.json`: the checks Safari cannot run (`safari-no-media-dark`,
  `safari-no-focus-visible-date-input`).

The other 16 modules need no entry. Two fixtures exist to make the registry's checks meaningful:
`colors.html` has a "Two classes" block in which each span carries two neighboring utility classes
in file order, so a change of rule order in `femto.colors.css` shows as a difference, and
`components-tooltip.html` has tooltips on an open accordion summary and on two dropdown summaries,
which exercise the no-transitions option's chevron rules, and runs for `components/accordion`,
`components/dropdown` and `components/nav` too.

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

## Coverage: 2.1.1 modules and settings

This section maps every key of 2.1.1's `$modules` map and every 2.1.1 Sass setting to the femto
file or mechanism that replaces it, with the check that covers it. Sources are
`git show v2.1.1:scss/_settings.scss` and `scss/colors/utilities/_settings.scss`. Modules are listed
in `$modules` order. `css/femto.css` imports them in the order 2.1.1 emits them
(`tests/sections.json`), so each femto file carries its position among those imports in
parentheses. That order puts Section before Container, Typography before Link, and Button and Table
before Embedded content. `uv run tests/static_checks.py --only coverage` checks the Modules and Settings
tables against the tag, `tests/sections.json`, `tests/pages/pages.json` and `css/femto.css`.

### Modules

| 2.1.1 module | 2.1.1 section in `pico.css` | femto file (position in `css/femto.css`) | Fixture pages besides `kitchen-sink.html` |
|---|---|---|---|
| `themes/default` | Styles; Color schemes | `tokens/base.css` (1), `tokens/breakpoints.css` (2) and `layout/elements.css` (3) for Styles; `tokens/schemes.css` (4) for Color schemes. Azure is built in; `themes/azure.css` restates its ten tokens | `tokens-base.html`, `tokens-breakpoints.html`, `layout-elements.html`, `tokens-schemes.html` |
| `layout/document` | Document | `layout/document.css` (5) | `layout-document.html` |
| `layout/landmarks` | Landmarks | `layout/landmarks.css` (6) | `layout-landmarks.html` |
| `layout/container` | Container | `layout/container.css` (8) | `classes-container.html` |
| `layout/section` | Section | `layout/section.css` (7) | `layout-section.html` |
| `layout/grid` | Grid | `layout/grid.css` (9), which reads `--femto-grid-template-columns` from `tokens/breakpoints.css` | `classes-grid.html` |
| `layout/overflow-auto` | Overflow auto | `layout/overflow-auto.css` (10) | `classes-overflow-auto.html` |
| `content/link` | Link | `content/link.css` (12) | `content-link.html`, `classes-links.html` |
| `content/typography` | Typography | `content/typography.css` (11) | `content-typography.html` |
| `content/embedded` | Embedded content | `content/embedded.css` (15) | `content-embedded.html` |
| `content/button` | Button | `content/button.css` (13) | `content-button.html`, `classes-buttons.html` |
| `content/table` | Table | `content/table.css` (14) | `content-table.html`, `classes-table-striped.html` |
| `content/code` | Code | `content/code.css` (16) | `content-code.html` |
| `content/figure` | Figure | `content/figure.css` (17) | `content-figure.html` |
| `content/misc` | Misc | `content/misc.css` (18) | `content-misc.html` |
| `forms/basics` | Basics form elements | `forms/basics.css` (19) | `forms-basics.html`, `forms-input-date.html` |
| `forms/checkbox-radio-switch` | Checkboxes, Radios and Switches | `forms/checkbox-radio-switch.css` (20) | `forms-checkbox-radio-switch.html` |
| `forms/input-color` | Input type color | `forms/input-color.css` (21) | `forms-input-color.html` |
| `forms/input-date` | Input type datetime | `forms/input-date.css` (22) | `forms-input-date.html` |
| `forms/input-file` | Input type file | `forms/input-file.css` (23) | `forms-input-file.html` |
| `forms/input-range` | Input type range | `forms/input-range.css` (24) | `forms-input-range.html` |
| `forms/input-search` | Input type search | `forms/input-search.css` (25) | `forms-input-search.html` |
| `components/accordion` | Accordion (`<details>`) | `components/accordion.css` (26) | `components-accordion.html`, `components-tooltip.html` |
| `components/card` | Card (`<article>`) | `components/card.css` (27) | `components-card.html` |
| `components/dropdown` | Dropdown (`details.dropdown`) | `components/dropdown.css` (28) | `classes-dropdown.html`, `classes-dropdown-open.html`, `components-tooltip.html` |
| `components/group` | Group (`[role="group"]`, `[role="search"]`) | `components/group.css` (29) | `components-group.html` |
| `components/loading` | Loading (`[aria-busy=true]`) | `components/loading.css` (30) | `components-loading.html` |
| `components/modal` | Modal (`<dialog>`) | `components/modal.css` (31) | `components-modal.html`, `components-modal-show.html`, `classes-modal.html` |
| `components/nav` | Nav | `components/nav.css` (32) | `components-nav.html`, `components-tooltip.html` |
| `components/progress` | Progress | `components/progress.css` (33) | `components-progress.html` |
| `components/tooltip` | Tooltip (`[data-tooltip]`) | `components/tooltip.css` (34) | `components-tooltip.html` |
| `utilities/accessibility` | Accessibility & User interaction | `utilities/accessibility.css` (35) | `utilities-accessibility.html` |
| `utilities/reduce-motion` | Reduce Motion Features | `utilities/reduce-motion.css` (36) | `utilities-reduce-motion.html` (no run applies `reduce`; see Known limits) |

The `default` preset compares `css/femto.css` with `tests/reference/femto.css`. `npm run build`
inlines every file above into `dist/femto.css` and `dist/femto.min.css`. `static_checks.py --only
dist` checks them against a fresh build, and `compare` runs with an empty registry check them
against `css/` in the browsers (see Last verified).

### Settings

| 2.1.1 setting | 2.1.1 default | femto file or mechanism | Checked by |
|---|---|---|---|
| `$theme-color` | `"azure"` | Azure is built into `tokens/schemes.css` and `tokens/base.css` (`--femto-primary-inverse-filter`). Each of the 20 colors, azure included, is `css/themes/<color>.css`: one `:root, :host` rule with ten tokens, loaded after femto | presets `theme-<color>` against `tests/reference/femto.<color>.css` (`femto.css` for azure); `static_checks.py --only themes` |
| `$css-var-prefix` | `"--pico-"` | Dropped: always `--femto-` | `static_checks.py` shipped-file hygiene (no `--pico-` names) |
| `$semantic-root-element` | `"body"` | Hardcoded `body` (`body > header`, `body > main`, `body > footer` in `layout/landmarks.css` and `options/responsive-spacings.css`) | `default` and `option-responsive-spacings` presets, `layout-landmarks.html` |
| `$enable-semantic-container` | `false` | Dropped with the classless builds. `.container` gives centered widths | `default` preset (the default build's output) |
| `$enable-viewport` | `true` | Dropped with the classless builds; it applied only inside the semantic container | nothing to compare: no output in the default build |
| `$enable-responsive-spacings` | `false` | Opt-in `css/options/responsive-spacings.css` | preset `option-responsive-spacings` against `tests/reference/options/femto.responsive-spacings.css` |
| `$enable-responsive-typography` | `true` | On: five `--femto-font-size` root steps in `tokens/breakpoints.css`. Opt-out `css/options/fixed-typography.css` | `default` preset at 21 widths; preset `option-fixed-typography` against `tests/reference/options/femto.fixed-typography.css` |
| `$enable-classes` | `true` | Always on; class rules stay in their module files | `default` preset (`classes-*.html`) |
| `$enable-transitions` | `true` | On. Opt-out `css/options/no-transitions.css` | preset `option-no-transitions` against `tests/reference/options/femto.no-transitions.css`; `divergences/options-no-transitions.json` |
| `$enable-important` | `true` | Dropped; the default output's 20 `!important` declarations are kept | `default` preset; `css/no-important` off in `eslint.config.mjs` |
| `$parent-selector` | `""` | Dropped with the conditional builds | nothing to compare: the default build has no parent selector |
| `$breakpoints` | 576, 768, 1024, 1280 and 1536px; viewports 510 to 1450px; root font sizes 106.25% to 131.25% | Literal media queries: the root font-size steps and `--femto-grid-template-columns` in `tokens/breakpoints.css`, `.container` max-widths in `layout/container.css`, `dialog > article` max-widths in `components/modal.css` | `default` preset at 21 widths (1px either side of each breakpoint); `divergences/tokens-breakpoints.json` |
| `$modules` | all 33 on | One file per module (table above). A custom set is a copy of `css/femto.css` with lines removed | `tests/sections.json`, which `fast --modules` and `hybrid` builds use to swap femto module files into the 2.1.1 reference section by section; `static_checks.py --only coverage` |
| pico.colors `$css-var-prefix`, `$css-class-prefix` | `"--pico-"`, `"pico-"` | Dropped: `--femto-color-*`, `.femto-color-*`, `.femto-background-*` | preset `colors` against `tests/reference/femto.colors.css` |
| pico.colors `$palette`, `$properties`, `$utilities` | 20 color families and 19 shades, main colors on, black and white off, hex values; `color` and `background` names; all four utilities on | Dropped: `css/femto.colors.css` is static, created from `pico.colors.css` with the rename | preset `colors`, `colors.html` |

### Builds

| 2.1.1 file | femto |
|---|---|
| `css/pico.css`, `css/pico.min.css` | `css/femto.css` (the `@import` entry), `dist/femto.css`, `dist/femto.min.css` |
| `css/pico.<color>.css` and `.min.css` (19 colors) | `dist/femto.min.css` plus `css/themes/<color>.css` |
| `css/pico.colors.css`, `css/pico.colors.min.css` | `css/femto.colors.css`, `dist/femto.colors.css`, `dist/femto.colors.min.css` |
| Responsive spacings on, transitions off, responsive typography off (never shipped) | `css/options/responsive-spacings.css`, `no-transitions.css`, `fixed-typography.css` |
| Classless, fluid classless and conditional, with their colors | Dropped |

## Selector coverage

`uv run tests/run.py coverage --css /tests/reference/femto.css --entry default [--pages ...]` parses
the stylesheet (banner sections, conditional at-rules, nested rules resolved against their parent,
and the files it `@import`s, read from disk in its place and reported per file, so
`--css /css/femto.css` reports by module), strips pseudo-elements and dynamic pseudo-classes from
every selector (a `:not()` containing one is dropped whole, an `:is()`/`:where()` argument left
empty becomes `*`), and evaluates it with
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

Verified on 2026-10-27 on the test machine (macOS, 10 CPUs, 16 GB, one 1920×1080 display at device
pixel ratio 1, appearance Light) with Google Chrome Beta 157.0.8103.15 and chromedriver
157.0.8103.15, Firefox 160.0b1 and geckodriver 0.37.1, Safari 27.0.1 and its safaridriver, Selenium
4.51.0. `uv run tests/run.py rig` repeats the checks and writes `rig.json`.

Chrome Beta updates itself, and Selenium fetches the matching chromedriver; the harness records the
version in each run's rig line but does not flag a change. Counts measured on Chrome 157 (such as the
480 enumerated properties under Collection) have not been rechecked on later versions.

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
- Pointer input, focus and `:focus-visible` need the Safari window visible and focused. While the
  screen is locked (`lsappinfo front` reports `loginwindow`), the page reports
  `visibilityState: hidden` and `document.hasFocus() == false`, W3C pointer actions dispatch no
  DOM events at all, keyboard actions reach `body`, `requestAnimationFrame` never runs, and a
  `::file-selector-button` transition never advances (the transient `transition: none` handles that).
  `getComputedStyle`, `getAnimations().finish()` and element screenshots all work.
- When another app comes to the front during a run, every state fails to match until the session
  stops answering (each command hangs until the HTTP timeout). New sessions are then refused with
  "The Safari instance is already paired with a different session" until the orphaned
  `Safari --automation` instance is terminated.
- A false `hasFocus()` is not always a lost window. Each fixture load replaces the iframe, and when
  the old iframe held focus (after any focus state) Safari leaves the host document without focus:
  `document.hasFocus()` turns false although the window is key and input still arrives, which would
  skip every state cell after the first focus state. So the harness calls `window.focus()` in the host page first (which cannot make a
  window key behind another app or a lock screen), then asks safaridriver to switch to the
  session's window, and only then gives up. It also terminates any leftover `--automation` Safari
  before starting a session (it holds the Safari lock, so none can be live): a reused instance
  keeps the dead session's windows and opens the new one behind them.
- Real input disturbs Safari states: during local or Screen Sharing input, hover, focus and
  focus-visible stop matching on one side or both (never a false difference). safaridriver's synthesized input does not reset the
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
- Safari 27.2 (it updated itself by 2026-10-29, safaridriver 22625.2.8.11.9): while the user's own
  Safari is open, a new WebDriver session brings that Safari to the front and never completes, and
  every attempt fails after 30 s with "The session timed out while connecting to a Safari instance"
  (the rig probe shows only `SessionNotCreatedException()`). Selenium is not involved: a bare W3C
  new-session request to safaridriver behaves the same. With Safari quit (⌘Q), safaridriver launches
  its own `--automation` instance in about 1 s. Quit Safari before every Safari run.
- The screen locks once the display sleeps (about 5 minutes after the last input on the test
  machine), and from then on every states cell reports "interactive states not run". Run the states
  leg as `caffeinate -d -i uv run tests/run.py full --browsers safari --states-only ...`, which
  holds a display-awake assertion only while the harness runs and changes no setting.

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
  self runs also show isolated cells above 8/255 (three in one self run comparing the reference
  with itself), so isolated cells above 8/255 in hybrid runs are rig noise, not CSS. The
  summary counts pixels off by more than 8/255 separately, and images are saved only for those.
- `select`: pointer down opens the native picker in Chrome and Firefox (`:open`), and Firefox keeps
  it open after release, which made later states nondeterministic until `mousedown` on `select` was
  cancelled.

## Last verified

The harness itself was proved on 2026-10-27 with Chrome Beta 157, Firefox 160 beta, Safari 27.0.1
and Selenium 4.51.0, on a light and a dark OS. Each reference against itself over the full matrix,
each reference against its chunk control, and the 2.1.1 Sass recompiled with Sass 1.85.1 against
the shipped references (see `reference/README.md`) found 0 differences in all three browsers, and
every selftest control passed in all three.

femto against 2.1.1 over the whole matrix, with the registry in `tests/divergences/`, last ran on
2026-10-29 with Chrome Beta 158.0.8127.2, Firefox 160.0, Safari 27.2 (safaridriver
22625.2.8.11.9) on macOS 27.2. Each Safari pass ran under `caffeinate -d -i` with Safari quit and
nobody using the machine (see Rig notes).

| Run | Cells | Result |
|---|---|---|
| `full --browsers chrome,firefox` (Selenium 4.52.0) | 4,178 (17,294 states) | 0 unregistered, 0 harness errors, 539 s |
| `full --browsers safari`, light OS (Selenium 4.51.0) | 2,089 (6,941 states) | 0 unregistered, 0 harness errors |
| `full --browsers safari`, dark OS (Selenium 4.51.0) | 2,089 (5,230 states) | 0 unregistered, 0 harness errors |
| `selftest --browsers chrome,firefox` (Selenium 4.52.0) | 24 controls | all pass |
| `compare` of `css/femto.css` against `dist/femto.css` and `dist/femto.min.css`, empty registry | 456 each | only `token-raw` records on `--femto-box-shadow`, `--femto-card-box-shadow` and `--femto-dropdown-box-shadow`, equal once whitespace is collapsed: `dist/` writes every custom property value on one line, and the source writes `--femto-box-shadow` across seven |
| `compare` of `css/femto.colors.css` against both `dist/femto.colors*.css`, empty registry | 8 each | 0 differences |

The `user-root-override` preset and the "Left invalid" form of `forms-basics.html` came after those
runs, which is why the matrix now has 2,093 cells per browser. In Chrome and Firefox both pass
against themselves with 0 differences, and against femto every record they produce is registered
(the preset on the kitchen sink at 1280 in every leg, ltr and rtl; the form in `default` and the
three option presets at 390 and 1280 in every leg). Safari has not run either yet.

On 2026-10-30 the root rule's `:host` moved out of `:where()`, where Safari 17.5 to 18.1 never match
it. `compare --presets default --all-legs` over the six default-entry pages with shadow hosts
(`components-modal.html`, `kitchen-sink.html`, `layout-document.html`, `tokens-base.html`,
`tokens-breakpoints.html`, `tokens-schemes.html`) then found 0 unregistered differences in Chrome
and Firefox. Safari 27.2 on a dark OS ran every leg except light media, which needs a light OS and
has not run: 0 unregistered differences, 0 harness errors, and no pixel off by more than 8/255.

`coverage --css /css/femto.css --entry default` reports 691 selectors over 43 pages (57 loads), 0
dynamic rules without `data-states`, and one selector that matches nothing and never can (see Known
limits). `uv run tests/static_checks.py` and `npm run lint` pass.

## Known limits

- One Safari pass compares only the OS scheme's media leg (registered `media:*` skip), so a complete
  Safari run needs a second pass with macOS switched to dark by hand. Safari never gives a
  date-family input `:focus-visible` (registered `state:focus-visible:input[type=...]` skip), and
  Safari interactive states need an unlocked screen.
- 19 of the 24 selftest controls run only the `light` leg, so on a dark OS Safari skips them and
  they report FAIL without comparing anything. Run Safari's selftest in the light pass.
- No fixture loads femto only inside a shadow root: every page loads the stylesheet in the outer
  document too, so a shadow host's own scheme is never the only one in play. That case was checked
  with a standalone Selenium script (five hosts, every computed longhand of 230 elements and
  their `::before`, Chrome and Firefox, light and dark media). Hosts without `data-theme`, with
  `data-theme=light` and inside a dark island match 2.1.1 exactly. Hosts with `data-theme=dark` are
  dark, where 2.1.1 gave them no color tokens at all.
- Computed styles cannot show `::-webkit-*`/`::-moz-*` vendor pseudo-elements (range thumbs and
  tracks, progress bars, spin buttons, calendar pickers, details markers) or `:visited`; token
  resolution and screenshots are the only signal for those. `::selection` is reported by
  `getComputedStyle` in all three browsers, but the harness does not collect it; it was
  compared by hand, on the page and in both islands, in Chrome, Firefox and Safari.
- Only the "Left invalid" form of `forms-basics.html` reaches `:user-invalid`: `page.js` calls
  `requestSubmit()` on `form[data-user-invalid]`, which marks its invalid fields without typing
  (Chrome 158, Firefox 160), and no harness state puts any other field there. The one known
  difference, Firefox losing 2.1.1's `:-moz-ui-invalid { box-shadow: none }`, is
  `firefox-user-invalid-focus-ring-restored`; runs without that page list the entry as unused.
  Safari has not run the form yet; its validation may show a bubble.
- Hover and press land on an element's centre. A full-width file input's centre is its "No file
  chosen" text, so the `::file-selector-button` hover and active rules are compared as text only.
  Firefox does not apply user-action states to `::file-selector-button` under automation at all.
- The progress bar pseudo-elements are checked only by `components-progress.html`'s screenshots: the
  kitchen sink's progress block sits below its 800 px screenshot, and the theme presets run only the
  kitchen sink.
- Interactive states run only at 1280, and the right-to-left widths of wide pages (the kitchen sink
  and pages with media rules) are the band widths, which leave out 1280, so right-to-left states
  never run on those pages.
- Animations are finished before styles are read, so intermediate `@keyframes` steps are never
  compared; the keyframe bodies were compared as text instead.
- The loading spinner is an SVG whose internal animation cannot be frozen; screenshots cover every
  `[aria-busy=true]` element on both sides. Media controls draw their time display asynchronously
  (Firefox), so `video[controls]` and `audio[controls]` are covered too.
- Screenshots cover the iframe viewport (the top 800 px after scrolling to the top), not the full page.
- `select:active` is checked without focus and without the native picker (see States).
- `prefers-reduced-motion` is not an axis; both sides run with the OS setting (no preference). So no
  run applies `utilities/reduce-motion.css`: leaving it out passes every mode. It was checked as
  text (identical to 2.1.1's section) and with a standalone wrapper that emulates `reduce` in Chrome
  and Firefox. The one reduced-motion difference, the indeterminate progress bar in Firefox, was
  probed the same way and is registered as documentation only.
- No run has a dynamic mobile toolbar, so `100svh` equals `100vh` in every cell and the modal card's
  `max-height` computes the same on both sides. The modal fix was probed with a standalone page that
  emulates the toolbar in Chrome and Firefox, and is registered as documentation only.
- Hover and active move the real (synthesized) pointer: in Safari, moving the physical mouse over the
  automation window during a run, or using the machine over Screen Sharing, disturbs them (every state in the cells that run meanwhile fails to match on one side or both;
  nothing is misreported as a difference). The harness retries such a cell once when
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
  both sides, so only screenshots see it. Every Safari
  `tokens-breakpoints.html` cell (the page with the open dialog) has pixel differences, none above
  8/255, while Safari's self run of the same page has none. Pixel diffs do not gate, and flat areas
  stay within the 1/255 tolerance; Chrome and Firefox show none of it. Do not chase these in triage.
