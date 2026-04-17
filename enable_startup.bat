@echo off
setlocal

set "APP_EXE=%~dp0dist\CSUAutoLogin.exe"
if not exist "%APP_EXE%" set "APP_EXE=%~dp0CSUAutoLogin.exe"

if not exist "%APP_EXE%" (
  echo 未找到 CSUAutoLogin.exe，请先执行 build.bat 进行构建。
  pause
  exit /b 1
)

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\CSUAutoLogin.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$shortcut = $ws.CreateShortcut('%SHORTCUT_PATH%'); " ^
  "$shortcut.TargetPath = '%APP_EXE%'; " ^
  "$shortcut.WorkingDirectory = '%~dp0'; " ^
  "$shortcut.WindowStyle = 7; " ^
  "$shortcut.Save()"

if exist "%SHORTCUT_PATH%" (
  echo 已创建开机自启快捷方式：%SHORTCUT_PATH%
) else (
  echo 创建开机自启失败。
  exit /b 1
)

endlocal
