# Local Whisper asset release procedure

The standard EvoFlux installer does not contain the speech engine or Whisper weights. Local Whisper becomes downloadable only after an app release pins verified runtime and model assets.

## Test a local build without publishing assets

Build the runtime archive on the same OS and architecture you are testing, and build the shared model archive from any supported host. The model comes from the pinned Hugging Face revision; no GitHub release or fabricated checksum is needed for this test.

On Windows x64, from the repository root:

```powershell
New-Item -ItemType Directory -Force .local-stt-assets | Out-Null
$assetDir = (Resolve-Path .local-stt-assets).Path
$baseUrl = [System.Uri]::new($assetDir).AbsoluteUri.TrimEnd('/')
uv run --no-project --python 3.12 python scripts/build_local_stt_runtime.py --asset runtime --version local-test --out $assetDir --base-url $baseUrl
uv run --no-project --python 3.12 python scripts/build_local_stt_runtime.py --asset model --out $assetDir --base-url $baseUrl

$runtime = Get-Content (Join-Path $assetDir 'runtime-win32-x64.json') -Raw | ConvertFrom-Json
$model = Get-Content (Join-Path $assetDir 'model-all.json') -Raw | ConvertFrom-Json
$manifest = @{ runtime_assets = @{ 'win32-x64' = $runtime }; model_asset = $model }
$manifestPath = Join-Path $assetDir 'local-manifest.json'
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
$env:EVOFLUX_LOCAL_STT_MANIFEST = $manifestPath
```

Start or restart the EvoFlux sidecar/desktop app from that same PowerShell session, then use **Settings → Voice input → Download to enable**. The local manifest uses the real archive byte sizes and SHA-256 values produced by the builder; `file://` URLs are accepted only through this development override. Keep `.local-stt-assets` out of commits. On macOS, run the runtime build on the Mac being tested and use `darwin-x64` or `darwin-arm64` in the manifest's `runtime_assets` key.

## Build and verify assets

1. Open a pull request with runtime packaging changes. The workflow builds and verifies Windows x64, macOS Intel, macOS Apple Silicon, and Linux x64 on the PR without publishing a release.
2. Review the matrix and offline model-load results before deciding whether to merge. PR workflow artifacts are temporary and are not used by app downloads.
3. After the workflow is on the default branch, manually dispatch it from a trusted branch with **Publish verified assets** off for a separate verification run, if needed. GitHub requires a `workflow_dispatch` workflow on the default branch to enable manual dispatch.
4. Dispatch the workflow with the same version and **Publish verified assets** on. This creates or updates the non-latest `local-stt-runtime-<version>` release with each platform runtime and the shared multilingual model.
5. Copy the generated JSON manifest from the workflow summary into `PINNED_RUNTIME_ASSETS` and `PINNED_MODEL_ASSET` in `app/services/local_stt_runtime/manifest.py`. Keep the generated HTTPS URLs, byte sizes, and SHA-256 values unchanged.
6. Review and release an EvoFlux app build containing those pins. The app's Settings screen can then show the download size and offer **Download to enable** on supported platforms.

Pull request runs only build and verify; the publish job requires a manual dispatch and an explicit publish input. The model is about 486 MB upstream; use the generated manifest as the authority for the actual download and installed sizes. Do not report a platform as available until its packaged app and local transcription have been checked on that platform.

## Updating assets

Use a new runtime version for every published asset set. Keep the model revision pinned unless a separately reviewed model update is intended. After publication, update the app manifest with the generated checksums and ship a new app build so the embedded pins match the release assets. Existing installed versions remain usable until the user chooses to update or remove them.
