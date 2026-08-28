"""
Drawing to Solid: web front end.

Serves the pipeline over HTTP so nobody has to install anything: paste or upload
a spec, optionally attach the source drawing, and get back the STEP, the STL,
the verification residuals and an interactive viewer.

    python -m uvicorn webapp:app --host 0.0.0.0 --port 8000

or, in the container:

    docker run --rm -p 8000:8000 drawing-to-solid:1.0 serve

Access control: set AUTH_USER and AUTH_PASS and every route requires HTTP basic
auth. Leave them unset and the app runs open, printing a warning; that is only
appropriate on a machine nobody else can reach.

PROTOTYPE. Basic auth only, no rate limiting, no sandboxing of uploads. Fine for
a handful of named colleagues over HTTPS; not hardened for the open internet.
"""

import base64
import binascii
import json
import os
import secrets
import shutil
import sys
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, Response

from drawing2solid import builder, viewer, verify as verifier

HERE = Path(__file__).parent
JOBS = Path(os.environ.get("OUTDIR", HERE / "selftest_out")) / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
EXAMPLE = json.loads((HERE / "examples" / "spool_shaft.json").read_text())
EXAMPLE_DRAWING = HERE / "examples" / "spool_shaft_drawing.png"

app = FastAPI(title="Drawing to Solid")

AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")
OPEN_ROUTES = {"/healthz"}

if AUTH_USER and AUTH_PASS:
    print(f"[auth] basic auth on, user '{AUTH_USER}'", file=sys.stderr)
else:
    print("[auth] WARNING: AUTH_USER/AUTH_PASS not set, every route is open. "
          "Only do this where nobody else can reach the machine.", file=sys.stderr)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """HTTP basic auth on every route when AUTH_USER and AUTH_PASS are set."""
    if not (AUTH_USER and AUTH_PASS) or request.url.path in OPEN_ROUTES:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            user = pw = ""
        # compare_digest on both halves so a wrong username costs the same as a
        # wrong password
        if (secrets.compare_digest(user, AUTH_USER)
                and secrets.compare_digest(pw, AUTH_PASS)):
            return await call_next(request)
    return Response("Authentication required", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Drawing to Solid"'})

CSS = """
:root{--bg:#e9ecef;--page:#fff;--tint:#f3f5f7;--ink:#161a20;--ink-2:#4d5764;
--ink-3:#7d8894;--rule:#ccd3da;--rule-2:#e4e8ec;--accent:#2f5d94;
--accent-soft:#e8eff7;--accent-line:#a3bedb;--judge:#9c6412;--judge-soft:#f7efe0;
--judge-line:#d8ab63;--bad:#a3322260;--bad-ink:#9c3020}
@media(prefers-color-scheme:dark){:root{--bg:#0e1116;--page:#171b21;--tint:#1d222a;
--ink:#e6eaef;--ink-2:#a4aeb9;--ink-3:#727d88;--rule:#2b323b;--rule-2:#232932;
--accent:#7ba7d8;--accent-soft:#152030;--accent-line:#3d5c82;--judge:#e0a44e;
--judge-soft:#2a2114;--judge-line:#7d5d2a;--bad-ink:#e08a7a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.55;
font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:34px 20px 64px;display:flex;
flex-direction:column;gap:22px}
.card{background:var(--page);border:1px solid var(--rule);border-radius:4px;padding:22px 24px}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
letter-spacing:.17em;text-transform:uppercase;color:var(--ink-3);margin-bottom:8px}
h1{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:700;
font-size:30px;margin:0 0 8px;letter-spacing:-.01em}
h2{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;
font-size:18px;margin:0 0 12px;padding-bottom:5px;border-bottom:1px solid var(--rule)}
p{margin:0 0 12px;color:var(--ink-2)}
label{display:block;font-family:"IBM Plex Mono",monospace;font-size:10px;
letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3);margin:0 0 6px}
textarea,input[type=text]{width:100%;font-family:"IBM Plex Mono",monospace;
font-size:12.5px;background:var(--tint);color:var(--ink);border:1px solid var(--rule);
border-radius:3px;padding:11px 13px;line-height:1.6}
textarea{min-height:230px;resize:vertical}
input[type=file]{font-size:13px;color:var(--ink-2)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:18px}
button{font:inherit;font-size:14px;font-weight:500;padding:10px 22px;border:0;
border-radius:3px;background:var(--accent);color:#fff;cursor:pointer}
@media(prefers-color-scheme:dark){button{color:#0e1116}}
button:hover{filter:brightness(1.08)}
.hint{font-size:12.5px;color:var(--ink-3);margin-top:6px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-family:"IBM Plex Mono",monospace;font-size:10px;
letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3);font-weight:400;
padding:0 0 6px;border-bottom:1px solid var(--rule)}
td{padding:6px 0;border-bottom:1px solid var(--rule-2);color:var(--ink-2);
font-variant-numeric:tabular-nums}
td.v{font-family:"IBM Plex Mono",monospace;color:var(--ink);text-align:right}
.pill{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:11px;
padding:2px 9px;border-radius:3px;border:1px solid var(--accent-line);
color:var(--accent);background:var(--accent-soft)}
.pill.bad{border-color:var(--bad);color:var(--bad-ink);background:transparent}
.pill.warn{border-color:var(--judge-line);color:var(--judge);background:var(--judge-soft)}
pre{background:var(--tint);border:1px solid var(--rule-2);border-radius:3px;
padding:13px 15px;overflow-x:auto;font-family:"IBM Plex Mono",monospace;
font-size:12px;color:var(--ink-2);white-space:pre-wrap;margin:0}
a{color:var(--accent)}
.dl{display:flex;flex-wrap:wrap;gap:10px;margin-top:4px}
.dl a{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:12.5px;
padding:7px 14px;border:1px solid var(--rule);border-radius:3px;text-decoration:none;
background:var(--tint)}
.dl a:hover{border-color:var(--accent-line)}
iframe{width:100%;height:560px;border:1px solid var(--rule);border-radius:3px;background:var(--page)}
.note{font-size:12.5px;color:var(--ink-3);border-left:2px solid var(--judge-line);
padding-left:12px}
"""

HEAD = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Drawing to Solid</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style></head><body><div class="wrap">"""
FOOT = "</div></body></html>"


@app.get("/", response_class=HTMLResponse)
def index():
    return HEAD + f"""
  <div>
    <div class="eyebrow">Drawing to Solid &middot; prototype</div>
    <h1>Build a verified solid from a spec</h1>
    <p>The spec is the list of numbers read off a drawing. Everything from here on
    is deterministic: no AI runs on this server.</p>
  </div>

  <form class="card" method="post" action="/build" enctype="multipart/form-data">
    <h2>1. The spec</h2>
    <label for="spec">Spec JSON (the reference part is loaded, edit freely)</label>
    <textarea id="spec" name="spec">{json.dumps(EXAMPLE, indent=1)}</textarea>
    <div class="hint">Try changing a diameter or a length. If your edit makes the
    dimension chain contradict itself, the build refuses and names the number.</div>

    <h2 style="margin-top:26px">2. The drawing, to check against (optional)</h2>
    <div class="row">
      <div>
        <label for="drawing">Source drawing image</label>
        <input type="file" id="drawing" name="drawing" accept="image/*">
        <div class="hint">Leave empty to use the bundled reference drawing.</div>
      </div>
      <div>
        <label for="box">Main side view, pixel box L,T,R,B</label>
        <input type="text" id="box" name="box" value="280,140,900,440">
        <div class="hint">Nothing else about the image is trusted.</div>
      </div>
    </div>

    <div style="margin-top:24px"><button type="submit">Build and verify</button></div>
  </form>

  <div class="card">
    <h2>Or just run the self-test</h2>
    <p>Twelve checks that demonstrate the guarantees rather than assert them,
    including five deliberately misread specs being refused and a
    consistent-but-wrong model being caught.</p>
    <div class="dl"><a href="/selftest">Run the self-test</a></div>
  </div>
""" + FOOT


@app.get("/selftest", response_class=PlainTextResponse)
def selftest():
    import subprocess, sys
    r = subprocess.run([sys.executable, "selftest.py"], cwd=HERE,
                       capture_output=True, text=True, timeout=900)
    body = r.stdout + ("\n" + r.stderr if r.stderr else "")
    import re
    return re.sub(r"\033\[[0-9;]*m", "", body)


@app.post("/build", response_class=HTMLResponse)
async def build(spec: str = Form(...), box: str = Form("280,140,900,440"),
                drawing: UploadFile = File(None)):
    job = JOBS / uuid.uuid4().hex[:12]
    job.mkdir(parents=True, exist_ok=True)
    out = [HEAD, '<div><div class="eyebrow">Drawing to Solid</div><h1>Result</h1></div>']

    try:
        s = json.loads(spec)
    except json.JSONDecodeError as e:
        return HEAD + f'<div class="card"><h2>That is not valid JSON</h2><pre>{e}</pre>' \
                      '<div class="dl"><a href="/">Back</a></div></div>' + FOOT

    # ---- build ----
    try:
        solid, report = builder.build(s, str(job))
    except builder.ChainError as e:
        out.append(
            '<div class="card"><h2>Build refused <span class="pill warn">as designed</span></h2>'
            '<p>The numbers in this spec contradict each other, which is what a '
            'misread drawing looks like arithmetically. Nothing was built.</p>'
            f'<pre>{e}</pre><div class="dl"><a href="/">Back</a></div></div>')
        return "".join(out) + FOOT
    except Exception:
        out.append('<div class="card"><h2>Unexpected error</h2>'
                   f'<pre>{traceback.format_exc()}</pre>'
                   '<div class="dl"><a href="/">Back</a></div></div>')
        return "".join(out) + FOOT

    rows = "".join(
        f'<tr><td>{k.replace("_", " ")}</td><td class="v">{v}</td></tr>'
        for k, v in report["checks"].items())
    out.append(
        '<div class="card"><h2>Built <span class="pill">closure checks held</span></h2>'
        f'<table><tr><th>Check</th><th style="text-align:right">Value</th></tr>{rows}'
        f'<tr><td>volume</td><td class="v">{report["volume_mm3"]} mm&sup3;</td></tr>'
        f'<tr><td>mass</td><td class="v">{report["mass_g"]} g</td></tr>'
        f'<tr><td>B-rep faces</td><td class="v">{report["faces"]}</td></tr></table>'
        + (f'<p class="note" style="margin-top:14px">{" ".join(report["notes"])}</p>'
           if report.get("notes") else "") + '</div>')

    # ---- verify ----
    img = job / "drawing.png"
    if drawing is not None and drawing.filename:
        img.write_bytes(await drawing.read())
        used = drawing.filename
    elif EXAMPLE_DRAWING.exists():
        shutil.copy(EXAMPLE_DRAWING, img)
        used = "bundled reference drawing"
    else:
        img, used = None, None

    if img:
        try:
            b = tuple(int(v) for v in box.split(","))
            v = verifier.verify(report, str(img), b)
            cls = {"PASS": "", "CHECK": " warn", "FAIL": " bad"}[v["verdict"]]
            vr = "".join(
                f'<tr><td>x = {r["model_x"]}</td>'
                f'<td class="v">{r.get("resid_mm", "")}</td>'
                f'<td class="v">{r["status"]}</td></tr>'
                for r in v["rows"] if r["status"] in ("ok", "MISMATCH"))
            out.append(
                f'<div class="card"><h2>Checked against the drawing '
                f'<span class="pill{cls}">{v["verdict"]}</span></h2>'
                f'<p>{v["transitions_matched"]} of {v["transitions_visible"]} '
                f'visible silhouette edges matched, using <em>{used}</em> at '
                f'{v["scale_px_per_unit"]} px/mm.</p>'
                '<table><tr><th>Model feature</th>'
                '<th style="text-align:right">Residual, mm</th>'
                f'<th style="text-align:right">Status</th></tr>{vr}</table></div>')
        except Exception as e:
            out.append('<div class="card"><h2>Could not verify</h2>'
                       f'<pre>{e}</pre><p class="note">The build itself is '
                       'unaffected. Check the pixel box matches the main side '
                       'view of the image you uploaded.</p></div>')

    # ---- viewer + downloads ----
    name = s.get("name", "part")
    try:
        viewer.generate(s, report, str(job / f"{name}.brep"),
                        str(job / "viewer.html"))
        has_viewer = True
    except Exception:
        has_viewer = False

    j = job.name
    links = [f'<a href="/f/{j}/{name}.step">{name}.step</a>',
             f'<a href="/f/{j}/{name}.stl">{name}.stl</a>',
             f'<a href="/f/{j}/{name}_report.json">report.json</a>']
    if has_viewer:
        links.insert(0, f'<a href="/f/{j}/viewer.html" target="_blank">open viewer</a>')
    out.append('<div class="card"><h2>Files</h2><div class="dl">'
               + "".join(links) + '</div></div>')
    if has_viewer:
        out.append(f'<div class="card"><h2>Viewer</h2>'
                   f'<iframe src="/f/{j}/viewer.html" title="3D viewer"></iframe></div>')
    out.append('<div class="card"><div class="dl"><a href="/">Build another</a></div></div>')
    return "".join(out) + FOOT


@app.get("/f/{job}/{fname}")
def fetch(job: str, fname: str):
    # job ids are hex, filenames are resolved inside the job dir only
    p = (JOBS / job / fname).resolve()
    if not str(p).startswith(str(JOBS.resolve())) or not p.is_file():
        return PlainTextResponse("not found", status_code=404)
    media = "text/html" if p.suffix == ".html" else "application/octet-stream"
    return FileResponse(p, media_type=media, filename=None if p.suffix == ".html" else p.name)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
