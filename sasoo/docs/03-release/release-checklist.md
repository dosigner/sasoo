# Sasoo Release Checklist

## Scope

This checklist covers the tagged desktop release flow for Sasoo on macOS ARM and Windows.

Current automated workflows:

- [release.yml](/Users/dongj/Documents/논문/.github/workflows/release.yml)

Current local artifact verifiers:

- [verify-mac-artifacts.js](/Users/dongj/Documents/논문/sasoo/scripts/verify-mac-artifacts.js)
- [verify-win-artifacts.js](/Users/dongj/Documents/논문/sasoo/scripts/verify-win-artifacts.js)

## Before Tagging

1. Confirm the version is aligned in:
   - [VERSION](/Users/dongj/Documents/논문/sasoo/VERSION)
   - [package.json](/Users/dongj/Documents/논문/sasoo/package.json)
   - [frontend/package.json](/Users/dongj/Documents/논문/sasoo/frontend/package.json)
   - [backend/main.py](/Users/dongj/Documents/논문/sasoo/backend/main.py)
2. Confirm local-only data is ignored by git:
   - [sasoo/.gitignore](/Users/dongj/Documents/논문/sasoo/.gitignore)
3. Run the frontend validation:
   - `cd /Users/dongj/Documents/논문/sasoo/frontend && pnpm lint && pnpm build`

## Local Smoke Checks

macOS ARM:

1. `cd /Users/dongj/Documents/논문/sasoo && pnpm build:mac:release`
2. Open the generated ZIP from [dist](/Users/dongj/Documents/논문/sasoo/dist)
3. Validate:
   - App launches cleanly
   - Library screen opens
   - PDF loads without toolbar regressions
   - Workbench opens and chat popup overlays correctly
   - Analysis can start and complete
   - App can close and relaunch

Windows:

1. Run on a real Windows machine or Windows CI runner
2. `cd <repo>\sasoo && pnpm build:win:release`
3. Validate:
   - Installer `.exe` is produced
   - `latest.yml` exists
   - Installer launches without immediate crash
   - Backend bundle starts
   - PDF open, analysis, and chat popup work

## GitHub Actions Release Flow

Tagged release:

1. Push `main`
2. Push the tag:
   - `git push origin vX.Y.Z`
3. GitHub Actions will:
   - build macOS ARM on `macos-14`
   - build Windows on `windows-2022`
   - verify generated artifacts
   - upload assets to the matching GitHub draft release

Manual rerun for an existing tag:

1. Open Actions
2. Run `Release`
3. Enter the exact tag, for example `v0.6.4`

## Signing And Trust

Unsigned builds can be produced without extra secrets, but production release quality should include code signing.

Recommended signing/notarization secrets for GitHub Actions:

- macOS:
  - `CSC_LINK`
  - `CSC_KEY_PASSWORD`
  - `APPLE_ID`
  - `APPLE_APP_SPECIFIC_PASSWORD`
  - `APPLE_TEAM_ID`
- Windows:
  - `WIN_CSC_LINK`
  - `WIN_CSC_KEY_PASSWORD`

If those secrets are not configured, the workflows still build artifacts, but users may see OS trust warnings.

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

The backend packaging step currently emits a warning related to Pydantic v1 compatibility on Python 3.14+. Keep the release runners on Python 3.12 unless backend dependencies are upgraded.
