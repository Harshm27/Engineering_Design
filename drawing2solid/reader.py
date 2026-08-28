"""
drawing2solid.reader: the one AI step. Drawing image in, spec out.

Sends the drawing to the Claude API with the reading rules from SKILL.md and
the spec format from SCHEMA.md, gets a spec JSON back, and tries to build it.
If the builder refuses (the numbers do not close, which is what a misreading
looks like), the refusal is sent back to the model for ONE corrected reading.
Two model calls maximum per drawing.

Needs ANTHROPIC_API_KEY in the environment. Costs a few pence per drawing.
Scope matches the pipeline: turned parts. The model is told to say so, rather
than guess, when a drawing is outside that scope.

    python -m drawing2solid.reader my_drawing.png -o out/
"""

import argparse
import base64
import json
import os
import re
import sys

from . import builder

DEFAULT_MODEL = os.environ.get("READER_MODEL", "claude-sonnet-4-5")

RULES = """\
You are reading a dimensioned 2D mechanical engineering drawing of a TURNED
(lathe) part, to produce a machine-checkable spec. Work like a machinist:

1. Read the title block first: material, general tolerance, stated mass, scale.
2. Distinguish the part outline from dimension extension lines. Extension lines
   touch the surface at the same height; the commonest misreading is taking one
   for a silhouette edge. If an edge has no dimension explaining it, it is
   probably an extension line.
3. Close the arithmetic BEFORE answering: the axial chain of individual lengths
   must sum to the overall length. If it does not, one of your readings is
   wrong; re-examine the view rather than forcing it.
4. Arcs are usually located by their CENTRES plus tangency, not endpoints.
   Record centre coordinates; the builder solves the tangencies and will refuse
   if a stated centre disagrees with the geometry.
5. Expand standard callouts: DIN 509 E/F undercuts, thread callouts (an M4 is
   modelled at its tapping drill), centre drills, chamfer notes like 1x45.
6. Diameters on the drawing are diameters; the spec stores RADII in profile
   points. Halve them.

OUTPUT: a single JSON object, nothing else, no markdown fences. Either a spec
in exactly this format (x along the axis from the left face, r = radius, all in
the drawing's units):

{
 "name": "<short_snake_case_name>",
 "units": "mm",
 "kind": "turned",
 "material": {"name": "<from title block, or 'unstated (mild steel assumed)'>",
              "density_g_cm3": <number>},
 "profile": [
   {"pt": [<x>, <r>], "chamfer": <optional c of a c x 45 corner>, "fillet": <optional r>},
   {"arc": {"radius": <R>, "center_r": <centre's radius>, "center_x": <centre's x>}},
   {"blend": {"radius": <fillet R tangent to both neighbours>}},
   {"pt": [null, <r>]}   // x solved by tangency, only next to an arc/blend
   ... ordered left face (x=0) to right face
 ],
 "features": [
   {"type": "hole_axial", "end": "left|right", "d": <drill dia>, "depth": <n>,
    "tip_angle": 118, "mouth_chamfer": <n>, "thread": "M4", "thread_depth": <n>},
   {"type": "hole_pattern_axial", "ends": ["left","right"], "n": <count>,
    "d": <dia>, "pcd": <pitch circle dia>, "depth": <n>},
   {"type": "undercut_din509", "form": "E", "at_x": <shoulder x>, "into": "right",
    "width": <n>, "depth": <n>, "radius": <n>, "angle_deg": 15, "shaft_r": <r>}
 ],
 "checks": {
   "overall_length": {"value": <stated overall>, "tol": <its tolerance or 0.1>},
   "max_diameter":   {"value": <largest stated dia>, "tol": 0.05},
   "diameters_present": [<each stated cylindrical dia>]
 }
}

Or, when the drawing is not a turned part or is unreadable:

{"error": "<one sentence saying what it is and why it is out of scope>"}
"""


class ReadError(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError:
        raise ReadError("pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ReadError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic()


def _image_block(data: bytes, media_type: str):
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.b64encode(data).decode()}}


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ReadError("the model returned no JSON:\n" + text[:400])
    return json.loads(m.group(0))


def read_drawing(image_bytes: bytes, media_type: str = "image/png",
                 model: str = DEFAULT_MODEL, mock_spec: dict = None):
    """-> (spec, attempts, notes). Raises ReadError when the drawing cannot be
    read, builder.ChainError when two attempts still do not close."""
    if mock_spec is not None:
        return mock_spec, 0, ["mock read: no model was called"]

    client = _client()
    messages = [{"role": "user", "content": [
        _image_block(image_bytes, media_type),
        {"type": "text", "text": "Read this drawing into a spec."}]}]

    last_err = None
    for attempt in (1, 2):
        r = client.messages.create(model=model, max_tokens=4000, temperature=0,
                                   system=RULES, messages=messages)
        text = "".join(b.text for b in r.content if b.type == "text")
        spec = _extract_json(text)
        if "error" in spec:
            raise ReadError(spec["error"])
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                builder.build(spec, td)          # dry-run: does it close?
            notes = [f"read on attempt {attempt} of 2"]
            return spec, attempt, notes
        except builder.ChainError as e:
            last_err = e
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content":
                f"Your reading does not close arithmetically. The builder "
                f"refused with:\n\n{e}\n\nRe-examine the drawing, correct the "
                f"misread dimension, and return the full corrected JSON only."})
    raise last_err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    data = open(a.image, "rb").read()
    mt = "image/jpeg" if a.image.lower().endswith((".jpg", ".jpeg")) else \
         "image/webp" if a.image.lower().endswith(".webp") else "image/png"
    try:
        spec, attempts, notes = read_drawing(data, mt, a.model)
    except (ReadError, builder.ChainError) as e:
        print("READ FAILED:", e, file=sys.stderr)
        sys.exit(2)
    os.makedirs(a.outdir, exist_ok=True)
    path = os.path.join(a.outdir, spec.get("name", "part") + ".spec.json")
    json.dump(spec, open(path, "w"), indent=1)
    _, report = builder.build(spec, a.outdir)
    print(json.dumps({"spec": path, "notes": notes, "report": report}, indent=1))


if __name__ == "__main__":
    main()
