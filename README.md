# Drawing to Solid

A prototype that turns a 2D engineering drawing into a **dimensionally correct
3D model**, with automatic proof that the model matches the drawing.

**Try it in the browser, nothing to install:**
https://harshm27.github.io/Engineering_Design/
runs the same profile solver on the real spool-shaft spec. Edit a
number and it rebuilds; contradict another number and it refuses, naming the
dimension that does not close.

## Run the full pipeline

Needs Python 3.11+. Works on Windows, macOS (including Apple Silicon) and Linux.

```bash
pip install -r requirements.txt
python selftest.py
```

`selftest.py` demonstrates the claims rather than asserting them: the reference
part builds and matches its expected volume; five deliberately misread specs are
refused with the offending number named; the correct model reprojects onto the
source drawing with every visible edge matching; a model that is internally
consistent but wrong against the drawing is caught by that reprojection; and an
interactive viewer is produced. Exit 0 means all twelve checks held.

## Upload your own drawings

The one AI step, reading a drawing into a spec, runs through the web app. It
calls the Claude API (needs an `ANTHROPIC_API_KEY` from console.anthropic.com;
a few pence per drawing) and hands the result to the same builder, so a misread
drawing is refused, re-read once, and refused again rather than silently wrong.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m uvicorn webapp:app --port 8000        # then open http://localhost:8000
```

Upload a drawing on the front page; dimensions, spec, STEP/STL and the 3D viewer
come back in the browser. Scope is turned parts, and the reading is single-shot
from the image, so a clean scan matters; a drawing it cannot read is declined
with a reason. The interactive route (a Claude chat using `SKILL.md`) remains
the most accurate reader, since it can examine the views one at a time.

## The three commands

```bash
python -m drawing2solid.builder examples/spool_shaft.json -o out
python -m drawing2solid.verify  out/spool_shaft_report.json \
        examples/spool_shaft_drawing.png --box 280,140,900,440
python -m drawing2solid.viewer  examples/spool_shaft.json \
        out/spool_shaft_report.json out/spool_shaft.brep -o out/viewer.html
```

`--box` is the pixel rectangle around the drawing's main side view; nothing else
about the raster is trusted.

## How it works

```
read the drawing   ->   spec.json   ->   build    ->  STEP / STL
(person or model)       (numbers)        verify   ->  pass / fail
                                         viewer   ->  interactive HTML
```

Reading a drawing needs judgment, so that step is done by a person or a model
and produces only a readable list of numbers plus the constraints they must
satisfy (`SCHEMA.md`). Everything after the spec is deterministic code. The
builder solves the tangencies the drawing only implies and refuses when the
dimension chain does not close; the verifier reprojects the finished solid onto
the drawing image, because a spec can be self-consistent and still wrong.

## Scope, stated plainly

Automated coverage is turned parts: shafts, spools, bushes, pins, plus axial
holes, bolt-hole patterns and DIN 509 undercuts. The bracket in `viewers/` is
sheet metal, outside that range, modelled directly in CadQuery (`parts/bracket.py`).
Native .dwg/.rvt cannot be read; export to DXF or supply PDF/image. Threads are
modelled at tapping drill. `SKILL.md` is the drawing-reading workflow for the
AI-assisted step. `brief.pdf` is a two-page summary.
