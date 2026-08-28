@echo off
REM Drawing to Solid, one-click on Windows. Needs Docker Desktop running.
setlocal
if not exist "%~dp0out" mkdir "%~dp0out"
echo Building the image (first run downloads ~1 GB and takes a few minutes)...
docker build -t drawing-to-solid:1.0 "%~dp0" || goto :err
echo.
echo Running the self-test...
docker run --rm -v "%~dp0out:/out" drawing-to-solid:1.0 %*
echo.
echo Results are in: %~dp0out
pause
exit /b 0
:err
echo.
echo Build failed. Is Docker Desktop installed and running?
pause
exit /b 1
