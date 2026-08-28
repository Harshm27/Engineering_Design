<#
    Drawing to Solid: share it with a colleague, one command.

    Right-click this file and choose "Run with PowerShell", or from a terminal:

        powershell -ExecutionPolicy Bypass -File share.ps1

    What it does, in order:
      1. finds the application files (beside this script, or in a subfolder)
      2. makes a Python virtual environment under %LOCALAPPDATA%, deliberately
         outside OneDrive, and installs the pinned dependencies (first run only,
         a couple of minutes)
      3. generates a random password
      4. starts the web app on localhost with that password
      5. downloads cloudflared.exe if it is not already there
      6. opens a Cloudflare quick tunnel and prints the public HTTPS address
      7. prints a message you can paste straight to whoever is testing

    Leave the window open. Closing it, or pressing Ctrl+C, stops both the tunnel
    and the app, and the address stops working immediately.

    No Docker needed. Requires Python 3.11 or newer on PATH.
#>

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# The app root is wherever requirements.txt lives: beside this script, or one
# level down if the pack was unzipped into a subfolder.
$here = $null
foreach ($c in @($scriptDir, (Join-Path $scriptDir 'drawing_to_solid'))) {
    if (Test-Path (Join-Path $c 'requirements.txt')) { $here = $c; break }
}
if (-not $here) {
    $found = Get-ChildItem -Path $scriptDir -Directory -ErrorAction SilentlyContinue |
             Where-Object { Test-Path (Join-Path $_.FullName 'requirements.txt') } |
             Select-Object -First 1
    if ($found) { $here = $found.FullName }
}
if (-not $here) {
    Write-Host ''
    Write-Host "FAILED: could not find the application files." -ForegroundColor Red
    Write-Host "  Looked beside this script and one level below, for requirements.txt." -ForegroundColor Yellow
    Write-Host "  Unzip drawing_to_solid_testpack.zip here, so that a folder named" -ForegroundColor Yellow
    Write-Host "  drawing_to_solid sits next to this script, then run it again." -ForegroundColor Yellow
    Write-Host ''
    Read-Host 'Press Enter to close'
    exit 1
}
Set-Location $here

# Keep the virtual environment, cloudflared and the outputs OUT of OneDrive.
# A venv is ~500 MB of small files; syncing it is slow and can lock files
# mid-install.
$work      = Join-Path $env:LOCALAPPDATA 'drawing-to-solid'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$venv      = Join-Path $work 'venv'
$py        = Join-Path $venv 'Scripts\python.exe'
$cfExe     = Join-Path $work 'cloudflared.exe'
$cfUrl      = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
$port       = 8000
$appProc    = $null
$cfProc     = $null
$cfLog      = Join-Path $env:TEMP 'd2s-tunnel.log'
$appLog     = Join-Path $env:TEMP 'd2s-app.log'

function Say  ($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "    $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "    $m" -ForegroundColor Yellow }

function Cleanup {
    Write-Host ''
    Say 'Shutting down'
    foreach ($p in @($cfProc, $appProc)) {
        if ($p -and -not $p.HasExited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
    }
    Ok 'The address no longer works. Run this script again to share it afresh.'
}

try {
    # ---------------------------------------------------------------- python --
    Say 'Checking Python'
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) { $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue }
    if (-not $pyCmd) {
        throw "Python was not found on PATH. Install it from python.org or open an Anaconda Prompt and run this script from there."
    }
    Ok (& $pyCmd.Source -V 2>&1)
    Ok "App files:   $here"
    Ok "Working dir: $work  (kept out of OneDrive)"

    if (-not (Test-Path $py)) {
        Say 'Creating the virtual environment (first run only)'
        & $pyCmd.Source -m venv $venv
        if (-not (Test-Path $py)) { throw "Could not create a virtual environment at $venv" }
    }

    Say 'Installing dependencies (first run takes a couple of minutes)'
    $pipLog = Join-Path $work 'pip-install.log'
    & $py -m pip install --quiet --upgrade pip 2>&1 | Out-Null
    & $py -m pip install -r (Join-Path $here 'requirements.txt') 2>&1 |
        Tee-Object -FilePath $pipLog | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Warn 'pip could not install everything. The last lines of its output:'
        Get-Content $pipLog -Tail 30 | ForEach-Object { Warn $_ }
        Warn ''
        Warn "Full log: $pipLog"
        throw 'pip install failed.'
    }

    # Import each module separately so a failure names itself instead of hiding
    # behind a generic message.
    $probe = @'
import importlib
mods = ["numpy","PIL","fastapi","uvicorn","multipart","OCP","cadquery"]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except BaseException as e:
        bad.append(f"{m}: {type(e).__name__}: {e}")
if bad:
    print("IMPORT_FAILURES")
    for b in bad: print(b)
    raise SystemExit(1)
'@
    # A freshly installed set of large DLLs can fail to load on the very first
    # attempt on Windows, typically while the on-access virus scanner still has
    # them open. Retry a couple of times before believing it.
    $probeOut = $null
    foreach ($attempt in 1..3) {
        $probeOut = ($probe | & $py - 2>&1)
        if ($LASTEXITCODE -eq 0) { break }
        if ($attempt -lt 3) {
            Warn "Import attempt $attempt failed, retrying in 5s (this is usually a"
            Warn "freshly installed DLL still being scanned)"
            Start-Sleep -Seconds 5
        }
    }
    if ($LASTEXITCODE -ne 0) {
        Warn 'The dependencies installed, but some will not import:'
        $probeOut | ForEach-Object { if ($_ -ne 'IMPORT_FAILURES') { Warn $_ } }
        Warn ''
        if ($probeOut -match 'DLL load failed') {
            Warn 'A DLL failed to load. OpenCASCADE needs the Microsoft Visual C++'
            Warn 'Redistributable (x64), which is not installed by default:'
            Warn '  https://aka.ms/vs/17/release/vc_redist.x64.exe'
            Warn 'Install it, reboot if asked, then run this script again.'
        } else {
            Warn 'Run diagnose.ps1 for the full picture and send me the output.'
        }
        throw 'Dependencies will not import.'
    }
    Ok 'Dependencies ready'

    # ------------------------------------------------------------- password --
    $pass = & $py -c "import secrets; print(secrets.token_urlsafe(18))"
    $user = 'ujjwal'
    Ok "Login generated: $user / $pass"

    # -------------------------------------------------------------- the app --
    Say "Starting the app on http://localhost:$port"
    $env:AUTH_USER = $user
    $env:AUTH_PASS = $pass
    $env:OUTDIR    = Join-Path $work 'out'
    New-Item -ItemType Directory -Force -Path $env:OUTDIR | Out-Null

    $appProc = Start-Process -FilePath $py `
        -ArgumentList @('-m','uvicorn','webapp:app','--host','127.0.0.1','--port',"$port") `
        -WorkingDirectory $here -PassThru -NoNewWindow `
        -RedirectStandardOutput $appLog -RedirectStandardError "$appLog.err"

    $up = $false
    foreach ($i in 1..40) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:$port/healthz" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $up = $true; break }
        } catch { }
        if ($appProc.HasExited) { break }
    }
    if (-not $up) {
        Warn "The app did not come up. Its log:"
        if (Test-Path $appLog)       { Get-Content $appLog       -Tail 25 | ForEach-Object { Warn $_ } }
        if (Test-Path "$appLog.err") { Get-Content "$appLog.err" -Tail 25 | ForEach-Object { Warn $_ } }
        throw "Could not start the app."
    }
    Ok 'App is up and answering'

    # --------------------------------------------------------------- tunnel --
    if (-not (Test-Path $cfExe)) {
        Say 'Downloading cloudflared (about 55 MB, first run only)'
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $cfUrl -OutFile $cfExe -UseBasicParsing
        Ok 'Downloaded'
    }

    Say 'Opening the tunnel'
    if (Test-Path $cfLog) { Remove-Item $cfLog -Force }
    $cfProc = Start-Process -FilePath $cfExe `
        -ArgumentList @('tunnel','--no-autoupdate','--url',"http://127.0.0.1:$port") `
        -PassThru -NoNewWindow -RedirectStandardOutput $cfLog -RedirectStandardError "$cfLog.err"

    $publicUrl = $null
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 1
        foreach ($f in @($cfLog, "$cfLog.err")) {
            if (Test-Path $f) {
                $m = Select-String -Path $f -Pattern 'https://[-a-z0-9]+\.trycloudflare\.com' -AllMatches |
                     Select-Object -First 1
                if ($m) { $publicUrl = $m.Matches[0].Value; break }
            }
        }
        if ($publicUrl) { break }
        if ($cfProc.HasExited) { break }
    }

    if (-not $publicUrl) {
        Warn 'No tunnel address appeared. The tunnel log:'
        foreach ($f in @($cfLog, "$cfLog.err")) {
            if (Test-Path $f) { Get-Content $f -Tail 25 | ForEach-Object { Warn $_ } }
        }
        Warn ''
        Warn 'If this says the connection was refused or timed out, your network is'
        Warn 'probably blocking Cloudflare. The app is still running locally at'
        Warn "http://localhost:$port, and DEPLOY.md lists other hosting routes."
        throw 'Tunnel did not start.'
    }

    # ------------------------------------------------------------- hand over --
    Write-Host ''
    Write-Host ('=' * 66) -ForegroundColor DarkGray
    Write-Host '  Live. Paste the block below to whoever is testing.' -ForegroundColor Green
    Write-Host ('=' * 66) -ForegroundColor DarkGray
    Write-Host ''
    Write-Host "  Drawing to Solid, a prototype that turns a 2D engineering"
    Write-Host "  drawing into a verified 3D model."
    Write-Host ''
    Write-Host "    $publicUrl"
    Write-Host "    username: $user"
    Write-Host "    password: $pass"
    Write-Host ''
    Write-Host "  The reference part is preloaded, so pressing Build and verify"
    Write-Host "  shows the whole thing working. Try changing a dimension in the"
    Write-Host "  spec: if your edit contradicts another number, it refuses to"
    Write-Host "  build and tells you which one. $publicUrl/selftest runs the"
    Write-Host "  twelve checks behind that claim."
    Write-Host ''
    Write-Host ('=' * 66) -ForegroundColor DarkGray
    Write-Host '  This window must stay open. Ctrl+C stops sharing.' -ForegroundColor Yellow
    Write-Host ('=' * 66) -ForegroundColor DarkGray

    while (-not $cfProc.HasExited -and -not $appProc.HasExited) { Start-Sleep -Seconds 2 }
    Warn 'One of the processes stopped on its own.'
}
catch {
    Write-Host ''
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Cleanup
    Write-Host ''
    Read-Host 'Press Enter to close'
}
