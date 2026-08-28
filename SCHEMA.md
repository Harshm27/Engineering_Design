# Part-spec schema (v1): turned parts

The spec is the contract between *interpretation* (a human or an LLM reading the
drawing) and *construction* (deterministic code). Everything in it is a number
read off the drawing or a constraint stated by it; nothing is a guess about
final coordinates. The builder solves the geometry and **refuses to build**
if the numbers do not close.

Coordinates: `x` is the axial direction (0 at the left face), `r` is radius.
All values in the drawing's units (`units`, normally mm).

```jsonc
{
  "name": "spool_shaft",                 // used for output filenames
  "source_drawing": "xometry_lathe_sample_v2.0",
  "units": "mm",
  "kind": "turned",                      // v1 supports revolved parts + axial/radial features
  "material": { "name": "Stainless steel", "density_g_cm3": 7.90 },

  // ---- outer profile: ordered from x=0 to x=L, as (x, r) vertices ----
  // Vertex ops soften the corner AT that vertex:
  //   "chamfer": c      -> c × 45° chamfer
  //   "fillet": r       -> radius r
  // Arc segments replace a corner with a solved arc:
  //   {"arc": {"radius": R, "center_r": rc, "center_x": xc}}
  //       explicit centre; runs from the previous vertex to the tangency
  //       with whatever comes next (line or blend)
  //   {"blend": {"radius": rf}}
  //       fillet arc solved tangent to BOTH neighbours (arc-to-line or line-to-line)
  "profile": [
    { "pt": [0, 5],    "chamfer": 0.3 },          // left face meets ø10
    { "pt": [8, 5],    "fillet": 1.0 },           // spigot -> flange face
    { "pt": [8, 20],   "chamfer": 1.0 },          // flange face up to ø40 (1×45° on the corner)
    { "pt": [11, 20],  "fillet": 0.3 },           // 3-wide land; R0,3 break into the flare
    { "arc": { "radius": 19, "center_r": 21.5, "center_x": 29.9 } },
    { "blend": { "radius": 3 } },                  // R3 tangent to the ø15 drum
    { "pt": [null, 7.5] },                         // drum: x solved by tangency
    { "blend": { "radius": 3 } },
    { "arc": { "radius": 19, "center_r": 21.5, "center_x": 35.1 } },
    { "pt": [54, 20],  "fillet": 0.3 },
    { "pt": [56, 20],  "chamfer": 1.0 },
    { "pt": [57, 20] },
    { "pt": [57, 5],   "fillet": 1.0 },
    { "pt": [69, 5] },                             // ø10 journal to the undercut shoulder
    { "pt": [69, 4] },                             // shoulder down to ø8 (undercut feature refines this)
    { "pt": [76, 4],   "chamfer": 0.3 }            // right face
  ],

  // ---- features cut after the revolve ----
  "features": [
    { "type": "hole_axial", "end": "left",  "d": 3.3, "depth": 12,
      "tip_angle": 118, "mouth_chamfer": 0.5, "thread": "M4", "thread_depth": 8 },
    { "type": "hole_axial", "end": "right", "d": 4.0, "depth": 12,
      "tip_angle": 118, "mouth_chamfer": 0.5 },
    { "type": "hole_pattern_axial", "ends": ["left","right"], "n": 4,
      "d": 3.0, "pcd": 30, "depth": 14 },          // depth from that end face; through the flange
    { "type": "undercut_din509", "form": "E", "at_x": 69, "into": "left",
      "width": 2.0, "depth": 0.2, "radius": 0.4, "angle_deg": 15, "shaft_r": 4.0 }
  ],

  // ---- closure checks: build FAILS if any of these don't hold ----
  "checks": {
    "overall_length": { "value": 76, "tol": 0.1 },
    "max_diameter":   { "value": 40, "tol": 0.05 },
    "diameters_present": [40, 15, 10, 8],          // radii that must appear as cylindrical lands
    "mass_g": { "value": null, "tol_pct": 5 }      // optional, if the drawing states Gewicht
  },

  // ---- optional: drives the generated viewer's dimension schedule ----
  "schedule": [
    { "balloon": 17, "feature": "Overall length", "value": "76 ±0,1",
      "anchor": [38, 0, -20] }
  ]
}
```

## Rules the builder enforces

1. `pt` x-values must be non-decreasing; a `null` x means "solved by the
   adjacent arc/blend tangency" and is only legal next to an arc or blend.
2. Every `arc` must actually reach its neighbours: the solved tangent points
   must lie between the neighbouring vertices, else the build aborts with the
   residual printed (this is the "dimension chain doesn't close" alarm).
3. `checks.overall_length` and `max_diameter` are compared against the built
   solid's bounding box, not against the spec's own numbers, so a misread
   interior dimension is caught, not laundered.
4. Threads are modelled at tapping-drill diameter (ISO coarse table built in)
   and recorded in the report; they are never silently cut as ø=nominal.

## What v1 does not cover

Milled pockets, keyways/flats (planned as `cut_flat`), non-axial holes,
free-form surfaces. The schema is versioned so these extend rather than break.
