!macro customInit
  ; Kill running Sasoo and Python backend processes before installation
  nsExec::ExecToStack 'taskkill /F /IM "Sasoo.exe" /T'
  nsExec::ExecToStack 'taskkill /F /IM "sasoo-backend.exe" /T'
  Sleep 2000
!macroend
