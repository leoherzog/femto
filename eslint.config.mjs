// Lint for the hand-written CSS in css/. It only checks, never transforms (PLAN Decision 1).
// Target: Baseline Widely Available on the release date, no earlier than 2026-11-13 (PLAN Decision 7).
// Run: npx eslint css
import { defineConfig } from "eslint/config";
import css from "@eslint/css";

export default defineConfig([
  // Only css/ is linted. The 2.1.1 build output (css/pico*.css) and its PostCSS config stay until
  // Phase 5 deletes them; the other folders hold Sass, scripts and test tooling, not shipped CSS.
  {
    ignores: [
      "css/pico*.css",
      "css/postcss.config.js",
      "docs/",
      "scripts/",
      "scss/",
      "tests/",
      "eslint.config.mjs",
    ],
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
          // accepts and PLAN Conversion rules say to keep as it is. CSSTree's grammar requires a
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
      // (PLAN Settings: $enable-important is dropped and its default output stays).
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

          // (b) Widely Available before the release date. The bundled data is year-granular and
          // dated before 2026-11-13, so it still reports these as Newly Available.
          allowFunctions: [
            // light-dark(): Baseline low 2024-05-13, Widely 2026-11-13 (web-features 3.44.0).
            "light-dark",
          ],

          // (a) Standard halves of the hand-written prefix pairs PLAN Conversion rules keep. Each
          // is written next to its prefixed form, which the target browsers without the
          // standard property use.
          allowProperties: [
            // -webkit-backdrop-filter is kept for Safari 17.5 to 17.x; backdrop-filter is
            // Baseline 2024 (Safari 18).
            "backdrop-filter",
            // -webkit-text-size-adjust is kept for Safari; unprefixed text-size-adjust is
            // Chromium only and is Limited Availability.
            "text-size-adjust",
            // -webkit-user-select is kept for Safari; unprefixed user-select is Limited
            // Availability only because Safari needs the prefix.
            "user-select",

            // (c) 2.1.1 features that are not Baseline but that browsers without them ignore
            // harmlessly, kept for parity (owner decision, 2026-10-27).
            // accent-color (Color schemes): Limited because iOS Safari lacks it.
            "accent-color",
            // resize (Basics form elements: textarea): Limited on iOS.
            "resize",
            // clip (Accessibility: [aria-hidden=false][hidden]): deprecated, still applied everywhere.
            "clip",
          ],
          allowSelectors: [
            // (a) summary::marker pairs with the kept ::-webkit-details-marker, which Safari uses
            // to hide the disclosure triangle.
            "marker",
            // (c) ::selection (Typography): Limited.
            "selection",
          ],
        },
      ],
    },
  },
]);
