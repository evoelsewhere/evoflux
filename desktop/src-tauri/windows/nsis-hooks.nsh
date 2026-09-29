; Keep the progress UI compact and prevent the generated file list from being
; exposed through a "Show details" toggle during install or uninstall.
ShowInstDetails nevershow
ShowUninstDetails nevershow

; The installer only stops EvoFlux.exe itself. Two other processes can hold
; files it has to replace:
; - the WebBridge native host, which Chrome starts from a hard link to
;   EvoFlux.exe — while one runs, EvoFlux.exe cannot be rewritten;
; - the embedded tailnet helper under sidecar\tailnet.
; Both names belong to EvoFlux alone, so stopping them by name is safe.
!macro EVOFLUX_STOP_HELPERS
  nsis_tauri_utils::KillProcessCurrentUser "evoflux-webbridge-host.exe"
  Pop $R0
  nsis_tauri_utils::KillProcessCurrentUser "evoflux-tailnet.exe"
  Pop $R0
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro EVOFLUX_STOP_HELPERS
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro EVOFLUX_STOP_HELPERS
!macroend
