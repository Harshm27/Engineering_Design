"""
drawing2solid.viewer: generate the interactive HTML viewer for a built part.

Takes the .brep written by the builder plus the spec and report, tessellates
the solid (per-face vertex normals: smooth surfaces, sharp creases), builds
exact section-cap faces for half/quarter sections, quantizes everything, and
injects it into the packaged template together with three.js.

The spec's optional "schedule" list drives the clickable dimension table:
    { "balloon": 17, "feature": "Overall length", "value": "76 ±0,1",
      "anchor": [x, y, z], "offset": [dx, dy] }   // offset in px, optional

Usage:
    python -m drawing2solid.viewer spec.json report.json part.brep \
        -o viewer.html [--three path/to/three.min.js]
"""

import argparse
import base64
import json
import math
import os

import numpy as np
import cadquery as cq
from OCP.BRep import BRep_Tool, BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopLoc import TopLoc_Location

HERE = os.path.dirname(__file__)


def load_brep(path):
    sh = TopoDS_Shape()
    BRepTools.Read_s(sh, path, BRep_Builder())
    return cq.Shape.cast(sh)


def tessellate(shape, lin=0.035, ang=0.15):
    BRepMesh_IncrementalMesh(shape.wrapped, lin, False, ang, True)
    V, N, I = [], [], []
    base = 0
    ex = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        ex.Next()
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is None:
            continue
        tr = loc.Transformation()
        rev = f.Orientation() == TopAbs_REVERSED
        pts = np.array([[p.X(), p.Y(), p.Z()] for p in
                        (tri.Node(i).Transformed(tr) for i in range(1, tri.NbNodes() + 1))])
        tris = []
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            tris.append((c - 1, b - 1, a - 1) if rev else (a - 1, b - 1, c - 1))
        tris = np.array(tris)
        nrm = np.zeros_like(pts)
        fn = np.cross(pts[tris[:, 1]] - pts[tris[:, 0]], pts[tris[:, 2]] - pts[tris[:, 0]])
        for k in range(3):
            np.add.at(nrm, tris[:, k], fn)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True)
        ln[ln == 0] = 1
        nrm /= ln
        V.append(pts)
        N.append(nrm)
        I.append(tris + base)
        base += len(pts)
    return np.vstack(V), np.vstack(N), np.vstack(I)


def pack(V, N, I, ctr, half):
    if len(V) >= 65536:
        raise RuntimeError(f"mesh too dense for u16 indices ({len(V)} verts): "
                           "raise tessellation tolerance")
    q = np.clip(np.round((V - ctr) / half * 32767), -32767, 32767).astype("<i2")
    nq = np.clip(np.round(N * 127), -127, 127).astype("i1")
    return dict(p=base64.b64encode(q.tobytes()).decode(),
                n=base64.b64encode(nq.tobytes()).decode(),
                i=base64.b64encode(I.astype("<u2").tobytes()).decode(),
                nv=len(V), tris=len(I))


def cap_faces(solid, normal_axis, at, big=1000.0):
    """Exact planar faces where the solid is cut by the plane axis=at
    (keeps the axis<at half). Returns None if the plane misses the solid."""
    bb = solid.BoundingBox()
    o = [bb.xmin - 1, -big / 2 + (at if normal_axis == 1 else 0),
         -big / 2 + (at if normal_axis == 2 else 0)]
    o[normal_axis] = at
    cut = solid.cut(cq.Solid.makeBox(big, big, big, cq.Vector(*o)))
    keep = []
    for f in cut.Faces():
        try:
            n = f.normalAt()                       # normal at parametric midpoint
            c = f.Center()
        except Exception:
            continue
        if abs([c.x, c.y, c.z][normal_axis] - at) < 1e-6 and abs([n.x, n.y, n.z][normal_axis]) > 0.999:
            keep.append(f)
    return cq.Compound.makeCompound(keep) if keep else None


def edge_polylines(solid, step=0.3):
    segs = []
    for e in solid.Edges():
        n = max(2, min(200, int(e.Length() / step) + 2))
        pl = [e.positionAt(i / (n - 1)) for i in range(n)]
        for a, b in zip(pl[:-1], pl[1:]):
            segs += [a.x, a.y, a.z, b.x, b.y, b.z]
    return np.array(segs).reshape(-1, 3)


def generate(spec, report, brep_path, out_path, three_path=None):
    solid = load_brep(brep_path)
    bb = solid.BoundingBox()
    ctr = np.array([(bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2])
    half = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin, bb.zmax - bb.zmin) / 2 * 1.12

    geom = {"ctr": ctr.tolist(), "half": float(half)}
    geom["body"] = pack(*tessellate(solid), ctr, half)
    EMPTY = dict(p="", n="", i="", nv=0, tris=0)
    cz = cap_faces(solid, 2, float(ctr[2]))
    cy = cap_faces(solid, 1, float(ctr[1]))
    geom["capZ"] = pack(*tessellate(cz, 0.05, 0.2), ctr, half) if cz else EMPTY
    geom["capY"] = pack(*tessellate(cy, 0.05, 0.2), ctr, half) if cy else EMPTY
    sa = edge_polylines(solid)
    geom["edges"] = base64.b64encode(
        np.clip(np.round((sa - ctr) / half * 32767), -32767, 32767)
        .astype("<i2").tobytes()).decode()
    geom["nedge"] = len(sa)

    sched = []
    for s in spec.get("schedule", []):
        sched.append(dict(b=s.get("balloon", ""), f=s["feature"], v=s["value"],
                          a=s.get("anchor", ctr.tolist()),
                          o=s.get("offset", [0, -30])))
    cfg = dict(
        title=spec.get("title", spec["name"].replace("_", " ")),
        subtitle=spec.get("subtitle", f"Rebuilt from drawing {spec.get('source_drawing', '')}".strip()),
        part=spec.get("source_drawing", spec["name"]),
        material=spec.get("material", {}).get("name"),
        density=("%.2f" % spec["material"]["density_g_cm3"]).replace(".", ",")
        if spec.get("material", {}).get("density_g_cm3") else None,
        mass_g=report.get("mass_g"),
        volume_mm3=report.get("volume_mm3"),
        faces=report.get("faces"),
        gen_tol=spec.get("gen_tol"),
        finish=spec.get("finish"),
        note=spec.get("note", " ".join(report.get("notes", []))),
        schedule=sched,
        dist=float(half * 5.0),
        eyebrow=spec.get("eyebrow"),
    )

    tpl = open(os.path.join(HERE, "template.html")).read()
    three_path = three_path or os.path.join(HERE, "vendor", "three.min.js")
    html = (tpl.replace("__TITLE__", cfg["title"])
               .replace("/*__THREE__*/", open(three_path).read())
               .replace("/*__GEOM__*/", json.dumps(geom))
               .replace("/*__CFG__*/", json.dumps(cfg)))
    with open(out_path, "w") as fh:
        fh.write(html)
    return out_path, len(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("report")
    ap.add_argument("brep")
    ap.add_argument("-o", "--out", default="viewer.html")
    ap.add_argument("--three", default=None)
    a = ap.parse_args()
    path, size = generate(json.load(open(a.spec)), json.load(open(a.report)),
                          a.brep, a.out, a.three)
    print(f"{path}  {size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
