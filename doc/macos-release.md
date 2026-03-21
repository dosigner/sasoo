# macOS Release Pipeline

This project now treats macOS release builds as a signed-and-notarized pipeline instead of a best-effort archive export.

## Required secrets

- `CSC_LINK`: Developer ID Application certificate for electron-builder
- `CSC_KEY_PASSWORD`: password for the certificate referenced by `CSC_LINK`
- `APPLE_API_KEY`: App Store Connect API private key contents
- `APPLE_API_KEY_ID`: App Store Connect API key ID
- `APPLE_API_ISSUER`: App Store Connect API issuer ID

In CI, `APPLE_API_KEY` is written to a temporary `.p8` file before the build starts, and the resulting file path is passed to electron-builder.

## Local commands

- `pnpm clean:mac`: remove mac build outputs before rebuilding
- `pnpm build:mac`: clean and build mac artifacts without publishing
- `pnpm build:mac:release`: require Apple credentials, build, staple, and verify release artifacts
- `pnpm verify:mac-artifact`: verify archive integrity, `codesign`, `spctl`, and `latest-mac.yml`

## CI behavior

The GitHub Actions workflow at `.github/workflows/release.yml` runs on tag pushes.

- Release jobs fail before packaging if Apple credentials are missing.
- Artifacts are built on `macos-14`.
- The workflow runs notarization through electron-builder, staples the app and DMG, then verifies the generated ZIP, DMG, signatures, Gatekeeper acceptance, and `latest-mac.yml`.
- Release assets are uploaded only after verification succeeds.
