# Contributing to femto

Thanks for your interest in contributing to femto! Please take a moment to review this document before submitting a [bug report](https://github.com/leoherzog/femto/issues) or a [pull request](https://github.com/leoherzog/femto/pulls).

## Bug reports

The [issue tracker](https://github.com/leoherzog/femto/issues) is the preferred channel for bug reports, but please respect the following restrictions:
- Please do not use the issue tracker for personal support requests. [Open a question in our discussion forums](https://github.com/leoherzog/femto/discussions) instead.
- Please do not use the issue tracker for feature requests. Instead, use our discussion forums to [suggest any ideas](https://github.com/leoherzog/femto/discussions) you have.

## Pull requests

Good pull requests, patches, improvements, and new features are a fantastic help.

**Please ask before starting work on any significant new features.**
We recommend that you first [suggest your feature idea in our discussion forums](https://github.com/leoherzog/femto/discussions).

The [`dev`](https://github.com/leoherzog/femto/tree/dev) branch is open for pull requests.

**Edit the files in [`css/`](../css/) directly, never [`dist/`](../dist/).** `npm run build` writes `dist/` from `css/`. After `npm ci` installs the dev tools, run these before you open a pull request:

- `npm run build`, and commit the `dist/` files it changes
- `npm run lint`
- `uv run tests/static_checks.py` (in a new clone, first run `uv run tests/reference/build_references.py copies`, which writes the gitignored 2.1.1 references from tag `v2.1.1`)
- for a change to the CSS, the parity harness, as [`tests/README.md`](../tests/README.md) describes

If a push to this repository forgets the build, the [Build workflow](workflows/build.yml) commits `dist/` after it, so pull before your next push. A pull request that forgets it gets `dist/` rebuilt when it is merged.
