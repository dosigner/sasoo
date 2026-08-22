# Sasoo Release Checklist

> 2026-08-06 현행화: v0.8.0 기준(macOS ZIP+DMG, Windows 미서명 배포)을 반영.

## Scope

This checklist covers the tagged desktop release flow for Sasoo on macOS ARM and Windows.

Current automated workflows:

- [build-check.yml](../../../.github/workflows/build-check.yml)
- [release.yml](../../../.github/workflows/release.yml)

Current build plan:

- [electron-build-plan.md](electron-build-plan.md)

Current local artifact verifiers:

- [verify-mac-artifacts.js](../../scripts/verify-mac-artifacts.js)
- [verify-win-artifacts.js](../../scripts/verify-win-artifacts.js)

## Before Tagging

1. Confirm the version is aligned in:
   - [VERSION](../../VERSION)
   - [package.json](../../package.json)
   - [frontend/package.json](../../frontend/package.json)
   - [backend/main.py](../../backend/main.py)
2. Confirm the local build machine matches the intended path:
   - macOS local validation is for `Darwin arm64`
   - Windows packaging must run on `windows-latest` CI or a real Windows machine
3. Confirm toolchain availability before packaging:
   - `node`
   - `pnpm`
   - `backend/.venv`
   - backend Python version
4. Preferred release packaging Python is `3.12`.
   - local Python `3.14.x` is acceptable for development validation, but not the release baseline
5. Confirm local-only data is ignored by git:
   - [sasoo/.gitignore](../../.gitignore)
6. Run the frontend validation:
   - `cd sasoo/frontend && pnpm tsc --noEmit`
   - `cd sasoo/frontend && pnpm test`
   - `cd sasoo/frontend && pnpm build`
   - `cd sasoo/frontend && pnpm lint`
7. Run backend test validation:
   - `cd sasoo/backend && ./.venv/bin/python -m pytest services api models`
8. Confirm both previously exposed Google API keys are disabled or deleted at the provider, and review usage, billing, and audit logs.
9. Confirm the exact release commit passed the Windows `Build Check` workflow.
10. Immutable releases are optional. To publish immutable releases, enable GitHub's **Immutable Releases** setting and configure `IMMUTABLE_RELEASES_TOKEN` with repository Administration read permission. Without the token the release is published as a mutable release.
12. Confirm the active `Release` workflow builds and publishes both macOS and Windows artifacts. Windows publishes unsigned by default (SmartScreen warning); the workflow's `Detect Windows signing capability` step switches automatically to a signed build when `WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD` are both configured.

## Local Smoke Checks

macOS ARM:

1. `cd sasoo && pnpm build:mac:release`
2. Open the generated ZIP from `sasoo/dist`
3. Validate:
   - App launches cleanly
   - Library screen opens
   - PDF loads without toolbar regressions
   - Workbench opens and docked chat behaves correctly
   - Analysis can start
   - App can close and relaunch
   - A legacy `.sasoo_key` value migrates to macOS Keychain and the file is removed

Windows:

1. Run on a real Windows machine or Windows CI runner
2. `cd <repo>\sasoo && pnpm build:win:release`
3. Validate:
   - Installer `.exe` is produced
   - `latest.yml` exists
   - Installer launches without immediate crash
   - Backend bundle starts
   - PDF open, analysis, and docked chat work
   - New API-key encryption uses Windows Credential Manager, not `.sasoo_key`

## GitHub Actions Release Flow

Current v0.8.0 tagged release:

1. Push `main`
2. Push the tag:
   - `git push origin vX.Y.Z`
3. GitHub Actions will:
   - build macOS ARM on `macos-14` and Windows on `windows-latest`
   - publish the Windows build unsigned by default (SmartScreen warning); if `WIN_CSC_LINK` and `WIN_CSC_KEY_PASSWORD` are both configured, it builds and publishes a signed Windows release instead
   - use Python `3.12`
   - verify generated artifacts
   - upload assets to the matching GitHub draft release

Manual build for an existing tag that has no GitHub release:

1. Open Actions
2. Run `Release`
3. Enter the exact tag, for example `v0.7.0`

The workflow never modifies an existing draft or published release and never replaces an existing asset. If a stale draft exists, inspect and delete it manually before starting a clean rerun.

## Signing And Trust

macOS releases are currently distributed as unsigned, unnotarized ZIP and DMG files. Every release note and the repository README must disclose this and provide the limited `xattr -dr com.apple.quarantine /Applications/Sasoo.app` installation procedure. Never describe the macOS artifact as signed, notarized, or Gatekeeper-approved.

Only use the `xattr` workaround for an artifact downloaded directly from the official `dosigner/sasoo` GitHub Releases page. It removes quarantine protection; it does not verify the publisher or make the app pass Apple's signing and notarization checks.

Windows releases currently publish unsigned by default; Windows SmartScreen will warn that the publisher is unknown. Configuring both secrets switches the workflow to a signed build automatically:

- Windows:
  - `WIN_CSC_LINK`
  - `WIN_CSC_KEY_PASSWORD`

The current release workflow verifies macOS ZIP extraction and update-manifest integrity, and verifies the Windows installer and update manifest with `verify-win-artifacts.js` — which checks the installer's `Get-AuthenticodeSignature` when signed, and skips that check for the unsigned default build.

## Release Completion

1. Confirm the draft GitHub release contains:
   - mac ZIP
   - mac DMG
   - mac blockmap
   - `latest-mac.yml`
   - Windows installer (`.exe`)
   - Windows blockmap (if generated)
   - `latest.yml`
2. Add release notes explaining that saved API keys migrate automatically when possible, and users must re-enter keys that cannot be migrated or were revoked/deleted with the provider
3. Publish the draft release
4. Keep one final manual install check on each target OS before broad distribution

## Known Risk

The backend packaging step can warn on Python 3.14+ because release packaging is validated on Python 3.12. Keep the release runners on Python 3.12 unless backend dependencies are upgraded.
