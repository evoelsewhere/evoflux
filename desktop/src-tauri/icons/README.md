# Icons

`icon.png` is the 1024×1024 source. The other PNG sizes (`32x32.png`,
`128x128.png`, `128x128@2x.png`) and the platform-specific bundles
(`icon.icns` for macOS, `icon.ico` for Windows) are generated from it by:

```sh
cd desktop/src-tauri && cargo tauri icon icons/icon.png
```

That command writes `icon.icns` and `icon.ico` alongside the existing PNGs.
The release CI removes stale generated icon outputs, regenerates them from
`icon.png`, then packages the desktop app so prod bundles do not reuse old
platform icon files.
