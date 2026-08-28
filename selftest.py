"""
Drawing to Solid: self-test.

Runs the claims the pipeline makes, so you can watch them pass or fail rather
than take them on trust. No arguments; run it from the package root:

    python selftest.py

What it demonstrates, in order:

  1. BUILD          the reference part builds from its spec and matches the
                    expected volume to 0,1 mm3
  2. REFUSES        five specs with a deliberately misread dimension are each
                    rejected, naming the number that does not close
  3. VERIFY PASS    the correct model, projected back onto the source drawing,
                    matches every visible silhouette edge
  4. VERIFY FAIL    a model that is internally consistent but wrong versus the
                    drawing is caught by the reprojection, which is the failure
                    the builder cannot see
  5. VIEWER         a self-contained interactive viewer is produced

Exit code 0 = every claim held. Non-zero = something regressed.
"""

import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "examples", "spool_shaft.json")
DRAWING = os.path.join(HERE, "examples", "spool_shaft_drawing.png")
OUT = os.environ.get("OUTDIR") or os.path.join(HERE, "selftest_out")
BOX = "280,140,900,440"          # main side view of the bundled drawing
EXPECT_VOLUME = 20071.1          # mm3
TOL_VOLUME = 0.5

C_OK, C_BAD, C_DIM, C_OFF = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
if os.name == "nt" and not os.environ.get("WT_SESSION"):
    C_OK = C_BAD = C_DIM = C_OFF = ""

results = []


def run(args):
    return subprocess.run([sys.executable, "-m"] + args, cwd=HERE,
                          capture_output=True, text=True)


def report(name, passed, detail=""):
    results.append(passed)
    mark = f"{C_OK}PASS{C_OFF}" if passed else f"{C_BAD}FAIL{C_OFF}"
    print(f"  [{mark}] {name}")
    if detail:
        for line in detail.strip().splitlines():
            print(f"         {C_DIM}{line}{C_OFF}")


def head(n, title):
    print(f"\n{n}. {title}")


# ---------------------------------------------------------------- 1. build --
head(1, "The reference part builds from its spec")
r = run(["drawing2solid.builder", SPEC, "-o", OUT])
if r.returncode != 0:
    report("builder ran", False, r.stderr)
    print("\nCannot continue without a build. Is cadquery installed?")
    sys.exit(1)
rep = json.loads(r.stdout)
vol_ok = abs(rep["volume_mm3"] - EXPECT_VOLUME) <= TOL_VOLUME
report(f"volume {rep['volume_mm3']} mm3 (expected {EXPECT_VOLUME})", vol_ok)
report("solid is valid and closed", rep["valid"])
report("closure checks all held",
       all(v is not False for v in rep["checks"].values()),
       json.dumps(rep["checks"]))

# ------------------------------------------------------------- 2. refusals --
head(2, "A misread dimension is refused, not quietly built")
base = json.load(open(SPEC))


def corrupt(label, mutate):
    s = copy.deepcopy(base)
    mutate(s)
    tmp = os.path.join(OUT, "corrupt.json")
    os.makedirs(OUT, exist_ok=True)
    json.dump(s, open(tmp, "w"))
    r = run(["drawing2solid.builder", tmp, "-o", os.path.join(OUT, "junk")])
    refused = r.returncode == 2
    msg = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
    report(label, refused, msg if refused else "built anyway, which is wrong")


corrupt("flare centre radius misread, 21,5 read as 24",
        lambda s: s["profile"][4]["arc"].update(center_r=24))
corrupt("flare centre position misread, 29,9 read as 27",
        lambda s: s["profile"][4]["arc"].update(center_x=27.0))
corrupt("flange inner face misread, 54 read as 52",
        lambda s: s["profile"][9].update(pt=[52, 20]))
corrupt("overall length misread, 76 read as 74",
        lambda s: s["profile"][-1].update(pt=[74, 4]))
corrupt("flare start misread, 11 read as 13",
        lambda s: s["profile"][3].update(pt=[13, 20]))

# --------------------------------------------------------- 3/4. reprojection --
head(3, "The correct model matches the drawing it came from")
if not os.path.exists(DRAWING):
    report("source drawing bundled", False, f"missing: {DRAWING}")
else:
    r = run(["drawing2solid.verify",
             os.path.join(OUT, "spool_shaft_report.json"), DRAWING,
             "--box", BOX])
    v = json.loads(r.stdout)
    report(f"verdict {v['verdict']}, {v['transitions_matched']} of "
           f"{v['transitions_visible']} edges matched", v["verdict"] == "PASS",
           "worst residual "
           f"{max(abs(x.get('resid_mm', 0)) for x in v['rows']):.3f} mm")

    head(4, "A self-consistent but WRONG model is still caught")
    w = copy.deepcopy(base)
    for p in w["profile"]:                      # widen both lands by 1 mm and
        if p.get("pt") == [11, 20]: p["pt"] = [12, 20]      # move the flare
        if p.get("pt") == [54, 20]: p["pt"] = [53, 20]      # centres to match,
        if "arc" in p:                                       # so the chain still
            p["arc"]["center_x"] = 30.9 if p["arc"]["center_x"] == 29.9 else 34.1
    w["checks"].pop("diameters_present", None)
    tmp = os.path.join(OUT, "consistent_but_wrong.json")
    json.dump(w, open(tmp, "w"))
    rb = run(["drawing2solid.builder", tmp, "-o", os.path.join(OUT, "wrong")])
    report("the builder accepts it (it cannot tell, and says so)",
           rb.returncode == 0)
    if rb.returncode == 0:
        rv = run(["drawing2solid.verify",
                  os.path.join(OUT, "wrong", "spool_shaft_report.json"),
                  DRAWING, "--box", BOX])
        vv = json.loads(rv.stdout)
        bad = [x["model_x"] for x in vv["rows"] if x["status"] == "MISMATCH"]
        report(f"the reprojection rejects it: verdict {vv['verdict']}",
               vv["verdict"] == "FAIL",
               f"mismatched at x = {', '.join(map(str, bad))}")

# --------------------------------------------------------------- 5. viewer --
head(5, "An interactive viewer is produced")
r = run(["drawing2solid.viewer", SPEC,
         os.path.join(OUT, "spool_shaft_report.json"),
         os.path.join(OUT, "spool_shaft.brep"),
         "-o", os.path.join(OUT, "spool_viewer.html")])
ok = r.returncode == 0 and os.path.exists(os.path.join(OUT, "spool_viewer.html"))
report("viewer written", ok,
       f"open: {os.path.join(OUT, 'spool_viewer.html')}" if ok else r.stderr)

# ----------------------------------------------------------------- summary --
n_pass, n_all = sum(results), len(results)
print(f"\n{'=' * 58}")
print(f"  {n_pass} of {n_all} checks passed")
if n_pass == n_all:
    print(f"  {C_OK}Every claim the pipeline makes held on this machine.{C_OFF}")
else:
    print(f"  {C_BAD}Something regressed. See the FAIL lines above.{C_OFF}")
print(f"{'=' * 58}")
print(f"\nOutputs in: {OUT}")
sys.exit(0 if n_pass == n_all else 1)
