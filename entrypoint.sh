#!/bin/sh
# Drawing to Solid container entrypoint.
#
#   (no argument)                       run the self-test
#   build  <spec.json>                  build a part, output to /out
#   verify <report.json> <drawing.png> --box L,T,R,B
#   viewer <spec.json> <report.json> <part.brep>
#   serve  [port]                       web front end (default port 8000)
#   shell                               interactive shell
#   <anything else>                     run it verbatim
set -e
case "$1" in
  selftest|"")
    exec python selftest.py
    ;;
  build)
    shift
    exec python -m drawing2solid.builder "$@" -o "$OUTDIR"
    ;;
  verify)
    shift
    exec python -m drawing2solid.verify "$@"
    ;;
  viewer)
    shift
    exec python -m drawing2solid.viewer "$@"
    ;;
  serve)
    shift
    # Cloud Run and similar platforms inject $PORT; an explicit argument wins.
    PORT="${1:-${PORT:-8000}}"
    echo "Drawing to Solid on http://0.0.0.0:${PORT}"
    exec python -m uvicorn webapp:app --host 0.0.0.0 --port "$PORT"
    ;;
  shell)
    exec /bin/sh
    ;;
  *)
    exec "$@"
    ;;
esac
