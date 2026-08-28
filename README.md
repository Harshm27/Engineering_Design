# Drawing to Solid

A prototype that turns a 2D engineering drawing into a **dimensionally correct
3D model**, with automatic proof that the model matches the drawing.

Two real parts have been through it. Nothing in this repository calls an AI
model: the reading of a drawing happens once, by a person or a model, and its
whole output is a `spec.json`. Everything after that is deterministic code.

---

## Try it without installing anything

**GitHub Codespaces** (free on a personal account, no card needed). Press
**Code → Codespaces → Create codespace on main**. The container installs
everything on first boot, then:

```bash
python selftest.py                                    # the twelve checks
python -m uvicorn webapp:app --host 0.0.0.0 --port 8000   # the web front end
```

VS Code offers to forward port 8000; open it and you get the whole pipeline in a
browser. Set `AUTH_USER` and `AUTH_PASS` first if you make that port public.

## Or locally

Needs Python 3.11 or newer. Verified on Linux and on macOS, Intel and Apple
Silicon alike, since every dependency publishes `arm64` wheels.

```bash
pip install -r requirements.txt
python selftest.py
```

Docker works too, see `DOCKER.md`. Hosting options, including a one-command
Google Cloud Run deploy that stays inside the free allowance, are in `DEPLOY.md`.

---

## What the self-test proves

It demonstrates the claims rather than asserting them, and exits non-zero if any
fail:

1. the reference part builds from its spec and matches its expected volume
2. five specs, each carrying a different deliberately misread dimension, are all
   **refused**, with the offending number named
3. the correct model, projected back onto the source drawing, matches every
   visible silhouette edge
4. a model that is internally consistent but **wrong** against the drawing is
   caught by that reprojection, which is the failure the builder cannot see
5. an interactive viewer is produced

## How it works

```
read the drawing   ->   spec.json   ->   build    ->  STEP / STL
(person or model)       (numbers)        verify   ->  pass / fail
                                         viewer   ->  interactive HTML
```

Reading a drawing needs judgment, so that step is done by a person or a model and
produces only a readable list of numbers plus the constraints they must satisfy.
The **builder** solves the tangencies a drawing only implies, and refuses to
build when the dimension chain does not close, which is what a misreading looks
like arithmetically. The **verifier** then reprojects the finished solid onto the
drawing image, because a spec can be self-consistent and still wrong.

Those two checks are what make a model-in-the-loop trustworthy, and they are the
part worth attacking if you want to find where this breaks.

## The three commands

```bash
python -m drawing2solid.builder examples/spool_shaft.json -o out
python -m drawing2solid.verify  out/spool_shaft_report.json \
        examples/spool_shaft_drawing.png --box 280,140,900,440
python -m drawing2solid.viewer  examples/spool_shaft.json \
        out/spool_shaft_report.json out/spool_shaft.brep -o out/viewer.html
```

`--box` is the pixel rectangle around the drawing's main side view. Nothing else
about the image is trusted.

## What it does not do

Automated coverage is **turned parts**: shafts, spools, bushes, pins, plus axial
holes, bolt-hole patterns on a pitch circle and DIN 509 undercuts. The bracket in
`viewers/` is sheet metal, outside that range, and was modelled directly in
CadQuery; its source is `parts/bracket.py`.

Native `.dwg` and `.rvt` cannot be read, so drawings need exporting to DXF or
supplying as PDF or image. A DXF removes the interpretation step altogether and
is strictly better than a raster. Threads are modelled at tapping-drill diameter
and reported as such. Where a drawing omits the material, any mass figure states
the assumption.

## Layout

| Path | What it is |
|---|---|
| `drawing2solid/` | builder, verifier, viewer generator |
| `selftest.py` | the demonstration described above |
| `webapp.py` | web front end, `serve` in the container |
| `examples/` | the reference spec and its source drawing |
| `SCHEMA.md` | the spec format |
| `SKILL.md` | the drawing-reading workflow, for the AI-assisted step |
| `DEPLOY.md` | five ways to host it, with costs |
| `DOCKER.md` | container details |
| `viewers/`, `drawings/`, `parts/` | prebuilt output for the two worked examples |
| `brief.pdf` | two-page summary |

Prototype. One shared password when served, no rate limiting, no sandboxing of
uploads. Fine for named colleagues over HTTPS, not hardened for the open
internet.
