<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/leoherzog/femto/HEAD/.github/logo-dark.svg">
    <img alt="femto" src="https://raw.githubusercontent.com/leoherzog/femto/HEAD/.github/logo-light.svg" height="46">
  </picture>
</h1>

Semantic HTML made beautiful

Link one stylesheet and plain HTML looks clean and readable: headings, text, links, buttons, forms, tables, cards (`<article>`), accordions (`<details>`) and modals (`<dialog>`) are styled from their elements alone, with no classes needed. A few classes cover what HTML has no element for, such as `.container` and `.grid` for layout and `.secondary`, `.contrast` and `.outline` for button styles.

- Plain CSS: no Sass, and no build step to use or customize it.
- Light and dark color schemes that follow the visitor's system setting, or that you set with `data-theme`.
- Azure plus 19 other theme colors, and 3 options, each one extra file.
- Customizable through `--femto-*` custom properties.
- A color palette with utility classes, in a file of its own.
- Only CSS that is Baseline Widely Available, apart from some vendor-only rules and a few documented exceptions.

## Quick start

femto 3.0 is in alpha, so names and files may still change before 3.0.0. Every `@3` link and command in this README is for 3.0.0 and works once it is released: jsDelivr and npm skip prereleases when they resolve `@3`. Until then, load the alpha by its version from jsDelivr, or write `@alpha` in place of `@3` in any link:

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3.0.0-alpha.1/dist/femto.min.css">
```

or install it from npm, pinned to that version so that a later alpha, which may rename things, is not installed on its own:

```sh
npm install --save-exact @leoherzog/femto@alpha
```

### From a CDN

Link femto from [jsDelivr](https://www.jsdelivr.com/package/npm/@leoherzog/femto) in the `<head>` of your page:

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/dist/femto.min.css">
```

### Download

[Download femto](https://github.com/leoherzog/femto/archive/refs/heads/main.zip) and link `dist/femto.min.css`:

```html
<link rel="stylesheet" href="dist/femto.min.css">
```

### npm

```sh
npm install @leoherzog/femto
```

The [package](https://www.npmjs.com/package/@leoherzog/femto)'s main file is `dist/femto.min.css`, and it exports every file in `css/` and `dist/` by its path, such as `@leoherzog/femto/css/themes/jade.css`. In a CSS file that a bundler processes, import it by those paths:

```css
@import "@leoherzog/femto";
@import "@leoherzog/femto/css/themes/jade.css";
```

A bundler that rewrites CSS for older browsers can break femto's color schemes. Vite 8's production build, for example, minifies CSS with Lightning CSS for browsers older than femto supports, and rewrites every `light-dark()` into variables that resolve once on `:root`, so `data-theme` on an element no longer changes its colors. Set the bundler's CSS targets to femto's [minimum versions](#browser-support), for example in `vite.config.js`:

```js
export default { build: { cssTarget: ["chrome125", "edge125", "firefox128", "safari17.5", "ios17.5"] } };
```

List `ios17.5` as well as `safari17.5`: without it, Lightning CSS drops `-webkit-text-size-adjust`, the only form iOS Safari reads. Vite does not accept a Samsung Internet target, and `chrome125` covers Samsung Internet 27, which is built on Chromium 125.

### Starter template

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light dark">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/dist/femto.min.css">
    <title>Hello, world!</title>
  </head>
  <body>
    <main class="container">
      <h1>Hello, world!</h1>
    </main>
  </body>
</html>
```

## Classes and attributes

Most of femto works from the elements alone. These are the classes and attributes it also reads:

| Markup | What it does |
|---|---|
| `.container`, `.container-fluid` | Centers the content at a maximum width for each breakpoint, or spans the full width |
| `.grid` | Lays its children out in equal columns from 768px, in one column below |
| `.overflow-auto` | Scrolls content that overflows it, such as a wide table |
| `.secondary`, `.contrast`, `.outline` | Button styles; `.secondary` and `.contrast` also color links |
| `role="button"` | An element that looks like a button, such as a link or a `<summary>` |
| `<table class="striped">` | Shades the odd body rows, not counting rows with the `hidden` attribute |
| `<input type="checkbox" role="switch">` | A switch |
| `aria-invalid="true"` or `"false"` on a form field | Invalid or valid border colors, an icon in most text fields, and a matching color on a `<small>` right after the field |
| `role="group"`, `role="search"` | Joins buttons, inputs and selects in one row; `search` rounds the ends |
| `<details class="dropdown">` | A dropdown: a `<summary>` and a `<ul>` that opens below it |
| `<nav aria-label="breadcrumb">` | Breadcrumbs |
| `aria-busy="true"` | A loading spinner |
| `data-tooltip`, `data-placement` | A tooltip with that text, above the element or where `data-placement` (`top`, `bottom`, `left`, `right`) puts it. A switch shows none, since its `::before` is its thumb, so put the tooltip on the switch's `<label>` |
| `<dialog>` holding an `<article>` | A modal. The `.modal-is-open`, `.modal-is-opening` and `.modal-is-closing` classes, which your script sets on `<html>`, lock scrolling and run the opening and closing animations. To keep the page from shifting when `.modal-is-open` hides the scrollbar, your script can also set `--femto-scrollbar-width` on `<html>` to the scrollbar's width |
| `.close`, or `rel="prev"` on a link or button, in a modal's `<article>` | A close button: an × icon at the top right (top left in right-to-left text), in the header if there is one |
| `aria-current` (any value but `"false"`) | Shows a link, button or dropdown item as current, with its hover colors; in breadcrumbs, the current page as plain text |
| `role="link"` | An element that looks like a link |
| `disabled`, `aria-disabled="true"` | A not-allowed cursor; `aria-disabled="true"` on a `<label>` also dims it like a disabled field |
| `aria-controls` | A pointer cursor |
| `dir="rtl"` | Right-to-left text, with the form field icons, chevrons, breadcrumb separators, group and search corners, progress animation, modal close button and modal footer mirrored |

## Files

femto comes in two forms that style a page the same way: one file in `dist/`, or the modules it is built from in `css/`.

| Path | Contents |
|---|---|
| `dist/femto.min.css`, `dist/femto.css` | All of femto in one file, minified and not. Recommended. |
| `dist/femto.colors.min.css`, `dist/femto.colors.css` | The [color utilities](#color-utilities), minified and not. |
| `css/femto.css` | The entry: it `@import`s the 36 modules, in cascade order. |
| `css/femto.colors.css` | The source of the color utilities. |
| `css/tokens/`, `css/layout/`, `css/content/`, `css/forms/`, `css/components/`, `css/utilities/` | The modules. |
| `css/themes/` | The 20 [theme colors](#themes). |
| `css/options/` | The 3 [options](#options). |

Use `dist/femto.min.css` unless you need the modules. It is about 74 KB, 11 KB gzipped and 10 KB with Brotli. With `css/femto.css`, the browser finds the modules only after it has downloaded the entry, then fetches 36 files instead of one, and many small files compress worse than one. Median first contentful paint in milliseconds, with a cold cache, in Chrome and Firefox over emulated links to a local HTTPS server set up like a CDN (2026-10-28 and 29):

| Link (round trip) | HTTP/2, `css/femto.css` / one file | HTTP/3 | HTTP/1.1 |
|---|---|---|---|
| Fiber (5 ms) | 68 / 57 | 80 / 56 | 100 / 60 |
| Cable (28 ms) | 246 / 196 | 247 / 172 | 550 / 192 |
| LTE (70 ms) | 411 / 276 | 380 / 260 | 862 / 280 |
| 4G (170 ms) | 916 / 588 | 846 / 564 | 1976 / 580 |
| Slow 3G (400 ms) | 2525 / 1808 | 2258 / 1452 | 5334 / 1820 |
| 2G (800 ms) | 4622 / 3259 | 4192 / 3000 | 10135 / 3267 |

On a first visit the `@import` entry costs about 2 extra round trips on HTTP/2 and HTTP/3, and 8 to 9 on HTTP/1.1. Repeat visits, from the cache, take about 19 ms either way.

Use `css/` for a [custom module set](#custom-module-set), which can also go in a [cascade layer](#cascade-layer), or to read and edit the modules. A bundler that inlines `@import` turns `css/femto.css` into one file too.

## Themes

femto's built-in color is azure. Each of the 19 others is one file in `css/themes/`: amber, blue, cyan, fuchsia, green, grey, indigo, jade, lime, orange, pink, pumpkin, purple, red, sand, slate, violet, yellow and zinc. Load it right after femto and before your own stylesheets, and in femto's [cascade layer](#cascade-layer) if you use one:

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/dist/femto.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/css/themes/jade.css">
<link rel="stylesheet" href="styles.css">
```

A theme file is one `:root, :host` rule that sets ten theme tokens. That is the same specificity as your own overrides on `:root`, so a theme loaded after your stylesheet would replace them. For a color of your own, copy a theme file and change its values.

femto ships no prebuilt themed copies: there is no `dist/femto.jade.min.css`. To fetch femto and a theme in one request, join them in a jsDelivr combine URL:

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/combine/npm/@leoherzog/femto@3/dist/femto.min.css,npm/@leoherzog/femto@3/css/themes/jade.css">
```

This should work once femto is published, because neither file has an `@import` and every `url()` in them is a `data:` URI, but it is not yet confirmed. It does not work with `css/femto.css`: jsDelivr does not rewrite relative paths in combined files, so the entry's `@import`s would not resolve.

## Options

Each file in `css/options/` changes one default:

| File | What it does |
|---|---|
| `responsive-spacings.css` | Gives the page's header, main and footer, sections and cards (`<article>`) more vertical spacing at each breakpoint, and cards more horizontal spacing, from 1.25 to 2.25 times `--femto-spacing`. |
| `fixed-typography.css` | Keeps the root font size at 100% at every width, instead of stepping it up at each breakpoint. |
| `no-transitions.css` | Turns off transitions: links, buttons, form fields and components lose their transitions, the modal opens and closes without animating, and tooltips appear without sliding in. The loading spinner and the indeterminate progress bar still animate. |

Load an option like a theme: right after femto, before your own stylesheets, and in femto's [cascade layer](#cascade-layer) if you use one. Each file's header says what it overrides.

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/dist/femto.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/css/options/fixed-typography.css">
<link rel="stylesheet" href="styles.css">
```

## Color utilities

`femto.colors.css` is a separate, standalone file that works with or without femto. It holds the palette as custom properties, `--femto-color-<color>-<shade>` for the 20 theme colors in shades from 50 to 950, and two kinds of utility class: `.femto-color-*` sets the text color, and `.femto-background-*` sets the background color with a readable text color. Each color also has an unshaded name for one of its shades, such as `--femto-color-jade` (jade-550) with `.femto-color-jade` and `.femto-background-jade`, and `--femto-color-light` and `--femto-color-dark` are the white and black text colors the background classes use.

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/dist/femto.colors.min.css">

<p class="femto-color-jade-600">Jade text</p>
<p class="femto-background-pumpkin-300">Text on a pumpkin background</p>
```

Use `dist/femto.colors.min.css` (about 78 KB, 7 KB gzipped and under 5 KB with Brotli), `dist/femto.colors.css`, or the source, `css/femto.colors.css`.

## Color schemes

femto has a light and a dark scheme. By default it follows the visitor's system setting (`prefers-color-scheme`) on screen, and prints in the light scheme. To choose a scheme, set `data-theme="light"` or `data-theme="dark"` on `<html>` for the whole page, or on one element for a part of it.

```html
<article data-theme="dark">
  <h2>A dark card</h2>
  <p>This card and the text in it use the dark scheme, whatever the rest of the page uses.</p>
</article>
```

On an element, `data-theme` switches the colors femto sets on it and inside it, such as a card's background and the colors of headings, paragraphs, links, buttons and form fields. It does not change the text color the element inherits, which text directly inside it keeps, and it adds no background to an element femto gives none, such as a `<section>` or a `<div>`. Where you need them, set `color: var(--femto-color)` on the element, and `background-color: var(--femto-background-color)` if femto gives it no background.

Every color token is declared once, on `:root` and `:host`, with `light-dark()` where the light and dark values differ, and `data-theme` sets `color-scheme`, which picks between them, plus the few values `light-dark()` cannot carry (see below). So:

- An element that carries `data-theme` itself, such as a button, heading or form field, keeps its own colors in that scheme.
- Your own color overrides on `:root`, loaded after femto, apply in both schemes and inside every `data-theme` element. Write them with `light-dark()` to give each scheme its own value.
- `data-theme="dark"` on a web component's host makes its shadow root dark when the component loads femto there.

A `color-scheme` that your own CSS sets on an element also switches femto's colors in that subtree, as it switches the browser's own colors. `data-theme` is still the way to theme an element: it also switches the form validation icons and the chevron and loading spinner on `.contrast` buttons, which `light-dark()` cannot carry.

## Custom module set

To load only some modules, save a copy of `css/femto.css` in the same folder, since its `@import` paths are relative to it, and delete the lines you do not need:

```css
/* css/site.css: a copy of css/femto.css with the modules this site does not use deleted */
@import "tokens/base.css";
@import "tokens/breakpoints.css";
@import "layout/elements.css";
@import "tokens/schemes.css";
/* ...the other lines you keep, in the same order... */
@import "utilities/reduce-motion.css";
```

Keep the lines in their order, which is the cascade order, and keep the first four: `tokens/base.css`, `tokens/breakpoints.css`, `layout/elements.css` and `tokens/schemes.css`. They hold the tokens and per-element settings the other modules read; without `layout/elements.css`, for example, headings lose their sizes and weights, and search fields their rounded ends. The copy loads module by module, like `css/femto.css`; a bundler that inlines `@import` turns it into one file. If you install femto from npm, write the same list in your own CSS with package paths, such as `@import "@leoherzog/femto/css/tokens/base.css";`, instead of copying the file. If you also load `no-transitions.css`, copy it too and delete its rules for the modules you left out.

## Cascade layer

femto is not in a cascade layer. To put it in one, import it with `layer()`, and import your theme and option files into the same layer:

```css
/* Paths relative to femto's css/ folder */
@import url(femto.css) layer(femto);
@import url(themes/jade.css) layer(femto);
@import url(options/no-transitions.css) layer(femto);

/* Your own rules follow, unlayered */
```

From npm, use package paths instead, such as `@import "@leoherzog/femto/css/femto.css" layer(femto);`. Your unlayered rules then override femto's, whatever their specificity, except femto's few `!important` declarations. Theme and option files belong in femto's layer: left unlayered, they would compete with your unlayered rules by specificity instead of always losing to them, and would override any rules you put in layers of your own. `dist/femto.min.css` can be imported into a layer the same way.

## Shadow roots

femto declares its tokens on `:host` as well as `:root`, so it also styles the inside of a shadow root that loads it, and the host's `data-theme` picks the scheme there. A `<link rel="stylesheet">` inside the shadow root works with any femto file.

A constructable stylesheet (`adoptedStyleSheets`) needs the text of `dist/femto.css` or `dist/femto.min.css`. `CSSStyleSheet.replace()` and `replaceSync()` drop `@import` rules, so a sheet made from `css/femto.css`'s text would have no rules at all.

```js
// In a module script. One sheet can be adopted by every shadow root that needs femto.
const sheet = new CSSStyleSheet();
sheet.replaceSync(await (await fetch("dist/femto.min.css")).text());
document.querySelector("my-widget").shadowRoot.adoptedStyleSheets = [sheet];
```

## Browser support

femto targets Baseline Widely Available on its release date, which is no earlier than 2026-11-13, when `light-dark()` becomes Widely Available:

| Browser | Minimum version |
|---|---|
| Chrome and Edge | 125 |
| Firefox | 128 |
| Safari, macOS and iOS | 17.5 |
| Samsung Internet | 27 |

Each minimum version is at or above what Baseline Widely Available maps to on 2026-11-13, Safari 17.5 being the first Safari with `light-dark()`. A few features femto uses are missing or partial in some of them, and each is either covered by a vendor-prefixed form or ignored harmlessly. Safari 17.5 reads `backdrop-filter` and `user-select` only with their `-webkit-` prefix, and iOS Safari reads `text-size-adjust` only that way. Browsers that lack `resize`, `::selection`, the `ui-monospace` font or some `cursor` keywords ignore them, and `accent-color`, partial in some, has no visible effect on femto's own controls. femto also has vendor-only rules, such as `-webkit-tap-highlight-color`, `@-moz-document` and the `::-webkit-` and `::-moz-` form control pseudo-elements, which other browsers ignore. The parity tests run in recent Chrome, Firefox and Safari, not in these versions.

`npm run lint` runs the `use-baseline` rule of @eslint/css over every file in `css/`, with the Baseline data of web-features 3.42.0 from October 2026. It checks property names, at-rule names, `@media` features, pseudo-classes and pseudo-elements, and the keywords, functions and units of ordinary declarations. It does not check custom property values, which is where `light-dark()` and the font stacks live, values nested inside other functions, vendor-prefixed names or browser versions. Its exceptions are listed and explained in `eslint.config.mjs`.

Browsers without `light-dark()`, which means Chrome and Edge before 123, Firefox before 120, Safari before 17.5 and Samsung Internet before 27, do not get a plainer femto: they get a broken one. Every color token whose light and dark values differ fails where it is used, so form fields lose their borders and backgrounds and some button labels disappear. Tools that rewrite `light-dark()` for those browsers cause a narrower break in supported ones: `data-theme` on an element stops changing its colors; see [npm](#npm).

## Contributing

Edit the files in `css/`, and never edit `dist/` by hand. Then install the pinned dev tools, check and build:

```sh
npm ci
npm run lint
npm run build
```

`npm run build` runs `build.mjs`, which uses esbuild to inline `css/femto.css` and `css/femto.colors.css` into `dist/`, plain and minified; it only inlines and minifies. Commit `dist/` with your change. The Build workflow (`.github/workflows/build.yml`) lints `css/` and rebuilds `dist/` on every push and pull request. On `dev` it commits `dist/` when the build changed it, so if you forget, pull before your next push; anywhere else, a stale `dist/` fails the check. The parity tests are described in [tests/README.md](tests/README.md).

Read [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md) before you open an issue or a pull request.

## Migrating from Pico

femto 3.0 is derived from Pico CSS 2.1.1, copyright 2019-2024 Pico, under the MIT License (see [LICENSE.md](LICENSE.md)). It keeps every element and feature of Pico's default build, its 20 theme colors, its options and its color utilities, rewritten as plain CSS with femto names.

### New file names and URLs

| Pico 2.1.1 | femto 3.0 |
|---|---|
| npm `@picocss/pico` | npm `@leoherzog/femto` |
| Composer `picocss/pico` | None; use npm, a CDN or the [download](#download) |
| `css/pico.min.css`, `css/pico.css` | `dist/femto.min.css`, `dist/femto.css` |
| `css/pico.colors.min.css`, `css/pico.colors.css` | `dist/femto.colors.min.css`, `dist/femto.colors.css` |
| `css/pico.<color>.min.css` | `dist/femto.min.css`, then `css/themes/<color>.css` |
| The classless and fluid classless builds, with or without a color | `dist/femto.min.css`, plus a theme file for a color; see [Dropped builds](#dropped-builds) |
| The conditional builds | None; see [Dropped builds](#dropped-builds) |

The one-file builds moved from `css/` to `dist/`, and `css/femto.css` is now the `@import` entry. On jsDelivr, `https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css` becomes `https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/dist/femto.min.css`.

A themed build such as `pico.jade.min.css` becomes femto plus `css/themes/jade.css`: one combine URL (expected to work once femto is published, but not yet confirmed; see [Themes](#themes)), or two `<link>` tags.

```html
<!-- One request -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/combine/npm/@leoherzog/femto@3/dist/femto.min.css,npm/@leoherzog/femto@3/css/themes/jade.css">

<!-- Or two -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/dist/femto.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@leoherzog/femto@3/css/themes/jade.css">
```

### Find and replace

Replace `pico` with `femto` in class names and custom properties, in your HTML, CSS and scripts. femto has no `--pico-*` aliases, so every name needs the change:

- Custom properties: `--pico-primary` becomes `--femto-primary`, and every other `--pico-` name likewise.
- Color utility classes: `.pico-color-jade-500` becomes `.femto-color-jade-500`, and `.pico-background-*` becomes `.femto-background-*`.

Change file paths, URLs and package names by the table above, not by find and replace: the one-file builds moved to `dist/`, and the packages have new names. Data attributes keep their names: `data-theme`, `data-tooltip` and `data-placement`.

### Dropped builds

- The conditional builds (`pico.conditional*.css`), which styled only what is inside `.pico`, are gone, with their `$parent-selector` setting. femto styles the whole page, or a shadow root that loads it. Remove the `.pico` classes.
- The classless builds (`pico.classless*.css` and `pico.fluid.classless*.css`) are gone. Load femto and put a container class on the page's header, main and footer: `.container` for centered widths, or `.container-fluid` for the full width.

```html
<body>
  <header class="container">...</header>
  <main class="container">...</main>
  <footer class="container">...</footer>
</body>
```

### Sass settings

femto has no Sass. Each Pico 2.1.1 setting is now a file, a custom property, or gone:

| Pico 2.1.1 | femto 3.0 |
|---|---|
| `$theme-color` | `css/themes/<color>.css`, after femto. Azure is built in. |
| `$enable-responsive-spacings: true` | `css/options/responsive-spacings.css` |
| `$enable-responsive-typography: false` | `css/options/fixed-typography.css` |
| `$enable-transitions: false` | `css/options/no-transitions.css` |
| `$modules` | A [custom module set](#custom-module-set) |
| `$breakpoints` | Fixed at 576, 768, 1024, 1280 and 1536px |
| `$css-var-prefix` | Gone: always `--femto-` |
| `$semantic-root-element` | Gone: always `body` |
| `$enable-semantic-container`, `$enable-viewport` | Gone with the classless builds: use `.container`, or `.container-fluid` where `$enable-viewport` was false |
| `$enable-classes` | Gone: classes are always on |
| `$enable-important` | Gone: femto keeps the default build's `!important` declarations |
| `$parent-selector` | Gone with the conditional builds |
| `pico.colors` settings | Gone: `femto.colors.css` is a static file |

Any other change is a custom property override on `:root`, after femto, such as `:root { --femto-border-radius: 0; }`. Sass palette variables such as `$azure-550` are custom properties in `femto.colors.css`, such as `var(--femto-color-azure-550)`.

If your project still builds with Sass, `@use "pkg:@leoherzog/femto";` includes `dist/femto.min.css`. Do not `@use` `css/femto.css`: Sass leaves its `@import`s as they are, and they would not resolve from your output file.

### Color scheme changes

Color tokens are now declared once, and `data-theme` sets the scheme instead of redeclaring the color tokens (see [Color schemes](#color-schemes)). That changes five things:

- `data-theme` on a button, heading or form field keeps that element's own colors in the chosen scheme. In Pico 2.1.1 such an element took the page's background and text colors: on a dark page, `<button data-theme="light">` was a white box that turned blue on hover.
- `data-theme="dark"` on a web component's host makes its shadow root dark when the component loads femto there. When only the shadow root loaded Pico 2.1.1, it gave that shadow root no color tokens.
- Custom color overrides work on plain `:root` and reach inside `data-theme` elements. Pico 2.1.1 ignored them in the light and automatic dark schemes, where its scheme selectors outranked `:root`, and inside every nested `data-theme` element, which redeclared the tokens. Likewise, your own rules that set `--femto-form-element-focus-color` on a checkbox or radio now take effect from specificity (0,1,1); Pico 2.1.1's scheme selectors outranked them below (0,2,1) or (0,3,1).
- A `color-scheme` set on an element without `data-theme` now switches femto's colors in that subtree. `data-theme` remains the way to theme an element.
- A script that reads a color token with `getPropertyValue()` gets `light-dark(...)` text where the schemes differ, such as for `--femto-primary`, where Pico 2.1.1 gave a color. To get the color in effect, set the token on a property, such as `color: var(--femto-primary)`, and read that property's computed value.

### Supported browsers

Pico 2.1.1 supported every browser in browserslist's `defaults`, with prefixes added by autoprefixer. femto 3.0 supports Chrome and Edge 125, Firefox 128, Safari 17.5 and Samsung Internet 27 (see [Browser support](#browser-support)), and drops the `-ms-` rules, `::-webkit-input-placeholder` and `::-moz-list-bullet`. In browsers without `light-dark()`, femto's colors and form fields break rather than degrade, so stay on Pico 2.1.1 if you need them.

### Other changes

- Firefox shows its keyboard focus ring again on elements that set no outline of their own, such as `video` and tooltips with `tabindex`: femto drops 2.1.1's `:-moz-focusring { outline: none }`. It also draws the focus and `aria-invalid` rings on a field the user has left invalid, as Chrome and Safari already did, because femto drops `:-moz-ui-invalid { box-shadow: none }`.
- Some rendering bugs of 2.1.1 are fixed, such as an indeterminate `<progress>` that looked complete in Firefox with reduced motion. The [changelog](CHANGELOG.md#fixed) lists them.
- The focus ring of `role="group"` and `role="search"` inside a `data-theme` element follows that element's scheme.
- With `no-transitions.css`, `--femto-transition` is `0s` (2.1.1 kept `0.2s ease-in-out`), so your own rules that read it stop animating too, and the group focus ring no longer fades.
- Two new tokens: `--femto-primary-inverse-filter`, the filter for the loading spinner on primary buttons, which a theme of your own sets to `brightness(0) invert(0)` when its `--femto-primary-inverse` is dark, and `--femto-grid-template-columns`, which `.grid` reads.
- If you used a classless build, classes such as `.grid`, `.secondary`, `.dropdown` and `.striped` that it ignored are now styled.

Every difference from Pico 2.1.1 that the parity tests found is registered, with its reason, in [tests/divergences/](tests/divergences/), and [CHANGELOG.md](CHANGELOG.md) lists the changes in each release.

## License

femto is released under the MIT License. See [LICENSE.md](LICENSE.md).
