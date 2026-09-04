@echo off
REM ===========================================================================
REM  Cube FX Simulator - launcher for the desktop shortcut
REM ===========================================================================
REM  Runs from its own folder rather than wherever the shortcut was invoked
REM  from, builds the native DLL if it is missing, and holds the window open on
REM  failure. A dev tool that dies silently is worse than one that never
REM  started, so this deliberately keeps a console: if the DLL will not build or
REM  a package is missing, the reason stays on screen.
REM ===========================================================================
cd /d "%~dp0"

if not exist "cubefx.dll" (
  echo cubefx.dll not found - building it once, this takes a minute...
  python build.py --native-only
  if errorlevel 1 goto failed
  if not exist "cubefx.dll" goto failed
  echo.
)

python -m native.app
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo ---------------------------------------------------------------
echo  The simulator did not start. The error is above.
echo.
echo  Common causes:
echo    - the native DLL will not build: needs MSVC Build Tools and the
echo      clang inside emsdk. Run  python build.py --native-only
echo    - missing packages:  pip install numpy pyaudiowpatch dearpygui
echo ---------------------------------------------------------------
echo.
pause
exit /b 1
