# macOS Release Pipeline

This project distributes macOS builds as a single unsigned Apple Silicon ZIP archive.
DMG packaging, Apple code signing, and notarization are intentionally out of scope for the current release flow.

## Release target

- Platform: macOS on Apple Silicon
- Artifact: `dist/*-mac.zip`
- Metadata: `dist/latest-mac.yml`
- Differential update data: `dist/*.blockmap`

## Local commands

- `pnpm clean:mac`: remove mac build outputs before rebuilding
- `pnpm build:mac`: clean and build the unsigned macOS ZIP artifacts
- `pnpm build:mac:release`: run `build:mac` and verify the generated ZIP release artifacts
- `pnpm verify:mac-artifact`: verify `latest-mac.yml`, `unzip -t`, and ZIP extraction into a single `.app`

## Verification scope

`pnpm verify:mac-artifact` checks the release shape that we actually ship:

- exactly one `*-mac.zip` exists in `dist/`
- `latest-mac.yml` points to that ZIP and matches its size and sha512
- `unzip -t` succeeds
- `ditto -x -k` extracts exactly one `.app` bundle

It does not require `codesign`, `spctl`, notarization, or DMG validation.

## GitHub Actions behavior

The workflow at `.github/workflows/release.yml` runs on tag pushes that match `v*` and on manual dispatch.

- No Apple Developer secrets are required.
- The macOS build runs on `macos-14`.
- Release assets include only the ZIP archive, `latest-mac.yml`, and any generated `.blockmap` files.

## User install flow

1. Download the macOS ZIP asset from GitHub Releases.
2. Extract the ZIP with Archive Utility or Finder.
3. Move `Sasoo.app` into `/Applications`.
4. If macOS shows "`Sasoo` is damaged and can't be opened", run:

   ```bash
   xattr -dr com.apple.quarantine /Applications/Sasoo.app
   ```

5. If launch is still blocked, use right-click `Open` on `Sasoo.app`.

## Release note reminder

Every macOS release note should include the install workaround below because unsigned ZIP builds can trigger Gatekeeper quarantine warnings:

```bash
xattr -dr com.apple.quarantine /Applications/Sasoo.app
```
