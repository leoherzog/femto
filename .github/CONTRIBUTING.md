# Contributing to femto

Thanks for your interest in contributing to femto! Please take a moment to review this document before opening an [issue](https://github.com/leoherzog/femto/issues) or a [pull request](https://github.com/leoherzog/femto/pulls).

## Issues

The [issue tracker](https://github.com/leoherzog/femto/issues) is the place for bug reports, questions and feature ideas. Please search open and closed issues first. For a bug, use the bug report template and include a reduced test case.

## Pull requests

Good pull requests, patches, improvements, and new features are a fantastic help.

**Please ask before starting work on any significant new features.**
We recommend that you first [open an issue](https://github.com/leoherzog/femto/issues/new) to suggest your feature idea.

The [`dev`](https://github.com/leoherzog/femto/tree/dev) branch is open for pull requests.

**Edit the files in [`css/`](../css/) directly, never [`dist/`](../dist/).** `npm run build` writes `dist/` from `css/`. After `npm ci` installs the dev tools, run these before you open a pull request:

- `npm run build`, and commit the `dist/` files it changes
- `npm run lint`
- `uv run tests/static_checks.py` (in a new clone, first fetch tag `v2.1.1` as [`tests/reference/README.md`](../tests/reference/README.md) describes, then run `uv run tests/reference/build_references.py copies`, which writes the gitignored 2.1.1 references from it)
- for a change to the CSS, the parity harness, as [`tests/README.md`](../tests/README.md) describes

The [Build workflow](workflows/build.yml) lints `css/` and rebuilds `dist/` on every push and pull request. If a push to `dev` forgets the build, the workflow commits `dist/` after it, so pull before your next push. Anywhere else, including a pull request, a stale `dist/` fails the check.

Please follow the [code of conduct](CODE_OF_CONDUCT.md), and report security problems privately as [SECURITY.md](SECURITY.md) describes.
