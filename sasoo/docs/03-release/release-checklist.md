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
   - `cd /Users/dongj/Documents/논문/sasoo/backend && ./.venv/bin/python -m unittest discover -s services -p 'test*.py'`
   - `cd /Users/dongj/Documents/논문/sasoo/backend && ./.venv/bin/python -m unittest discover -s api -p 'test*.py'`

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

Windows:

1. Run on a real Windows machine or Windows CI runner
2. `cd <repo>\sasoo && pnpm build:win:release`
3. Validate:
   - Installer `.exe` is produced
   - `latest.yml` exists
   - Installer launches without immediate crash
   - Backend bundle starts
   - PDF open, analysis, and docked chat work

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
3. Enter the exact tag, for example `v0.6.7`

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

### How the env-gated signing scaffolding works

Signing and notarization are wired to activate purely by registering the GitHub
Actions secrets above — no code change is needed when a certificate is obtained.

- `.github/workflows/release.yml` runs a `Configure macOS signing (env-gated)`
  step (and a `Configure Windows signing (env-gated)` step) that inject each
  secret into `GITHUB_ENV` **only when it is non-empty**. An empty `CSC_LINK`
  would make electron-builder call `importCertificate("")` and break the build,
  so absent secrets leave the environment untouched — the build is byte-for-byte
  identical to the current unsigned pipeline. Each step logs `ENABLED`/`DISABLED`.
- When no macOS certificate is present, the step sets
  `CSC_IDENTITY_AUTO_DISCOVERY=false` so electron-builder never picks up an
  unrelated keychain identity.
- `package.json` `build.mac` sets `hardenedRuntime`, `entitlements`
  ([build/entitlements.mac.plist](/Users/dongj/Documents/논문/sasoo/build/entitlements.mac.plist)),
  and `entitlementsInherit`
  ([build/entitlements.mac.inherit.plist](/Users/dongj/Documents/논문/sasoo/build/entitlements.mac.inherit.plist)).
  These keys are only consumed when a signing identity exists, so they are inert
  for unsigned builds. The entitlements enable JIT, unsigned executable memory,
  and library-validation bypass required by the bundled JVM and the PyInstaller
  backend.
- `build.mac.notarize` is set to `false` to disable electron-builder's built-in
  notarization (which is ambiguous about `teamId`). Notarization is handled
  exclusively by the `afterSign` hook
  ([scripts/notarize.js](/Users/dongj/Documents/논문/sasoo/scripts/notarize.js)),
  which is a no-op unless `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, and
  `APPLE_TEAM_ID` are all set.
- `@electron/osx-sign` signs Mach-O binaries inside `extraResources`
  automatically once an identity is present, so the bundled backend needs no
  manual `codesign` step.

### Verifying a signed build once certificates are available

macOS (run on the packaged `Sasoo.app`):

- `codesign --verify --deep --strict --verbose=2 /Applications/Sasoo.app`
- `spctl --assess --type execute --verbose=2 /Applications/Sasoo.app`
- `xcrun stapler validate /Applications/Sasoo.app`

Windows (run on the packaged installer `.exe`):

- `signtool verify /pa /v Sasoo-Setup.exe`
- or `powershell -Command "Get-AuthenticodeSignature -LiteralPath 'Sasoo-Setup.exe' | Format-List"`

The artifact verifiers automate the conditional form of these checks:

- [verify-mac-artifacts.js](/Users/dongj/Documents/논문/sasoo/scripts/verify-mac-artifacts.js)
  runs `codesign` and, if the app is signed, `spctl` and `xcrun stapler`. On an
  unsigned build it logs `unsigned build — signature checks skipped` and passes.
- [verify-win-artifacts.js](/Users/dongj/Documents/논문/sasoo/scripts/verify-win-artifacts.js)
  runs `Get-AuthenticodeSignature`; `NotSigned` is skipped, `Valid` passes, any
  other status fails.
- Set `SASOO_REQUIRE_SIGNED=1` to promote an unsigned artifact to a hard failure
  (use this once signing is expected on every release).
- macOS verifiers also assert the bundled Java runtime is present; set
  `SASOO_SKIP_JAVA_BUNDLE=1` to skip that check for backend-less test builds.

### Follow-up after signing is stable

The macOS auto-update download currently bypasses `electron-updater` because
unsigned builds cannot be installed by Squirrel.Mac. Once signing and
notarization are verified on real releases, switch the mac branch in
[electron/updater.ts](/Users/dongj/Documents/논문/sasoo/electron/updater.ts) (the
`updater:download` handler around lines 49-53) from opening the GitHub Releases
page in the browser back to `autoUpdater.downloadUpdate()`, so macOS gets the
same in-app update flow as Windows.

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
