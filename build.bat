@echo off
setlocal

cd /d "%~dp0"
taskkill /F /IM CSUAutoLogin.exe >nul 2>nul
if exist "dist\CSUAutoLogin.exe" del /F /Q "dist\CSUAutoLogin.exe"
if exist "build" rmdir /S /Q "build"
if exist "CSUAutoLogin.spec" del /F /Q "CSUAutoLogin.spec"
uv run --with requests --with pyinstaller pyinstaller --noconfirm --clean --onefile --windowed --name CSUAutoLogin main.py

if errorlevel 1 (
  echo 构建失败。
  exit /b 1
)

copy /Y config.json dist\config.json >nul
echo 构建完成，产物位于 dist\CSUAutoLogin.exe

endlocal