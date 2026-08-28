---
name: drawing-to-3d
description: Reconstruct a verified 3D solid (STEP/STL + interactive HTML viewer) from a 2D engineering drawing image or PDF. Use whenever the user provides a technical/engineering drawing, machine drawing, manufacturing drawing, or blueprint and wants a 3D model, 3D render, 3D viewer, or CAD file from it. Triggers: "2D to 3D", "render this drawing in 3D", "make a model from this drawing", "STEP file from drawing".
---

# Drawing → verified 3D solid

Converts a dimensioned 2D engineering drawing into a B-rep solid with evidence
that the reconstruction is right. The pipeline splits the work into what an
LLM is good at (reading and interpreting the drawing) and what code must do
(solving geometry, refusing inconsistency, measuring the result).

**You never write geometry coordinates by hand.** You fill a spec; the code
solves, builds, and checks.

## Pipeline

```
read drawing  →  spec.json  →  builder (refuses if numbers don't close)
                                  →  STEP / STL / report.json
                              →  verify (reprojects solid onto the raster)
                              →  viewer (interactive HTML)
```

Scope v1: turned (revolved) parts with axial holes, axial hole patterns on a
PCD, and DIN 509 undercuts. For milled/prismatic parts, say so honestly and
model manually, or extend the schema.

## Step 1. Read the drawing (the part that needs judgment)

1. **Never read the whole sheet at once.** Crop to each view and upscale 3–4×
   (PIL: crop, resize LANCZOS) before Reading. Read the title block too:
   material, general tolerance, scale, projection, weight if stated.
2. **Distinguish part outline from dimension extension lines.** Extension
   lines touch the surface at the same height, and the most common misreading is
   taking one for a silhouette edge. If an edge seems to exist where no
   dimension explains it, it is probably an extension line.
3. **Close the arithmetic before writing the spec.** Sum the axial chain and
   compare with the overall length. If it does not close, a datum is misread, so
   go back to the crops. Drawings are deliberately redundant; use it.
4. **Expand standard callouts** rather than guessing: DIN 509 E/F undercuts,
   DIN 76 thread runouts, ISO 4762/7380 counterbores, centre drills (DIN 332).
   Thread callouts (M4 etc.) are modelled at tapping drill; note it.
5. Arcs are usually located by their **centres** plus tangency, not endpoints.
   Record centre coordinates in the spec; the builder solves the tangencies
   and refuses if the stated centre disagrees with the anchor vertex.

## Step 2. Write the spec

Read `SCHEMA.md` in this skill's directory. Fill `profile` (x, r vertices with
chamfer/fillet corner ops; `arc`/`blend` connectors), `features`, `checks`
(overall length, max diameter, diameters that must exist, stated mass if the
title block gives one), and optionally `schedule` for the viewer's clickable
dimension table.

## Step 3. Build (deterministic)

```bash
pip install cadquery --break-system-packages   # once
python -m drawing2solid.builder spec.json -o out/
```

Exit 2 = BUILD REFUSED with the residual that failed. That residual is a
misreading alarm: return to Step 1, do not force numbers until it builds.
Success writes STEP, STL, BREP and `<name>_report.json`.

## Step 4. Verify against the source raster (always run this)

```bash
python -m drawing2solid.verify out/<name>_report.json drawing.png \
    --box L,T,R,B          # pixel box of the MAIN side view only
```

Calibration pairs the tallest drawn verticals with the model's largest-radius
faces, then least-squares refines. PASS = every visible silhouette line within
tolerance. FAIL on a spec the builder accepted means the spec is
self-consistent but wrong versus the drawing, so re-read the mismatched features
(the report names them). Show the user the residual table; it is the evidence.

## Step 5. Viewer

```bash
python -m drawing2solid.viewer spec.json out/<name>_report.json \
    out/<name>.brep -o viewer.html
```

Self-contained HTML (three.js inlined): orbit/zoom, four standard views,
half/quarter sections with hatched caps, edge overlay, clickable dimension
schedule. Publish as an Artifact when available; otherwise deliver the file.
Deliver STEP + STL + spec.json alongside, and state the modelling caveats
(threads at tapping drill; edge breaks as 0,3 chamfers/fillets).

## Failure honesty

- Builder REFUSED → say which dimension chain failed and re-read; never tweak
  numbers just to make it build.
- Verifier FAIL → show the mismatch rows; fix the spec, not the verifier.
- Drawing features outside v1 scope → say so and either extend the schema or
  model that feature manually in CadQuery on top of the built solid.
