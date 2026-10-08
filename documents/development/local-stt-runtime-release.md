# Local Whisper asset release procedure

The standard EvoFlux installer does not contain the speech engine or Whisper weights. Local Whisper becomes downloadable only after an app release pins verified runtime and model assets.

## Build and verify assets

1. Open **Actions → Local STT runtime** on a trusted branch.
2. Enter a new runtime version (for example, `0.1.0`) and leave **Publish verified assets** off for a verification run.
3. Confirm the runtime builds and the offline model-load check succeeds on Windows x64, macOS Intel, macOS Apple Silicon, and Linux x64.
4. Dispatch the workflow again with the same version and **Publish verified assets** on. This creates or updates the non-latest `local-stt-runtime-<version>` release with each platform runtime and the shared multilingual model.
5. Copy the generated JSON manifest from the workflow summary into `PINNED_RUNTIME_ASSETS` and `PINNED_MODEL_ASSET` in `app/services/local_stt_runtime/manifest.py`. Keep the generated HTTPS URLs, byte sizes, and SHA-256 values unchanged.
6. Review and release an EvoFlux app build containing those pins. The app's Settings screen can then show the download size and offer **Download to enable** on supported platforms.

This workflow is manually triggered only; pull requests do not build or publish speech assets. Publishing requires explicitly selecting the publish input. The model is about 486 MB upstream; use the generated manifest as the authority for the actual download and installed sizes. Do not report a platform as available until its packaged app and local transcription have been checked on that platform.

## Updating assets

Use a new runtime version for every published asset set. Keep the model revision pinned unless a separately reviewed model update is intended. After publication, update the app manifest with the generated checksums and ship a new app build so the embedded pins match the release assets. Existing installed versions remain usable until the user chooses to update or remove them.
