#!/usr/bin/env bash
# Drawing to Solid, one command on macOS/Linux. Needs Docker.
set -e
cd "$(dirname "$0")"
mkdir -p out
echo "Building the image (first run downloads ~1 GB and takes a few minutes)..."
docker build -t drawing-to-solid:1.0 .
echo
docker run --rm -v "$PWD/out:/out" drawing-to-solid:1.0 "$@"
echo
echo "Results are in: $PWD/out"
