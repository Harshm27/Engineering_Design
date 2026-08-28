# Running Drawing to Solid in Docker

Everything is pinned, so the container gives the same result on any machine.
Nothing here calls an AI model.

## One command

**Windows:** double-click `run.bat`
**macOS / Linux:** `./run.sh`

Either builds the image and runs the self-test, leaving the results in `out/`.
The first build downloads roughly 1 GB (Python, then OpenCASCADE) and takes a
few minutes. Later runs start instantly.

If you would rather type it yourself:

    docker build -t drawing-to-solid:1.0 .
    docker run --rm -v "$PWD/out:/out" drawing-to-solid:1.0

or with compose:

    docker compose run --rm drawing-to-solid

## What the self-test proves

It demonstrates the claims rather than asserting them, in five parts: the
reference part builds and matches its expected volume; five specs each carrying
a different deliberately misread dimension are all refused, with the offending
number named; the correct model is projected back onto the source drawing and
matches every visible edge; a model that is internally consistent but wrong
against the drawing is caught by that reprojection, which is the failure the
builder cannot see; and an interactive viewer is produced.

Exit code 0 means all twelve checks held. Open `out/spool_viewer.html` in a
browser afterwards.

## Running it as a service instead

Nobody has to install anything if one machine runs it and everyone else opens a
browser:

    docker compose up -d          # http://localhost:8000

or without compose:

    docker run -d -p 8000:8000 -v "$PWD/out:/out" drawing-to-solid:1.0 serve

The page takes a spec (the reference part is preloaded and editable), optionally
a drawing to check against, and returns the closure checks, the verification
residual table, downloadable STEP and STL, and the interactive viewer embedded
in the page. `/selftest` runs the twelve checks and returns the report as text;
`/healthz` is there for a load balancer.

Set `AUTH_USER` and `AUTH_PASS` and every route requires an HTTP basic login;
leave them unset and it runs open, printing a warning. `/healthz` stays open so
load balancers can probe it.

    docker run -d -p 8000:8000 -e AUTH_USER=ujjwal -e AUTH_PASS='...' \
        drawing-to-solid:1.0 serve

To host it where a colleague can reach it, see **DEPLOY.md**. **This is a
prototype: one shared password, no rate limiting, no sandboxing of uploads.**
It executes no uploaded code, only parses JSON specs, but anyone with the
password can make it burn CPU. Fine for named colleagues over HTTPS; not
hardened for the open internet.

## Doing your own runs

The entrypoint takes subcommands:

    docker run --rm -v "$PWD/out:/out" drawing-to-solid:1.0 \
        build examples/spool_shaft.json

    docker run --rm -v "$PWD/out:/out" drawing-to-solid:1.0 \
        verify /out/spool_shaft_report.json examples/spool_shaft_drawing.png \
        --box 280,140,900,440

    docker run --rm -v "$PWD/out:/out" drawing-to-solid:1.0 \
        viewer examples/spool_shaft.json /out/spool_shaft_report.json \
        /out/spool_shaft.brep -o /out/viewer.html

    docker run --rm -it -v "$PWD/out:/out" drawing-to-solid:1.0 shell

To try your own spec, mount the folder holding it:

    docker run --rm -v "$PWD/out:/out" -v "$PWD/myparts:/in" \
        drawing-to-solid:1.0 build /in/my_part.json

## Apple Silicon

Both routes work natively on an M-series Mac, no emulation and no `--platform`
flag. `cadquery-ocp` and `vtk` publish `macosx_11_0_arm64` wheels for pip, and
`manylinux_2_31_aarch64` wheels for the container, so `docker build` on an
arm64 Mac produces an arm64 image that installs arm64 wheels. `python:3.11-slim`
is multi-arch, and its glibc 2.36 clears the wheels' 2.31 floor.

## What was and was not tested before shipping

Verified: the pinned requirements install cleanly into a bare Python 3.11
environment and the full self-test passes there, 12 of 12. The web front end was
exercised end to end over HTTP: a valid spec returns the build, a PASS
verification with all 15 residuals, working downloads and the embedded viewer; a
deliberately misread spec returns the refusal rather than a server error;
malformed JSON returns a readable message; and directory traversal on the file
route is refused with a 404. The system library list in the Dockerfile was
derived by running `ldd` against the installed OpenCASCADE shared objects rather
than guessed. Wheel availability per platform was read from PyPI, not assumed.

Not verified: the image build itself, and therefore `serve` inside the
container (the same app was tested outside it). The environment this was assembled in
blocks access to container registries, so no base image could be pulled and no
build could be run. The Dockerfile is straightforward and its COPY sources,
shell syntax and compose file were all checked, but the first real build happens
on your machine. If it fails it will almost certainly be a missing system
library, which shows up as an ImportError on `OCP`; add the package to the
`apt-get install` line and rebuild.

## If you would rather skip Docker

The plain route is verified end to end and takes about ninety seconds:

    pip install -r requirements.txt
    python selftest.py

`cadquery` installs from wheels on Windows, macOS and Linux with no compiler
needed. Docker buys reproducibility and keeps your Python untouched; it does not
fix an install problem that, on the evidence so far, does not occur.
