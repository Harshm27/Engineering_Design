#!/usr/bin/env bash
#
# Drawing to Solid: share it with a colleague, one command.
#
#   ./share.sh
#
# Makes a virtual environment, installs the pinned dependencies, generates a
# password, starts the app, opens a Cloudflare quick tunnel and prints the
# public address plus a message you can paste to whoever is testing.
#
# Leave the terminal open. Ctrl+C stops sharing immediately.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# The app root is wherever requirements.txt lives: beside this script, or one
# level down if the pack was unzipped into a subfolder.
HERE=""
for c in "$SCRIPT_DIR" "$SCRIPT_DIR/drawing_to_solid"; do
  [ -f "$c/requirements.txt" ] && { HERE="$c"; break; }
done
if [ -z "$HERE" ]; then
  for c in "$SCRIPT_DIR"/*/; do
    [ -f "$c/requirements.txt" ] && { HERE="${c%/}"; break; }
  done
fi
if [ -z "$HERE" ]; then
  echo "FAILED: could not find the application files (no requirements.txt beside"
  echo "  this script or one level below). Unzip the pack here and try again."
  exit 1
fi
cd "$HERE"

PORT="${PORT:-8000}"
# Keep the virtual environment and downloads out of any synced folder.
WORK="${XDG_CACHE_HOME:-$HOME/.cache}/drawing-to-solid"
mkdir -p "$WORK"
VENV="$WORK/venv"
PY="$VENV/bin/python"
CF="$WORK/cloudflared"
APP_PID=""; CF_PID=""

say()  { printf '\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m    %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    %s\033[0m\n' "$1"; }

cleanup() {
  echo
  say "Shutting down"
  [ -n "$CF_PID" ]  && kill "$CF_PID"  2>/dev/null
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
  ok "The address no longer works. Run this again to share afresh."
}
trap cleanup EXIT INT TERM

command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
say "Checking Python"; ok "$(python3 -V)"; ok "App files:   $HERE"; ok "Working dir: $WORK"

[ -x "$PY" ] || { say "Creating the virtual environment (first run only)"; python3 -m venv "$VENV"; }
say "Installing dependencies (first run takes a couple of minutes)"
"$PY" -m pip install --quiet --upgrade pip
PIPLOG="$WORK/pip-install.log"
if ! "$PY" -m pip install -r requirements.txt > "$PIPLOG" 2>&1; then
  warn "pip could not install everything. Last lines:"; tail -30 "$PIPLOG" | while read -r l; do warn "$l"; done
  warn "Full log: $PIPLOG"; exit 1
fi
probe() { "$PY" - <<'PROBE'
import importlib
bad = []
for m in ["numpy","PIL","fastapi","uvicorn","multipart","OCP","cadquery"]:
    try: importlib.import_module(m)
    except BaseException as e: bad.append(f"{m}: {type(e).__name__}: {e}")
if bad:
    print("The dependencies installed, but some will not import:")
    for b in bad: print("  " + b)
    raise SystemExit(1)
PROBE
}
# Freshly installed large DLLs occasionally fail to load on the first attempt.
OUT=""
for attempt in 1 2 3; do
  OUT="$(probe 2>&1)" && break
  [ "$attempt" -lt 3 ] && { warn "Import attempt $attempt failed, retrying in 5s"; sleep 5; }
done
if [ -n "$OUT" ]; then echo "$OUT" | while read -r l; do warn "$l"; done; exit 1; fi
ok "Dependencies ready"

USER_NAME="${AUTH_USER:-ujjwal}"
PASS="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')"
ok "Login generated: $USER_NAME / $PASS"

say "Starting the app on http://localhost:$PORT"
mkdir -p "$WORK/out"
AUTH_USER="$USER_NAME" AUTH_PASS="$PASS" OUTDIR="$WORK/out" \
  "$PY" -m uvicorn webapp:app --host 127.0.0.1 --port "$PORT" > /tmp/d2s-app.log 2>&1 &
APP_PID=$!
for _ in $(seq 1 40); do
  sleep 1
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT/healthz" 2>/dev/null && break
done
curl -fsS -o /dev/null "http://127.0.0.1:$PORT/healthz" 2>/dev/null || {
  warn "The app did not come up. Its log:"; tail -25 /tmp/d2s-app.log | while read -r l; do warn "$l"; done; exit 1; }
ok "App is up and answering"

if [ ! -x "$CF" ]; then
  say "Downloading cloudflared (first run only)"
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)  A=cloudflared-darwin-arm64.tgz ;;
    Darwin-x86_64) A=cloudflared-darwin-amd64.tgz ;;
    Linux-x86_64)  A=cloudflared-linux-amd64 ;;
    Linux-aarch64) A=cloudflared-linux-arm64 ;;
    *) echo "unsupported platform $(uname -s)-$(uname -m)"; exit 1 ;;
  esac
  U="https://github.com/cloudflare/cloudflared/releases/latest/download/$A"
  if [ "${A##*.}" = "tgz" ]; then
    curl -fsSL "$U" -o "$WORK/cf.tgz" && tar -xzf "$WORK/cf.tgz" -C "$WORK" && chmod +x "$CF"
  else
    curl -fsSL "$U" -o "$CF"
  fi
  chmod +x "$CF"; ok "Downloaded"
fi

say "Opening the tunnel"
: > /tmp/d2s-tunnel.log
"$CF" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" > /tmp/d2s-tunnel.log 2>&1 &
CF_PID=$!
URL=""
for _ in $(seq 1 60); do
  sleep 1
  URL="$(grep -oE 'https://[-a-z0-9]+\.trycloudflare\.com' /tmp/d2s-tunnel.log | head -1)"
  [ -n "$URL" ] && break
done
[ -n "$URL" ] || {
  warn "No tunnel address appeared. The tunnel log:"
  tail -25 /tmp/d2s-tunnel.log | while read -r l; do warn "$l"; done
  warn ""
  warn "If that mentions a refused or timed-out connection, your network is"
  warn "blocking Cloudflare. The app is still running at http://localhost:$PORT,"
  warn "and DEPLOY.md lists other hosting routes."
  exit 1; }

echo
printf '\033[90m%s\033[0m\n' "=================================================================="
printf '\033[32m  Live. Paste the block below to whoever is testing.\033[0m\n'
printf '\033[90m%s\033[0m\n' "=================================================================="
cat <<TXT

  Drawing to Solid, a prototype that turns a 2D engineering
  drawing into a verified 3D model.

    $URL
    username: $USER_NAME
    password: $PASS

  The reference part is preloaded, so pressing Build and verify shows
  the whole thing working. Try changing a dimension in the spec: if your
  edit contradicts another number, it refuses to build and tells you
  which one. $URL/selftest runs the twelve
  checks behind that claim.

TXT
printf '\033[90m%s\033[0m\n' "=================================================================="
printf '\033[33m  This terminal must stay open. Ctrl+C stops sharing.\033[0m\n'
printf '\033[90m%s\033[0m\n' "=================================================================="

wait "$CF_PID"
