"""
drawing2solid.builder: deterministic construction of a turned part from a spec.

The spec (see SCHEMA.md) contains numbers read off a drawing plus constraints.
This module solves the constraints, REFUSES to build when they do not close,
revolves the profile, cuts the features, runs the closure checks, and exports
STEP/STL/BREP plus a JSON build report.

Profile model: an ordered list of explicit (x, r) vertices with optional
chamfer/fillet corner ops, separated by "gaps". A gap holds zero or more
connectors, solved deterministically:

    []             straight line between the two vertices
    [arc]          arc with explicit centre+radius; the far vertex's x may be
                   null and is then solved as the arc/radius intersection
    [arc, blend]   arc, then a fillet tangent to BOTH the arc and the
                   horizontal line at the next vertex's radius
    [blend, arc]   mirror case: fillet leaves the horizontal line at the
                   previous vertex's radius, tangent onto the arc

Every solved tangency is checked against any explicit x the spec carries; a
disagreement beyond 0.06 units aborts the build with the residual printed, and
that residual is the "you misread the drawing" alarm.

Usage:
    python -m drawing2solid.builder spec.json [-o outdir]
"""

import argparse
import json
import math
import os
import sys

import cadquery as cq

TAP_DRILL = {"M2": 1.6, "M2.5": 2.05, "M3": 2.5, "M4": 3.3, "M5": 4.2,
             "M6": 5.0, "M8": 6.8, "M10": 8.5, "M12": 10.2, "M16": 14.0}

TOL_SNAP = 0.06   # max residual between a solved tangency and a stated dimension


class ChainError(RuntimeError):
    """The spec's numbers do not close; the drawing was misread somewhere."""


# ---------------------------------------------------------------- geometry --

def arc_mid(c, p0, p1, R):
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    if a1 - a0 > math.pi:
        a1 -= 2 * math.pi
    if a0 - a1 > math.pi:
        a1 += 2 * math.pi
    am = (a0 + a1) / 2
    return (c[0] + R * math.cos(am), c[1] + R * math.sin(am))


def circle_x_at_r(cx, cy, R, y, side):
    """x where circle (cx,cy,R) crosses radius y; side -1 left / +1 right of centre."""
    d2 = R * R - (cy - y) ** 2
    if d2 < 0:
        raise ChainError(f"arc R{R} centred at r={cy} never reaches radius {y} "
                         f"(short by {abs(cy - y) - R:.3f})")
    return cx + side * math.sqrt(d2)


def fillet_arc_to_line(cx, cy, R, y_line, rf, side):
    """Fillet rf tangent to circle (cx,cy,R), where the profile runs on the
    circle's inside (our concave-flare case), and to the horizontal line at y_line,
    which lies below the arc centre. side: -1 fillet left of arc centre, +1 right.
    Returns (fillet_centre, tangent_on_arc, tangent_on_line)."""
    fy = y_line + rf
    reach = R - rf
    d2 = reach * reach - (cy - fy) ** 2
    if d2 < 0:
        raise ChainError(f"blend R{rf}: arc R{R} (centre r={cy}) cannot reach "
                         f"radius {y_line} (short by {abs(cy - fy) - reach:.3f})")
    fx = cx + side * math.sqrt(d2)
    ux, uy = (fx - cx) / reach, (fy - cy) / reach
    return (fx, fy), (cx + R * ux, cy + R * uy), (fx, y_line)


# ---------------------------------------------------------- profile solving --

def _parse(profile):
    verts, gaps, cur = [], [], []
    for it in profile:
        if "pt" in it:
            verts.append(dict(x=it["pt"][0], r=it["pt"][1],
                              chamfer=it.get("chamfer"), fillet=it.get("fillet")))
            gaps.append(cur)
            cur = []
        elif "arc" in it:
            cur.append(("arc", it["arc"]))
        elif "blend" in it:
            cur.append(("blend", it["blend"]["radius"]))
        else:
            raise ChainError(f"unknown profile item: {it}")
    if cur:
        raise ChainError("profile must end on a pt")
    return verts, gaps[1:]  # gaps[0] precedes the first vertex and must be empty


def _check_stated(x_solved, x_stated, what):
    if x_stated is not None and abs(x_stated - x_solved) > TOL_SNAP:
        raise ChainError(f"{what}: solved x={x_solved:.3f} but the spec states "
                         f"x={x_stated} (residual {x_stated - x_solved:+.3f})")
    return x_solved


def solve_profile(profile):
    """-> (segments, vertex_xy) where segments = [('line',p0,p1) | ('arc',p0,mid,p1)]
    and vertex_xy aligns with the spec's pt items (for corner ops)."""
    verts, gaps = _parse(profile)
    if verts[0]["x"] is None:
        raise ChainError("first vertex needs an explicit x")
    segs = []
    for i, gap in enumerate(gaps):
        A, B = verts[i], verts[i + 1]
        pa = (A["x"], A["r"])

        if not gap:
            if B["x"] is None:
                raise ChainError(f"vertex {i+1}: null x with no arc/blend to solve it")
            if B["x"] < pa[0] - 1e-9 and abs(B["r"] - pa[1]) > 1e-9:
                raise ChainError(f"profile x goes backwards into ({B['x']},{B['r']})")
            segs.append(("line", pa, (B["x"], B["r"])))
            continue

        kinds = [k for k, _ in gap]
        if kinds == ["arc"]:
            a = gap[0][1]
            R, cy = a["radius"], a["center_r"]
            # snap centre x so the arc passes exactly through the anchored vertex
            anchor, other = (pa, B) if abs(math.hypot(pa[0]-a["center_x"], pa[1]-cy) - R) \
                <= TOL_SNAP else ((B["x"], B["r"]), A)
            if anchor[0] is None:
                raise ChainError("arc anchored on a null-x vertex")
            dx = math.sqrt(max(R*R - (cy - anchor[1])**2, 0))
            cx = anchor[0] + dx if a["center_x"] >= anchor[0] else anchor[0] - dx
            _check_stated(cx, a["center_x"], f"arc R{R} centre location")
            d_prev = math.hypot(pa[0]-cx, pa[1]-cy)
            if abs(d_prev - R) > TOL_SNAP:
                raise ChainError(f"arc R{R}: previous vertex {pa} is {d_prev - R:+.3f} off the arc")
            side = +1 if B["r"] is not None and (B["x"] is None or B["x"] >= cx) else -1
            xb = circle_x_at_r(cx, cy, R, B["r"], side)
            B["x"] = _check_stated(xb, B["x"], f"arc R{R} onto r={B['r']}")
            pb = (B["x"], B["r"])
            segs.append(("arc", pa, arc_mid((cx, cy), pa, pb, R), pb))

        elif kinds == ["arc", "blend"]:
            a, rf = gap[0][1], gap[1][1]
            R, cy = a["radius"], a["center_r"]
            dx = math.sqrt(max(R*R - (cy - pa[1])**2, 0))
            cx = pa[0] + dx if a["center_x"] >= pa[0] else pa[0] - dx
            _check_stated(cx, a["center_x"], f"arc R{R} centre location")
            # the blend lands on the horizontal line at B.r; fillet sits between arc start and B
            side = -1 if cx > pa[0] else +1
            fc, t_arc, t_line = fillet_arc_to_line(cx, cy, R, B["r"], rf, side)
            segs.append(("arc", pa, arc_mid((cx, cy), pa, t_arc, R), t_arc))
            segs.append(("arc", t_arc, arc_mid(fc, t_arc, t_line, rf), t_line))
            B["x"] = _check_stated(t_line[0], B["x"], f"blend R{rf} onto r={B['r']}")

        elif kinds == ["blend", "arc"]:
            rf, a = gap[0][1], gap[1][1]
            R, cy = a["radius"], a["center_r"]
            # arc is anchored on B (must be explicit); fillet leaves the line at A.r
            if B["x"] is None:
                raise ChainError("blend+arc: far vertex needs explicit x")
            pb = (B["x"], B["r"])
            dx = math.sqrt(max(R*R - (cy - pb[1])**2, 0))
            cx = pb[0] + dx if a["center_x"] >= pb[0] else pb[0] - dx
            _check_stated(cx, a["center_x"], f"arc R{R} centre location")
            side = +1 if cx < pb[0] else -1
            fc, t_arc, t_line = fillet_arc_to_line(cx, cy, R, pa[1], rf, side)
            if t_line[0] < pa[0] - 1e-6:
                raise ChainError(f"blend R{rf} would start at x={t_line[0]:.3f}, "
                                 f"before the current vertex {pa}")
            segs.append(("line", pa, t_line))
            segs.append(("arc", t_line, arc_mid(fc, t_line, t_arc, rf), t_arc))
            segs.append(("arc", t_arc, arc_mid((cx, cy), t_arc, pb, R), pb))

        else:
            raise ChainError(f"unsupported connector sequence {kinds}")

    return segs, [(v["x"], v["r"], v.get("chamfer"), v.get("fillet")) for v in verts]


# ----------------------------------------------------------------- solid ----

def make_solid(segs, vertex_ops):
    w = cq.Workplane("XY").moveTo(*segs[0][1])
    for s in segs:
        if s[0] == "line":
            if math.hypot(s[2][0]-s[1][0], s[2][1]-s[1][1]) < 1e-9:
                continue
            w = w.lineTo(*s[2])
        else:
            w = w.threePointArc(s[2], s[3])
    p0, pn = segs[0][1], (segs[-1][2] if segs[-1][0] == "line" else segs[-1][3])
    w = w.lineTo(pn[0], 0).lineTo(p0[0], 0).close()
    wire = cq.Wire.assembleEdges(w.ctx.pendingEdges) if w.ctx.pendingEdges else w.val()
    if not isinstance(wire, cq.Wire):
        wire = w.val()

    for (px, pr, ch, fi) in vertex_ops:
        if not (ch or fi):
            continue
        vs = [v for v in wire.Vertices() if abs(v.X-px) < 1e-4 and abs(v.Y-pr) < 1e-4]
        if not vs:
            raise ChainError(f"corner op at ({px},{pr}): vertex not on wire")
        n_before = len(wire.Edges())
        wire = wire.chamfer2D(ch, vs) if ch else wire.fillet2D(fi, vs)
        if len(wire.Edges()) == n_before:
            raise ChainError(
                f"corner op at ({px},{pr}) had no effect: the vertex is "
                f"collinear (not a corner). Put the op on the actual corner "
                f"vertex, or remove it.")

    face = cq.Face.makeFromWires(wire)
    return cq.Workplane("XY").newObject([face]).revolve(360, (0, 0, 0), (1, 0, 0)).val()


def _rev(pts):
    wp = cq.Workplane("XY").moveTo(*pts[0])
    for p in pts[1:]:
        wp = wp.lineTo(*p)
    return wp.close().revolve(360, (0, 0, 0), (1, 0, 0)).val()


def cut_features(solid, spec, L, report):
    for f in spec.get("features", []):
        t = f["type"]
        if t == "hole_axial":
            d = f["d"]
            if f.get("thread"):
                d = TAP_DRILL.get(f["thread"], d)
                report["notes"].append(f"{f['thread']} at tapping drill ø{d}; thread not cut")
            r, dep, ch = d/2, f["depth"], f.get("mouth_chamfer", 0)
            tip = r / math.tan(math.radians(f.get("tip_angle", 118)/2)) if f.get("tip_angle") else 0
            if f["end"] == "left":
                pts = [(0,0), (0,r+ch), (ch,r), (dep,r), (dep+tip,0)]
            else:
                pts = [(L,0), (L,r+ch), (L-ch,r), (L-dep,r), (L-dep-tip,0)]
            solid = solid.cut(_rev(pts))

        elif t == "hole_pattern_axial":
            for end in f.get("ends", [f.get("end", "left")]):
                x0 = -0.5 if end == "left" else L - f["depth"]
                for i in range(f["n"]):
                    a = math.radians(360*i/f["n"] + f.get("start_deg", 0))
                    y, z = f["pcd"]/2*math.cos(a), f["pcd"]/2*math.sin(a)
                    solid = solid.cut(cq.Solid.makeCylinder(
                        f["d"]/2, f["depth"]+1.0, cq.Vector(x0, y, z), cq.Vector(1, 0, 0)))

        elif t == "undercut_din509":
            x, w_, dep = f["at_x"], f["width"], f["depth"]
            R, ang, rs = f["radius"], math.radians(f["angle_deg"]), f["shaft_r"]
            ru = rs - dep
            ramp = dep / math.tan(ang)
            cut = (cq.Workplane("XY").moveTo(x, rs + 1)
                   .lineTo(x, ru + R)
                   .threePointArc(arc_mid((x+R, ru+R), (x, ru+R), (x+R, ru), R), (x+R, ru))
                   .lineTo(x + w_ - ramp, ru)
                   .lineTo(x + w_, rs)
                   .lineTo(x + w_, rs + 1).close()
                   .revolve(360, (0, 0, 0), (1, 0, 0)).val())
            solid = solid.cut(cut)
        else:
            raise ChainError(f"unknown feature type {t}")
    return solid


# ----------------------------------------------------------------- checks ---

def run_checks(solid, spec, report):
    bb = solid.BoundingBox()
    ck = spec.get("checks", {})
    fails = []

    if "overall_length" in ck:
        want, tol = ck["overall_length"]["value"], ck["overall_length"].get("tol", 0.1)
        got = bb.xmax - bb.xmin
        report["checks"]["overall_length"] = round(got, 4)
        if abs(got - want) > tol + 1e-6:
            fails.append(f"overall length {got:.3f} != {want} ±{tol}")

    if "max_diameter" in ck:
        want, tol = ck["max_diameter"]["value"], ck["max_diameter"].get("tol", 0.05)
        got = max(bb.ymax - bb.ymin, bb.zmax - bb.zmin)
        report["checks"]["max_diameter"] = round(got, 4)
        if abs(got - want) > tol + 1e-6:
            fails.append(f"max diameter {got:.3f} != {want} ±{tol}")

    for d in ck.get("diameters_present", []):
        found = False
        for fc in solid.Faces():
            if fc.geomType() == "CYLINDER":
                try:
                    rad = fc._geomAdaptor().Cylinder().Radius()
                except Exception:
                    continue
                if abs(rad*2 - d) < 0.02:
                    found = True
                    break
        report["checks"][f"cylinder_d{d}"] = found
        if not found:
            fails.append(f"no cylindrical land at ø{d} in the built solid")

    mg = ck.get("mass_g") or {}
    if mg.get("value"):
        got = solid.Volume() * spec["material"]["density_g_cm3"] / 1000.0
        report["checks"]["mass_g"] = round(got, 1)
        if abs(got - mg["value"]) / mg["value"] * 100 > mg.get("tol_pct", 5):
            fails.append(f"mass {got:.1f} g != stated {mg['value']} g")

    if fails:
        raise ChainError("closure checks FAILED:\n  " + "\n  ".join(fails))


# ------------------------------------------------------------------ build ---

def build(spec, outdir="."):
    report = {"name": spec["name"], "notes": [], "checks": {}}

    segs, vops = solve_profile(spec["profile"])
    solid = make_solid(segs, vops)
    if not solid.isValid():
        raise ChainError("revolved solid failed OCC validity check")

    def _transitions(s):
        tr = {}
        for e in s.Edges():
            if e.geomType() == "CIRCLE" and abs(e.Center().y) < 1e-6 and abs(e.Center().z) < 1e-6:
                x = round(e.Center().x, 3)
                r = e._geomAdaptor().Circle().Radius()
                tr[x] = max(tr.get(x, 0.0), round(r, 3))
        return tr

    outline = _transitions(solid)               # silhouette: profile only
    L = solid.BoundingBox().xmax
    solid = cut_features(solid, spec, L, report)
    run_checks(solid, spec, report)

    allt = _transitions(solid)
    report["transitions_outline"] = sorted([x, r] for x, r in outline.items())
    report["transitions_internal"] = sorted(
        [x, r] for x, r in allt.items() if x not in outline)
    report["transitions_x"] = sorted(allt)
    report["volume_mm3"] = round(solid.Volume(), 1)
    report["mass_g"] = round(solid.Volume()*spec["material"]["density_g_cm3"]/1000, 1)
    report["faces"] = len(solid.Faces())
    report["valid"] = bool(solid.isValid())

    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, spec["name"])
    cq.exporters.export(cq.Workplane(obj=solid), base + ".step")
    cq.exporters.export(cq.Workplane(obj=solid), base + ".stl",
                        tolerance=0.01, angularTolerance=0.1)
    from OCP.BRepTools import BRepTools
    BRepTools.Write_s(solid.wrapped, base + ".brep")
    with open(base + "_report.json", "w") as fh:
        json.dump(report, fh, indent=1)
    return solid, report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("spec")
    ap.add_argument("-o", "--outdir", default=".")
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    try:
        _, rep = build(spec, a.outdir)
    except ChainError as e:
        print("BUILD REFUSED:", e, file=sys.stderr)
        sys.exit(2)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
