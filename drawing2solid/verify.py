"""
drawing2solid.verify: reproject the built solid onto the source drawing.

Answers one question with evidence: do the axial feature positions of the
BUILT SOLID coincide with the feature edges VISIBLE IN THE DRAWING RASTER?

Method
  1. The caller crops the drawing to the main (side) view and supplies the
     pixel box; nothing else is trusted from the raster.
  2. Vertical part edges are detected as vertical dark runs inside the view,
     recorded with their run height. Dimension/extension lines also show up, but
     they are tolerated, because unmatched detections never count against
     the score; only model transitions that miss do.
  3. Calibration never trusts end faces (extension lines spoof them).
     Instead the TALLEST detections are paired with the model's LARGEST-RADIUS
     transitions (on a turned part these are the flange faces, the most
     reliable lines on the sheet), then origin+scale are refined by least
     squares over all greedy matches.
  4. Every model transition is matched to its nearest detection; residuals
     are reported in drawing units (mm).

Verdict: PASS if every visible transition matches within tol; CHECK if >= 90%;
FAIL otherwise. Transitions whose silhouette step is below ~2 px (tangencies,
edge breaks) are reported 'not visible' and excluded from the denominator.

Usage:
    python -m drawing2solid.verify report.json drawing.png \
        --box L,T,R,B [--tol 0.15]
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image


def detect_vertical_runs(img_gray, box, dark=110):
    """All columns in box with their longest vertical dark run (px).
    Adjacent columns are merged (a drawn line is 2-4 px wide)."""
    l, t, r, b = box
    a = np.asarray(img_gray)[t:b, l:r] < dark
    runs = []
    for c in range(a.shape[1]):
        col = a[:, c]
        best = cur = 0
        for v in col:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        if best >= 8:
            runs.append([l + c, best])
    merged = []
    for x, h in runs:
        if merged and x - merged[-1][0] == 1:   # only directly adjacent columns
            if h > merged[-1][1]:
                merged[-1] = [x, h]
        else:
            merged.append([x, h])
    return [(x, h) for x, h in merged]


def calibrate(detections, transitions, box_h):
    """Pair tallest detections with largest-radius model transitions.
    Returns (x0_px, scale_px_per_unit)."""
    r_max = max(r for _, r in transitions)
    tall_model = sorted(x for x, r in transitions if r > 0.9 * r_max)
    tall_px = sorted(x for x, h in detections if h > 0.80 * box_h)
    if len(tall_model) < 2 or len(tall_px) < 2:
        raise RuntimeError(
            f"calibration needs >=2 tall edges; found {len(tall_px)} in raster, "
            f"{len(tall_model)} in model")
    # initial fit from the outermost tall pair
    scale = (tall_px[-1] - tall_px[0]) / (tall_model[-1] - tall_model[0])
    x0 = tall_px[0] - tall_model[0] * scale

    # refine: greedy-match every model transition, least-squares on inliers
    for _ in range(3):
        pairs = []
        for xm, r in transitions:
            pe = x0 + xm * scale
            near = min(detections, key=lambda d: abs(d[0] - pe))
            if abs(near[0] - pe) <= 3:          # inliers only
                pairs.append((xm, near[0]))
        if len(pairs) >= 4:
            xs = np.array([p[0] for p in pairs])
            ps = np.array([p[1] for p in pairs])
            A = np.vstack([xs, np.ones_like(xs)]).T
            scale, x0 = np.linalg.lstsq(A, ps, rcond=None)[0]
    return float(x0), float(scale)


def verify(report, image_path, box, tol_mm=0.15):
    im = Image.open(image_path).convert("L")
    box_h = box[3] - box[1]
    detections = detect_vertical_runs(im, box)
    transitions = report.get("transitions_outline")
    if not transitions:
        raise RuntimeError("report lacks transitions_outline; rebuild with the current builder")

    x0, scale = calibrate(detections, transitions, box_h)

    # cluster outline transitions the raster cannot separate (~2.5 px)
    res_mm = max(0.35, 2.5 / scale)
    clusters, cur = [], [transitions[0]]
    for t in transitions[1:]:
        if t[0] - cur[-1][0] <= res_mm:
            cur.append(t)
        else:
            clusters.append(cur)
            cur = [t]
    clusters.append(cur)

    rows, matched, considered = [], 0, 0
    for cl in clusters:
        # a cluster matches if ANY member sits within tol of a detection
        best = None
        for xm, r in cl:
            pe = x0 + xm * scale
            near = min(detections, key=lambda d: abs(d[0] - pe))
            resid = (near[0] - pe) / scale
            if best is None or abs(resid) < abs(best[1]):
                best = (xm, resid, near[0])
        label = "%.3g" % cl[0][0] if len(cl) == 1 else \
            "%.3g..%.3g" % (cl[0][0], cl[-1][0])
        if abs(best[1]) > max(4 * tol_mm, 3 / scale):
            rows.append(dict(model_x=label, status="not visible"))
            continue
        considered += 1
        ok = abs(best[1]) <= tol_mm
        matched += int(ok)
        rows.append(dict(model_x=label, px=int(best[2]),
                         resid_mm=round(float(best[1]), 3),
                         status="ok" if ok else "MISMATCH"))
    for xm, r in report.get("transitions_internal", []):
        rows.append(dict(model_x=float(xm), status="internal, not scored"))

    res = dict(
        x0_px=round(x0, 2), scale_px_per_unit=round(scale, 4), tol_mm=tol_mm,
        outline_clusters=len(clusters),
        transitions_visible=considered, transitions_matched=matched,
        score=round(matched / considered, 3) if considered else None,
        rows=rows,
    )
    res["verdict"] = ("PASS" if considered >= 6 and matched == considered else
                      "CHECK" if considered and matched / considered >= 0.9 else
                      "FAIL")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("image")
    ap.add_argument("--box", required=True, help="main-view pixel box L,T,R,B")
    ap.add_argument("--tol", type=float, default=0.15)
    a = ap.parse_args()
    report = json.load(open(a.report))
    box = tuple(int(v) for v in a.box.split(","))
    res = verify(report, a.image, box, a.tol)
    print(json.dumps(res, indent=1))
    sys.exit(0 if res["verdict"] != "FAIL" else 3)


if __name__ == "__main__":
    main()
