// Lint for the hand-written CSS in css/. It only checks, never transforms.
// Target: Baseline Widely Available on the release date, no earlier than 2026-11-13. use-baseline
// approximates it with the Widely status in its bundled web-features 3.42.0 data (2026-10-09),
// and does not check custom property values or values nested inside functions.
// Run: npx eslint css
import { defineConfig } from "eslint/config";
import css from "@eslint/css";

export default defineConfig([
  // Only css/ is linted: it holds the hand-written CSS that ships. dist/ is esbuild's one-file
  // build of css/ (build.mjs), and the other paths are build and test tooling.
  {
    ignores: ["dist/", "build.mjs", "tests/", "eslint.config.mjs"],
  },
  {
    files: ["css/**/*.css"],
    language: "css/css",
    plugins: { css },
    extends: ["css/recommended"],
    languageOptions: {
      customSyntax: (syntax) => ({
        ...syntax,
        atrules: {
          ...syntax.atrules,
          // 2.1.1 writes `@-moz-document url-prefix() { ... }` with an empty argument, which Firefox
          // accepts and femto keeps as it is. CSSTree's grammar requires a
          // string inside url-prefix(), so the argument is made optional here.
          "-moz-document": {
            prelude:
              "[ <url> | url-prefix( <string>? ) | domain( <string> ) | media-document( <string> ) | regexp( <string> ) ]#",
          },
        },
      }),
    },
    rules: {
      // femto keeps 2.1.1's default output, including its 20 !important declarations
      // ($enable-important is dropped and its default output stays).
      "css/no-important": "off",

      // Tokens are defined in tokens/*.css and used from every other file, and the rule only
      // traces custom properties defined earlier in the same file. Property names and values
      // without var() are still validated.
      "css/no-invalid-properties": ["error", { allowUnknownVariables: true }],

      // 2.1.1 font stacks put the emoji families after the generic family on purpose
      // (--femto-font-family: var(--femto-font-family-sans-serif) ends with the emoji list),
      // and font-family is always set through tokens the rule cannot resolve across files.
      "css/font-family-fallbacks": "off",

      "css/use-baseline": [
        "error",
        {
          available: "widely",

          // (b) Widely Available by the release date, but Newly Available in the bundled data,
          // whose stored status the rule compares. femto writes light-dark() only inside custom
          // properties and @supports conditions, which the rule skips, so this entry only covers a
          // future direct use.
          allowFunctions: [
            // light-dark(): Baseline low 2024-05-13, Widely 2026-11-13 (web-features 3.44.0).
            "light-dark",
          ],

          // (a) Standard halves of the hand-written prefix pairs femto keeps. Each
          // is written next to its prefixed form, which the target browsers without the
          // standard property use.
          allowProperties: [
            // -webkit-backdrop-filter is kept for Safari 17.5 to 17.x; backdrop-filter is
            // Baseline 2024 (Safari 18).
            "backdrop-filter",
            // -webkit-text-size-adjust is kept for iOS Safari; unprefixed text-size-adjust is
            // Chromium only and is Limited Availability.
            "text-size-adjust",
            // -webkit-user-select is kept for Safari; unprefixed user-select is Limited
            // Availability only because Safari needs the prefix.
            "user-select",

            // (c) 2.1.1 features that are not Baseline but that browsers without them ignore
            // harmlessly, kept for parity.
            // accent-color (Color schemes): Limited because Chrome for Android, and Safari before
            // 26.2, apply it without the minimum contrast. femto's controls use appearance: none,
            // so it has no visible effect unless a page restores the native control.
            "accent-color",
            // resize (Basics form elements: textarea): Limited on iOS.
            "resize",
            // clip (Accessibility: [aria-hidden=false][hidden]): deprecated, still applied everywhere.
            "clip",

            // (d) femto additions that are not Baseline but that browsers without them ignore
            // harmlessly.
            // forced-color-adjust (Accessibility: forced colors): Limited because Safari lacks it,
            // and Safari has no forced colors mode.
            "forced-color-adjust",
          ],
          allowSelectors: [
            // (c) summary::marker { display: none } is kept from 2.1.1 beside
            // ::-webkit-details-marker, but display does not apply to ::marker, so it hides
            // nothing. Outside Safari the summary has no marker because it is display: flow-root
            // with list-style-type: none; in Safari, ::-webkit-details-marker hides the triangle.
            "marker",
            // (c) ::selection (Typography): Limited.
            "selection",
          ],
        },
      ],
    },
  },
]);
