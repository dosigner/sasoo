# Attributions

`xberg-pdf-oxide` is published under the MIT licence (see `LICENSE`). This
document lists every third-party work the crate carries or derives from,
beyond the top-level `LICENSE`.

## Upstream: PDFOxide

The overwhelming majority of this crate's code is derived from
[`yfedoseev/pdf_oxide`](https://github.com/yfedoseev/pdf_oxide) ("PDFOxide")
by Yury Fedoseev, dual-licensed MIT OR Apache-2.0. `xberg-pdf-oxide` is a fork
that elects the MIT arm of that dual offer — taking a single arm of an
MIT-OR-Apache-2.0 dual licence is permitted by both licences.

`LICENSE` at the repository root reflects this lineage: it carries the
original "Copyright (c) 2025-present Yury Fedoseev" notice alongside
"Copyright (c) 2026-present Kreuzberg, Inc." for the fork's own contributions.
Upstream's pre-fork history is not reproduced in `CHANGELOG.md`; it lives in
this repository's git history and in the upstream project itself.

Upstream is the original project and where most users should go for the
unmodified library. Per upstream's trademark policy, describing this crate as
"a fork of PDFOxide" or "derived from PDFOxide" is explicitly permitted; using
upstream's names (`PDFOxide`, `pdf_oxide`) as the name of this distribution is
not, and no endorsement or affiliation with upstream or its author is implied.

## Vendored: fontdb

`src/vendor/fontdb/` vendors code derived from
[fontdb](https://github.com/RazrFalcon/fontdb) 0.24.0 by Yevhenii Reizner,
MIT-licensed:

```text
The MIT License (MIT)

Copyright (c) 2020 Yevhenii Reizner
```

(full text at `fontdb`'s own `LICENSE`, reproduced from the crates.io source
of `fontdb` 0.24.0). This code is vendored, not pulled in as a Cargo
dependency, and has been modified from upstream:

- The inlined font parser was replaced with the `fontations`/`skrifa` stack.
- `log` call sites were replaced with `tracing`.
- The unsafe memory-mapping path was removed.

## Bundled font files

The following font files are embedded into the compiled binary via
`include_bytes!` under `src/fonts/assets/`, each redistributed under its own
original licence:

| File | Licence | Upstream |
|---|---|---|
| `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf` | Bitstream Vera / DejaVu licence (permissive, requires renaming on modification) — full text in `src/fonts/assets/LICENSE-DejaVu` | DejaVu Fonts project; base glyphs © 2003 Bitstream, Inc. |
| `DroidSansFallbackFull.ttf` (~4.0 MB) | Apache License, Version 2.0 | Droid Sans Fallback, © Google Inc., from the Android Open Source Project (`frameworks/base/data/fonts`) |
| `NotoEmoji-Regular.ttf` (~419 KB) | SIL Open Font License, Version 1.1 | Noto Emoji (monochrome), © Google Inc. and contributors, <https://github.com/googlefonts/noto-emoji> |

Source and licence claims for `DroidSansFallbackFull.ttf` and
`NotoEmoji-Regular.ttf` are as stated in `src/fonts/assets/LICENSE-fallback-fonts`;
this document does not independently verify upstream's copyright beyond that
file. `DejaVuSans.ttf` and `DejaVuSans-Bold.ttf` are covered by
`src/fonts/assets/LICENSE-DejaVu`, which is the Bitstream Vera-derived DejaVu
Fonts licence; note its requirement that modified fonts be renamed to avoid
the words "Bitstream" or "Vera".

`DroidSansFallbackFull.ttf` and `NotoEmoji-Regular.ttf` are gated behind the
`cjk-form-fonts` Cargo feature per `src/fonts/assets/LICENSE-fallback-fonts`;
they are only embedded in binaries that enable it.

### Test fixture fonts

`tests/fixtures/fonts/` contains `DejaVuSansMono.ttf` and
`StandardSymbolsPS.otf`, covered by `tests/fixtures/fonts/LICENSE`, which is
the same Bitstream Vera / DejaVu Fonts licence as `src/fonts/assets/LICENSE-DejaVu`.
These are test-only fixtures, not shipped in the compiled binary.

## Non-MIT/Apache-2.0 dependencies

This crate ships under MIT alone. `deny.toml`'s `[licenses]` section is the
authoritative allow list of every licence its dependency graph may carry;
run `cargo deny check licenses` for the complete, current picture. The
permissive, non-MIT/Apache-2.0 licences on that list, and why each is present,
per `deny.toml`'s own comments:

- **BSD-3-Clause** — carried by `tiny-skia`, which enters through the
  rendering path.
- **BSD-2-Clause** — carried by `arrayref`, also on the rendering path.
- **Unicode-3.0**, **Zlib**, **ISC**, **CC0-1.0**, **BSL-1.0** — permissive
  licences carried by other transitive dependencies; see `deny.toml` for
  details.
- **Apache-2.0 WITH LLVM-exception** — pulled in transitively via
  `target-lexicon` → `pyo3-build-config` → `pyo3`.
- **NCSA** (University of Illinois/NCSA) — pulled in transitively via
  `libfuzzer-sys` → `rav1e` → `ravif` → `image 0.25.10`.
- **CDLA-Permissive-2.0** — Mozilla's CA root bundle data, via
  `webpki-roots` → `ureq`.
- **OpenSSL License** — pulled in transitively via `aws-lc-rs/fips` →
  `aws-lc-fips-sys`, only under the opt-in `fips` feature.

`deny.toml` records a locked decision against MPL-2.0 and any GPL/AGPL/SSPL
licence in the dependency graph; see that file for the rationale.

This section covers dependencies whose licence is not MIT or Apache-2.0. The
crate's ~100 transitive MIT/Apache-2.0 dependencies are not enumerated here;
`cargo deny check licenses` is the source of truth for the full dependency
licence inventory.
