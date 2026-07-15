# Electron Build Plan For macOS + Windows

## Summary

Use a split build strategy that matches the repo's actual platform constraints:

- Run local dev/runtime and packaged artifact checks on the current macOS ARM machine.
- Keep Windows package validation on the Build Check runner or a real Windows machine; add it to the public release workflow only after signing is configured.
- Treat [release.yml](../../../.github/workflows/release.yml) as the source of truth for cross-platform release packaging.

For the current v0.7.0 public release, the workflow publishes macOS only because an Authenticode certificate is not available. Windows packaging remains a validation path until signing is configured.

This matches the current platform guards in:

- [prepare-mac-build.js](/Users/dongj/Documents/논문/sasoo/scripts/prepare-mac-build.js)
- [prepare-win-build.js](/Users/dongj/Documents/논문/sasoo/scripts/prepare-win-build.js)

## 1. Local macOS Validation Path

### Toolchain checks

Validate these before packaging:

- `node` is installed
- `pnpm` is installed
- `backend/.venv` exists
- preferred backend Python for release-quality packaging is `3.12`

Current known local state on the macOS ARM machine used for this plan:

- platform: `Darwin arm64`
- backend venv Python: `3.14.3`

Python `3.14.x` is acceptable for local development, but it is not the release baseline. Final release packaging should stay on Python `3.12`.

### Frontend validation

Run:

```bash
cd /Users/dongj/Documents/논문/sasoo/frontend
pnpm build
```

### Backend test validation

Run:

```bash
cd /Users/dongj/Documents/논문/sasoo/backend
./.venv/bin/python -m unittest discover -s services -p 'test*.py'
./.venv/bin/python -m unittest discover -s api -p 'test*.py'
```

### macOS package build

Run the repo-supported entrypoint only:

```bash
cd /Users/dongj/Documents/논문/sasoo
pnpm build:mac:release
```

This path already includes:

- platform cleanup via [prepare-mac-build.js](/Users/dongj/Documents/논문/sasoo/scripts/prepare-mac-build.js)
- backend packaging
- frontend build
- Electron build
- artifact verification via [verify-mac-artifacts.js](/Users/dongj/Documents/논문/sasoo/scripts/verify-mac-artifacts.js)

### Expected macOS outputs

Verify `dist/` contains:

- one `*-mac.zip`
- one `.blockmap`
- `latest-mac.yml`

### Packaged macOS smoke checks

After building:

1. Unzip and open the app.
2. Confirm the app launches without an immediate crash.
3. Confirm Library opens.
4. Open a paper or PDF.
5. Open Workbench.
6. Start analysis.
7. Close and relaunch the app.

## 2. Windows Build Path

Do not attempt Windows packaging on the current macOS machine.

Use one of these repo-aligned paths:

- GitHub Actions Build Check on `windows-latest`
- a real Windows machine running `pnpm build:win:release`

### Windows execution sequence

On Windows:

1. Check out the repo or target tag.
2. Install Node and pnpm.
3. Install Python `3.12`.
4. Install backend requirements and `pyinstaller`.
5. Run:

```powershell
cd <repo>\sasoo
pnpm build:win:release
```

### Expected Windows outputs

Verify `dist/` contains:

- one `.exe`
- one `.exe.blockmap`
- `latest.yml`

### Windows smoke validation

Run at least these checks:

1. Installer launches.
2. App starts without immediate crash.
3. Bundled backend starts.
4. PDF open works.
5. Analysis starts.

## 3. Release-Quality Cross-Platform Path

Use the existing GitHub Actions release workflow for final packaging. The current v0.7.0 public matrix is macOS only:

- mac build on `macos-14`
- Python pinned to `3.12`

Trigger paths:

- push a tag such as `vX.Y.Z`
- manually dispatch the `Release` workflow with an existing tag

Expected release assets:

- mac ZIP
- mac blockmap
- `latest-mac.yml`

## 4. Important Constraints

- Keep `pnpm build:mac:release` and `pnpm build:win:release` as the supported platform release entrypoints.
- Do not add mac-to-Windows cross-build logic unless the platform-guard design is intentionally changed in:
  - [prepare-mac-build.js](/Users/dongj/Documents/논문/sasoo/scripts/prepare-mac-build.js)
  - [prepare-win-build.js](/Users/dongj/Documents/논문/sasoo/scripts/prepare-win-build.js)
- Do not treat local Python `3.14.x` packaging as release-equivalent.
- Keep CI and release runners on Python `3.12`.

## Artifact Contracts

No API or frontend interface changes are required for this build plan.

Expected artifact contracts remain:

- macOS: `*-mac.zip`, `.blockmap`, `latest-mac.yml`
- Windows: `.exe`, `.exe.blockmap`, `latest.yml`

Backend bundle contract remains:

- packaged backend exists under `backend/dist/sasoo-backend`
- Electron `extraResources` copies that bundle into the app package from [package.json](/Users/dongj/Documents/논문/sasoo/package.json)

## Test Plan

### Pre-build checks

- frontend build succeeds
- backend services tests pass
- backend API tests pass

### macOS artifact checks

- `pnpm build:mac:release`
- `scripts/verify-mac-artifacts.js` passes
- packaged app launches and core flows work

### Windows artifact checks

- `pnpm build:win:release` on Windows or CI
- `scripts/verify-win-artifacts.js` passes
- installer and app bootstrap succeed

### Regression checks after packaging

- bundled backend executable is present
- PDF loading works
- analysis can start
- Workbench and docked chat open without obvious runtime regressions

## Assumptions

- The current development machine is `macOS ARM`, so only the macOS local build path is directly executable there.
- Windows packaging uses CI or a real Windows machine, not macOS emulation.
- Release-quality packaging uses Python `3.12` even if local development uses a different Python version.
- Unsigned artifacts are acceptable for internal verification, but production distribution may still show OS trust warnings.
