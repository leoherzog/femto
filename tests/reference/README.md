# Reference CSS

The parity oracle: the compiled CSS of Pico 2.1.1 (git tag `v2.1.1`) with the femto rename applied, plus three option states 2.1.1 never shipped, compiled from the 2.1.1 Sass. Fixture pages load these and the femto files with the same class and token names, so one page works for both sides.

Nothing here is published. Do not edit these files by hand; regenerate them with `build_references.py`.

The 21 renamed copies are gitignored. `tests/run.py` rebuilds them from the tag whenever one is missing, so a clone needs tag `v2.1.1`, which upstream Pico publishes: `git fetch --no-tags https://github.com/picocss/pico.git tag v2.1.1`. The option references, this README and the script are committed.

```sh
uv run tests/reference/build_references.py check     # offline: verifies all 24 files (round trip, no "pico" outside comments)
uv run tests/reference/build_references.py copies    # rewrites the 21 copies from git, then checks
uv run tests/reference/build_references.py options   # recompiles the 3 option references (npx, npm, network)
```

## Files

| File | Source |
|---|---|
| `femto.css` | `git show v2.1.1:css/pico.css` |
| `femto.colors.css` | `git show v2.1.1:css/pico.colors.css` |
| `femto.<color>.css` (19) | `git show v2.1.1:css/pico.<color>.css` |
| `options/femto.responsive-spacings.css` | 2.1.1 Sass, `$enable-responsive-spacings: true` |
| `options/femto.no-transitions.css` | 2.1.1 Sass, `$enable-transitions: false` |
| `options/femto.fixed-typography.css` | 2.1.1 Sass, `$enable-responsive-typography: false` |
| `build_references.py` | the script that writes and checks all of the above |

`<color>` is each of amber, blue, cyan, fuchsia, green, grey, indigo, jade, lime, orange, pink, pumpkin, purple, red, sand, slate, violet, yellow and zinc. Azure is the default theme, so `femto.css` is the azure reference. Not copied, by design: `.min.css` files, the `.conditional` builds (dropped with `$parent-selector`), and the classless and fluid classless builds with their themes (`pico.classless.css`, `pico.fluid.classless.css`, `pico.classless.<color>.css`), which femto drops.

The option references are compiled on the default entry only. `$enable-semantic-container` and `$enable-viewport` are dropped with the classless builds, and `$enable-classes` is always on, as in the default build, so none of them needs a reference.

The 19 theme files came from 2.1.1's `scripts/build-themes.js` rather than the `build:css` step. That script passes `outputStyle: "compressed"` to `sass.compile`, which ignores it, so they are expanded like the entries, and they end without a trailing newline.

## Rename

Two substitutions, applied to identifiers only:

| 2.1.1 | Reference |
|---|---|
| `--pico-` | `--femto-` |
| `.pico-` before `color-` or `background-` (the utility classes in `pico.colors.css`) | `.femto-` |

These are the only occurrences of "pico" outside comments in all 21 source files: 24,322 replacements in total, for example 1,096 in `femto.css` and 2,402 in `femto.colors.css`. No source file contains "femto", so the reverse substitution is unambiguous.

Kept byte for byte: everything else, including `@charset "UTF-8";`, the literal zero-width space in a `content` string (one per file except `femto.colors.css`), and the header comment:

```css
/*!
 * Pico CSS ✨ v2.1.1 (https://picocss.com)
 * Copyright 2019-2025 - Licensed under MIT
 */
```

The header stays as provenance. `tests/` is exempt from the name check in `tests/static_checks.py`, and leaving comments untouched keeps the rename a pure identifier change that can be reversed exactly. The non-ASCII bytes are fine here because these files are never shipped; the shipped-file checks do not look at `tests/`.

Verification, run by `check` and repeated independently with `sed`:

- Reversing the substitutions (`--femto-` to `--pico-`, `.femto-` to `.pico-`) on each of the 21 copies reproduces `git show v2.1.1:css/<source>` byte for byte: 21 of 21 identical.
- With comments removed, no reference file contains "pico" in any case: 0 of 24 files. All 24 still contain it inside the header comment.
- For the 3 option references, the reversed text matches the SHA-256 of the compiled output recorded in `build_references.py`.

## Option references

2.1.1 never shipped these states, so they are compiled once from the 2.1.1 Sass in a temporary folder. Sass, PostCSS and Autoprefixer never enter the repo or the package; only the renamed CSS is committed.

Each entry follows `scss/pico.classless.scss`:

```scss
@use "index" with (
  $enable-transitions: false
);
```

The pipeline reproduces the 2.1.1 build exactly: `build:css`, then `build:autoprefix`.

1. `git archive v2.1.1 scss css/postcss.config.js | tar -x` into a temporary folder.
2. Write the three entries next to `scss/pico.scss`.
3. Compile each entry, and the unmodified `pico.scss` and `pico.classless.scss` as the control, with the 2.1.1 `build:css` flags:
   `npx --yes sass@1.85.1 --no-source-map --style expanded --no-error-css src/scss/<entry>.scss build/css/<name>.css`
4. Install the autoprefix tools at the versions `yarn.lock` resolves: postcss 8.5.3, postcss-cli 11.0.1, autoprefixer 10.4.21, browserslist 4.24.4, caniuse-lite 1.0.30001702, electron-to-chromium 1.5.113, node-releases 2.0.19, update-browserslist-db 1.1.3, fraction.js 4.3.7, normalize-range 0.1.2, picocolors 1.1.1 and postcss-value-parser 4.2.0, pinned exactly with npm `overrides`. caniuse-lite is 1.0.30001702 because that is what autoprefixer (`^1.0.30001702`) and browserslist (`^1.0.30001688`) resolve to in `yarn.lock`; the root pin 1.0.30001704 only occupies the top-level slot. The temporary `package.json` sets `"browserslist": ["defaults"]`, as the 2.1.1 one does.
5. `postcss --config build/css --replace build/css/<every file>`, with 2.1.1's `css/postcss.config.js` (`autoprefixer` with `cascade: false`, `map: false`). Browserslist warns that the data is 20 months old; that age is the point.
6. Compare the control with the oracle, then apply the rename to the three option files.

Node 24.22.0 and npm 11.19.1 ran it on 2026-10-27.

### Control result

| Sass | `pico.css` | `pico.classless.css` |
|---|---|---|
| 1.85.1, the `yarn.lock` version | byte-identical to `v2.1.1:css/pico.css` | byte-identical to `v2.1.1:css/pico.classless.css` |
| 1.106.1, the latest on 2026-10-27 | differs on 33 lines | differs on 33 lines |

The control still compiles `pico.classless.scss`, although femto drops the classless build: it is a second 2.1.1 file the pinned toolchain must reproduce byte for byte, compiled from the tag and compared with the tag, so it needs no classless copy in this folder.

Every line that differs under 1.106.1 is a `rgb()` or `rgba()` value whose channels are not whole numbers. 1.85.1 writes `rgb(231, 234, 239.5)`; 1.106.1 writes `rgb(90.5882352941%, 91.7647058824%, 93.9215686275%)`. Bisecting the published versions puts the change in Dart Sass 1.101.4 (1.101.3 still writes decimals). Its changelog says it avoids "`rgb()` or `rgba()` functions with non-percent decimal channels" for older browsers, using percentages instead. The values are equal: across the 151 changed channels in `pico.css` the largest difference is 1.25e-10 on the 0 to 255 scale. Nothing else differs, before or after the autoprefix step, and the three option compiles differ between the two versions on the same 33 lines only.

The committed option references use Sass 1.85.1, because only that version passes the control and the goal is the oracle's own build. A 1.106.1 compile would compute the same colors but would not be byte-comparable with the shipped references. `build_references.py options --sass 1.106.1` reruns the failing control; it writes nothing unless `--force` is given.

### What each option changes against `femto.css`

| Reference | Change |
|---|---|
| `femto.responsive-spacings.css` | 72 lines added in the Styles section: five `min-width` media blocks setting `--femto-block-spacing-vertical` on `body > header, body > main, body > footer, section`, and five setting both block spacings on `article`, from 1.25 to 2.25 times `--femto-spacing`. |
| `femto.fixed-typography.css` | 30 lines removed in the Styles section: the five media blocks that set `--femto-font-size` from 106.25% to 131.25%. |
| `femto.no-transitions.css` | 120 lines removed: every `transition` declaration, including the `-webkit-`, `-moz-` and `-ms-` copies on the range and progress pseudo-elements and the switch thumb's `margin 0.1s` transition; the modal opening and closing animations with the `modal-overlay` and `modal` keyframes; and the tooltip slide animations with their keyframes and slide tokens. `--femto-transition: 0.2s ease-in-out` stays defined. |

`tests/sections.json` lists the banner sections of the default entry, maps each to its femto files, and notes where themes and options differ inside a section.
