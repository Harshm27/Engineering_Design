<#
    Drawing to Solid: work out what is wrong with the Python environment.

    Right-click and Run with PowerShell, or:
        powershell -ExecutionPolicy Bypass -File diagnose.ps1

    Prints one line per module, with the real error for anything that fails.
    Paste the whole output back.
#>
$ErrorActionPreference = 'Continue'
$work = Join-Path $env:LOCALAPPDATA 'drawing-to-solid'
$py   = Join-Path $work 'venv\Scripts\python.exe'

Write-Host "venv python: $py"
if (-not (Test-Path $py)) {
    Write-Host "No virtual environment found. Run share.ps1 first." -ForegroundColor Red
    Read-Host 'Press Enter to close'; exit 1
}

& $py -V
Write-Host ''
Write-Host '--- importing each module on its own ---' -ForegroundColor Cyan

$probe = @'
import importlib, traceback
mods = ["numpy","PIL","fastapi","uvicorn","multipart",
        "multimethod","casadi","numba","scipy","nlopt","ezdxf",
        "vtk","OCP","cadquery"]
for m in mods:
    try:
        importlib.import_module(m)
        print(f"OK    {m}")
    except BaseException as e:
        print(f"FAIL  {m}  ->  {type(e).__name__}: {e}")
'@
$probe | & $py -

Write-Host ''
Write-Host '--- installed versions ---' -ForegroundColor Cyan
& $py -m pip list 2>$null | Select-String -Pattern 'cadquery|ocp|casadi|numba|numpy|vtk|fastapi|uvicorn|multimethod|scipy|nlopt'

Write-Host ''
Write-Host '--- Visual C++ runtime (OCP needs it on Windows) ---' -ForegroundColor Cyan
$vc = Test-Path "$env:SystemRoot\System32\vcruntime140.dll"
$vc1 = Test-Path "$env:SystemRoot\System32\vcruntime140_1.dll"
Write-Host "  vcruntime140.dll   : $vc"
Write-Host "  vcruntime140_1.dll : $vc1"
if (-not ($vc -and $vc1)) {
    Write-Host "  Missing. Install the Microsoft Visual C++ Redistributable (x64):" -ForegroundColor Yellow
    Write-Host "  https://aka.ms/vs/17/release/vc_redist.x64.exe" -ForegroundColor Yellow
}

Write-Host ''
Read-Host 'Copy everything above, then press Enter to close'
