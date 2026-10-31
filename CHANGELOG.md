# Changelog

All notable changes to femto are listed here. femto 3.0 is derived from Pico CSS 2.1.1, so its first entry lists how it differs from Pico 2.1.1.

## 3.0.0-alpha.1 (unreleased)

The first alpha of femto 3: Pico CSS 2.1.1's default build rewritten as plain CSS, with no Sass. It keeps every element and feature of Pico's default build, its 20 theme colors, its options and its color utilities. The README's [Migrating from Pico](README.md#migrating-from-pico) section explains how to switch.

### Changed

- The source is plain CSS modules in `css/`, imported in cascade order by `css/femto.css`. The one-file builds are in `dist/`: `femto.css`, `femto.min.css`, `femto.colors.css` and `femto.colors.min.css`, made by esbuild, which only inlines and minifies.
- `--pico-*` custom properties are `--femto-*`, and the `.pico-color-*` and `.pico-background-*` utilities are `.femto-color-*` and `.femto-background-*`.
- The npm package is `@leoherzog/femto`.
- Theme colors and options are small files loaded after femto, `css/themes/<color>.css` and `css/options/*.css`, instead of separate builds.
- Color tokens are declared once, on `:root, :host`, with `light-dark()`, and `data-theme` sets `color-scheme`. As a result:
  - An element that carries `data-theme` itself, such as a button, heading or form field, keeps its own colors in that scheme.
  - `data-theme="dark"` on a shadow host makes its shadow root dark, including the contrast icon filters and the focus ring of checkboxes and radios.
  - Custom color overrides on plain `:root` apply in both schemes and inside `data-theme` elements. Rules that set `--femto-form-element-focus-color` on a checkbox or radio take effect from specificity (0,1,1).
  - A `color-scheme` set on an element switches femto's colors in that subtree.
  - The focus ring of `role="group"` and `role="search"` inside a `data-theme` element follows that element's scheme.
  - `getPropertyValue()` returns `light-dark(...)` text for color tokens whose light and dark values differ.
- The minimum browsers are Chrome and Edge 125, Firefox 128, Safari 17.5 and Samsung Internet 27, where Pico 2.1.1 supported browserslist's `defaults`. Older browsers get broken colors and form fields, not a plainer page.
- Firefox's keyboard focus ring is no longer hidden on elements that set no outline of their own, and Firefox now draws the focus and `aria-invalid` rings on a field the user has left invalid, as Chrome and Safari already did.
- `no-transitions.css` sets `--femto-transition: 0s`, so the group focus ring no longer fades and your own rules that read the token stop animating. Being an appended file, it resets the tooltip slide tokens to `initial` instead of removing them, and leaves the modal and tooltip `@keyframes` defined.
- The root rule matches a shadow host with `:host` instead of `:where(:host)`, so it also applies in Safari 17.5 to 18.1, which never match `:host` inside `:where()`. A component's own `:host` rule now needs to come after femto to override it.

### Added

- `--femto-primary-inverse-filter`, the filter for the loading spinner on primary buttons, which Pico 2.1.1 picked at compile time.
- `--femto-grid-template-columns`, which `.grid` reads.

### Removed

- Sass and every Sass setting. The README's Sass settings table lists what replaces each one.
- The classless, fluid classless and conditional builds, with their `$enable-semantic-container`, `$enable-viewport` and `$parent-selector` settings.
- The prebuilt themed copies, such as `pico.jade.min.css`.
- The Composer package. Install femto from npm, link it from a CDN or download it.
- The `-ms-` rules, `::-webkit-input-placeholder`, `::-moz-list-bullet`, `:-moz-focusring { outline: none }` and `:-moz-ui-invalid { box-shadow: none }`.

### Fixed

Rendering bugs that Pico 2.1.1 has. Where Pico has an open issue for one, it is linked.

- In Firefox, an indeterminate `<progress>` shows the empty track when the user prefers reduced motion, as in Chrome and Safari, instead of a full bar that looked complete.
- A right-to-left breadcrumb shows only its divider between items, as a left-to-right one does, instead of also a stray backslash after the link in every item but the last ([picocss/pico#734](https://github.com/picocss/pico/issues/734)).
- `[role=search]` and `[role=group]` skip a `hidden` element or `<input type="hidden">` placed first or last, so the search pill and the group keep their rounded ends and the first visible control stays inside the group, instead of a flat end and a 1px overhang ([picocss/pico#736](https://github.com/picocss/pico/issues/736), [picocss/pico#748](https://github.com/picocss/pico/pull/748)).
- In a narrow column, such as one of three `.grid` columns at the medium breakpoint, a date or time input in `role="group"` or `role="search"` shrinks like a text field and clips its text, instead of pushing the group's button over the next column. Next to another field in a group it now shares the width, so at phone widths its text can be clipped where Pico 2.1.1 squeezed the other field. A `<fieldset>` also stays inside its column or container instead of growing to fit its widest content, such as a date field, a long word, a `<pre>` or a table, which now overflows it as it would a `<div>`, or scrolls inside `.overflow-auto` ([picocss/pico#733](https://github.com/picocss/pico/issues/733)).
- A dropdown in a `<nav>` lines up with the nav links beside it: Firefox before 143 no longer draws it a few pixels above them, and in current browsers its text no longer sits one border width above the link text ([picocss/pico#498](https://github.com/picocss/pico/issues/498)).
- A `[role=group]` or `[role=search]` that ends a nav item is centered with the other items, instead of keeping its bottom margin, which lifted it about half a rem and made the nav a rem taller. In an aside nav it is spaced from the next item like the other items. Helper text or another group after it keeps the margin ([picocss/pico#699](https://github.com/picocss/pico/issues/699)).
- In Firefox 143 and later, the list of an open dropdown in a `<nav>` lines up under its summary, as in Chrome, instead of shrinking to its items or, when right-aligned with `dir="rtl"` or in a right-to-left page, sitting beside the summary over the neighboring links. Safari 18.4 is reported to have the same bug. In Chrome too, the list now opens under its summary when text precedes the dropdown in its nav item. A nav dropdown wrapped in a `<label>` is now spaced from the label text as it is outside a nav, about 4px lower. In Firefox before 143, a dropdown in an `<aside>` nav now fills its item, and text before a nav dropdown sits on its own line, as in Chrome and newer Firefox ([picocss/pico#701](https://github.com/picocss/pico/issues/701), [picocss/pico#671](https://github.com/picocss/pico/issues/671)).
- A `<ul>`, `<ol>` or `<dl>` nested in another list starts a quarter of the typography spacing below its item, and the next item follows at the usual item gap, instead of the nested list starting flush and leaving a full paragraph gap after it ([picocss/pico#672](https://github.com/picocss/pico/issues/672)).
- In a `.striped` table, an odd body row or cell under a `data-theme` other than the page's (on the table, its `<tbody>`, the row or the cell) shows the stripe on that scheme's background, as the even rows do, instead of on the page's background, where its text was nearly unreadable ([picocss/pico#624](https://github.com/picocss/pico/issues/624)).

### Known issues

- A bundler that rewrites CSS for browsers older than femto's minimums breaks `data-theme` on elements. Vite 8's default production build is one; the README's npm section shows how to set its CSS targets.
- The jsDelivr combine URL for femto plus a theme is expected to work but has not been confirmed.
