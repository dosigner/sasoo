# macOS Release Pipeline

> Updated 2026-08-06: reflects v0.8.0 reality (macOS ZIP+DMG distribution).

This project distributes macOS builds as unsigned Apple Silicon ZIP and DMG archives.
Apple code signing and notarization are intentionally out of scope for the current release flow.

## Release target

- Platform: macOS on Apple Silicon
- Artifacts: `dist/*-mac.zip`, `dist/*.dmg`
- Metadata: `dist/latest-mac.yml`
- Differential update data: `dist/*.blockmap`

## Local commands

- `pnpm clean:mac`: remove mac build outputs before rebuilding
- `pnpm build:mac`: clean and build the unsigned macOS ZIP and DMG artifacts
- `pnpm build:mac:release`: run `build:mac` and verify the generated ZIP·DMG release artifacts
- `pnpm verify:mac-artifact`: verify `latest-mac.yml`, `unzip -t`, and ZIP extraction into a single `.app`

## Verification scope

`pnpm verify:mac-artifact` checks the ZIP shape, which is the electron-updater target:

- exactly one `*-mac.zip` exists in `dist/`
- `latest-mac.yml` points to that ZIP and matches its size and sha512 (and validates the DMG entry's size/sha512 too, if `latest-mac.yml` lists one)
- `unzip -t` succeeds
- `ditto -x -k` extracts exactly one `.app` bundle

It does not require `codesign`, `spctl`, or notarization, and it does not structurally validate the DMG (no mount/extraction check on the DMG itself).

## GitHub Actions behavior

The workflow at `.github/workflows/release.yml` runs on tag pushes that match `v*` and on manual dispatch.

- No Apple Developer secrets are required.
- The macOS build runs on `macos-14`.
- Release assets include the ZIP archive, the DMG archive, `latest-mac.yml`, and any generated `.blockmap` files.

## User install flow

ZIP:

1. Download the macOS ZIP asset from GitHub Releases.
2. Extract the ZIP with Archive Utility or Finder.
3. Move `Sasoo.app` into `/Applications`.
4. If macOS shows "`Sasoo` is damaged and can't be opened", run:

   ```bash
   xattr -dr com.apple.quarantine /Applications/Sasoo.app
   ```

5. If launch is still blocked, use right-click `Open` on `Sasoo.app`.

DMG:

1. Download the macOS DMG asset from GitHub Releases.
2. Open the DMG and drag `Sasoo.app` into the `/Applications` shortcut shown in the window.
3. The same unsigned-build Gatekeeper workaround applies: if macOS shows "`Sasoo` is damaged and can't be opened", run:

   ```bash
   xattr -dr com.apple.quarantine /Applications/Sasoo.app
   ```

4. If launch is still blocked, use right-click `Open` on `Sasoo.app`.

## Release note reminder

Every macOS release note should include the install workaround below because unsigned ZIP and DMG builds can trigger Gatekeeper quarantine warnings:

```bash
xattr -dr com.apple.quarantine /Applications/Sasoo.app
```
