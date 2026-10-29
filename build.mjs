// Builds dist/ from the modules in css/: each entry inlined into one file, plain and minified.
// Run: npm run build
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { build } from "esbuild";

const { version } = JSON.parse(readFileSync("package.json", "utf8"));

// Unminified, esbuild puts each item of a value with three or more commas on its own line. Browsers
// keep a custom property's whitespace, so getPropertyValue() would return those line breaks: put
// custom property values back on one line, as esbuild prints shorter ones.
const joinCustomProperties = (css) =>
  css.replace(/^( *)(--[\w-]+):((?:\n\1  .*)+)$/gm, (_, indent, name, value) => `${indent}${name}:${value.replace(/\n +/g, " ")}`);

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist");
for (const name of ["femto", "femto.colors"]) {
  for (const minify of [false, true]) {
    const { outputFiles } = await build({
      entryPoints: [`css/${name}.css`],
      outfile: `dist/${name}${minify ? ".min" : ""}.css`,
      bundle: true,
      // Whitespace only: esbuild's syntax minifier also rewrites custom property values (0.25rem to
      // .25rem), which getPropertyValue() returns, and saves about 30 compressed bytes.
      minifyWhitespace: minify,
      // esbuild writes an entry's own comments after the files it imports, so the header is a banner.
      legalComments: "none",
      banner: { css: `/*! ${name} ${version} | https://github.com/leoherzog/femto | MIT License */` },
      logLevel: "warning",
      write: false,
    });
    for (const { path, text } of outputFiles) writeFileSync(path, minify ? text : joinCustomProperties(text));
  }
}
