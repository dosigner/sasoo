# Sasoo Release Checklist

## Scope

This checklist covers the tagged desktop release flow for Sasoo on macOS ARM and Windows.

Current automated workflows:

- [release.yml](/Users/dongj/Documents/논문/.github/workflows/release.yml)

Current build plan:

- [electron-build-plan.md](/Users/dongj/Documents/논문/sasoo/docs/03-release/electron-build-plan.md)

Current local artifact verifiers:

- [verify-mac-artifacts.js](/Users/dongj/Documents/논문/sasoo/scripts/verify-mac-artifacts.js)
- [verify-win-artifacts.js](/Users/dongj/Documents/논문/sasoo/scripts/verify-win-artifacts.js)

## Before Tagging

1. Confirm the version is aligned in:
   - [VERSION](/Users/dongj/Documents/논문/sasoo/VERSION)
   - [package.json](/Users/dongj/Documents/논문/sasoo/package.json)
   - [frontend/package.json](/Users/dongj/Documents/논문/sasoo/frontend/package.json)
   - [backend/main.py](/Users/dongj/Documents/논문/sasoo/backend/main.py)
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
   - [sasoo/.gitignore](/Users/dongj/Documents/논문/sasoo/.gitignore)
6. Run the frontend validation:
   - `cd /Users/dongj/Documents/논문/sasoo/frontend && pnpm build`
7. Run backend test validation:
   - `cd /Users/dongj/Documents/논문/sasoo/backend && ./.venv/bin/python -m unittest discover -s services -t . -p 'test*.py'`
   - `cd /Users/dongj/Documents/논문/sasoo/backend && ./.venv/bin/python -m unittest discover -s api -t . -p 'test*.py'`

## Local Smoke Checks

macOS ARM:

1. `cd /Users/dongj/Documents/논문/sasoo && pnpm build:mac:release`
2. Open the generated ZIP from [dist](/Users/dongj/Documents/논문/sasoo/dist)
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

Tagged release:

1. Push `main`
2. Push the tag:
   - `git push origin vX.Y.Z`
3. GitHub Actions will:
   - build macOS ARM on `macos-14`
   - build Windows on `windows-latest`
   - use Python `3.12`
   - verify generated artifacts
   - upload assets to the matching GitHub draft release

Manual rerun for an existing tag:

1. Open Actions
2. Run `Release`
3. Enter the exact tag, for example `v0.7.0`

## Signing And Trust

macOS releases are currently distributed as unsigned, unnotarized ZIP files. Every release note and the repository README must disclose this and provide the limited `xattr -dr com.apple.quarantine /Applications/Sasoo.app` installation procedure. Never describe the macOS artifact as signed, notarized, or Gatekeeper-approved.

Only use the `xattr` workaround for an artifact downloaded directly from the official `dosigner/sasoo` GitHub Releases page. It removes quarantine protection; it does not verify the publisher or make the app pass Apple's signing and notarization checks.

Windows Release publishing remains blocked unless Authenticode secrets are configured:

- Windows:
  - `WIN_CSC_LINK`
  - `WIN_CSC_KEY_PASSWORD`

The release workflow verifies macOS ZIP extraction and update-manifest integrity. It verifies the Windows installer with `Get-AuthenticodeSignature`.

## Release Completion

1. Confirm the draft GitHub release contains:
   - mac ZIP
   - mac blockmap
   - `latest-mac.yml`
   - Windows installer `.exe`
   - Windows blockmap
   - `latest.yml`
2. Add release notes
3. Publish the draft release
4. Keep one final manual install check on each target OS before broad distribution

## Known Risk

The backend packaging step can warn on Python 3.14+ because release packaging is validated on Python 3.12. Keep the release runners on Python 3.12 unless backend dependencies are upgraded.
