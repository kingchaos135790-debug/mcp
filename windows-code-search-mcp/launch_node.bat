@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_distributed.ps1" -Role node -LogPrefix "%~n0" %*
exit /b %ERRORLEVEL%
