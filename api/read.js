// Drawing to Solid: the AI reading step as a Vercel function.
//
// POST /api/read  {password, media_type, image (base64, no data: prefix)}
//   -> 200 {spec, attempt}                     the reading closed arithmetically
//   -> 200 {error: {type, message}}            scope | refused | auth | upstream
//
// The drawing goes to the Claude API with the reading rules; the returned spec
// is dry-run through the same profile solver the page uses. A spec that does
// not close is sent back to the model once for a corrected reading; if the
// second attempt still fails, the residual is returned instead of a wrong part.
//
// Environment: ANTHROPIC_API_KEY (required), APP_PASSWORD (recommended),
// READER_MODEL (optional, default claude-sonnet-4-5).
'use strict';
const {solveProfile, runChecks} = require('./_solver.js');

const RULES = `You are reading a dimensioned 2D mechanical engineering drawing of a TURNED
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
   Record centre coordinates; the checker solves the tangencies and will refuse
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
   {"arc": {"radius": <R>, "center_r": <centre radius>, "center_x": <centre x>}},
   {"blend": {"radius": <fillet R tangent to both neighbours>}},
   {"pt": [null, <r>]}
 ],
 "features": [
   {"type": "hole_axial", "end": "left", "d": 3.3, "depth": 12, "tip_angle": 118,
    "mouth_chamfer": 0.5, "thread": "M4", "thread_depth": 8},
   {"type": "hole_pattern_axial", "ends": ["left","right"], "n": 4, "d": 3,
    "pcd": 30, "depth": 14},
   {"type": "undercut_din509", "form": "E", "at_x": 69, "into": "right",
    "width": 2, "depth": 0.2, "radius": 0.4, "angle_deg": 15, "shaft_r": 4}
 ],
 "checks": {
   "overall_length": {"value": <stated overall>, "tol": <its tolerance or 0.1>},
   "max_diameter":   {"value": <largest stated dia>, "tol": 0.05},
   "diameters_present": [<each stated cylindrical dia>]
 }
}

The profile lists pt vertices ordered from the left face (x=0) to the right
face; an arc/blend entry sits BETWEEN the two pt vertices it connects.

Or, when the drawing is not a turned part or is unreadable:

{"error": "<one sentence saying what it is and why it is out of scope>"}`;

function extractJson(text) {
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error('the model returned no JSON');
  return JSON.parse(m[0]);
}

function dryRun(spec) {                 // throws on a spec that does not close
  const {pts} = solveProfile(spec.profile);
  runChecks(pts, spec.checks);
}

async function callModel(apiKey, model, messages, fetchImpl) {
  const r = await fetchImpl('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {'content-type': 'application/json', 'x-api-key': apiKey,
              'anthropic-version': '2023-06-01'},
    body: JSON.stringify({model, max_tokens: 4000, system: RULES, messages}),
  });
  const data = await r.json();
  if (!r.ok) {
    const msg = (data && data.error && data.error.message) || `HTTP ${r.status}`;
    const type = r.status === 401 ? 'auth_upstream' : 'upstream';
    const e = new Error(msg); e.kind = type; throw e;
  }
  return data.content.filter(b => b.type === 'text').map(b => b.text).join('');
}

async function readDrawing(imageB64, mediaType, env, fetchImpl) {
  const messages = [{role: 'user', content: [
    {type: 'image', source: {type: 'base64', media_type: mediaType, data: imageB64}},
    {type: 'text', text: 'Read this drawing into a spec.'},
  ]}];
  const model = env.READER_MODEL || 'claude-sonnet-4-5';
  let lastResidual = null;
  for (let attempt = 1; attempt <= 2; attempt++) {
    const text = await callModel(env.ANTHROPIC_API_KEY, model, messages, fetchImpl);
    const spec = extractJson(text);
    if (spec.error) return {error: {type: 'scope', message: spec.error}};
    try { dryRun(spec); return {spec, attempt}; }
    catch (e) {
      lastResidual = e.message;
      messages.push({role: 'assistant', content: text});
      messages.push({role: 'user', content:
        'Your reading does not close arithmetically. The checker refused with:\n\n' +
        e.message + '\n\nRe-examine the drawing, correct the misread dimension, ' +
        'and return the full corrected JSON only.'});
    }
  }
  return {error: {type: 'refused', message: lastResidual}};
}

async function handler(req, res, env, fetchImpl) {
  env = env || process.env;
  fetchImpl = fetchImpl || fetch;
  const send = (code, obj) => { res.statusCode = code;
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(obj)); };

  if (req.method !== 'POST') return send(405, {error: {type: 'method', message: 'POST only'}});
  let body = req.body;
  if (!body || typeof body === 'string') {
    try { body = JSON.parse(body || await readStream(req)); }
    catch { return send(400, {error: {type: 'bad_request', message: 'JSON body expected'}}); }
  }
  if (env.APP_PASSWORD && body.password !== env.APP_PASSWORD)
    return send(401, {error: {type: 'auth', message: 'wrong or missing password'}});
  if (!env.ANTHROPIC_API_KEY)
    return send(500, {error: {type: 'config', message: 'ANTHROPIC_API_KEY is not set on the server'}});
  const mt = ['image/png', 'image/jpeg', 'image/webp'].includes(body.media_type)
    ? body.media_type : 'image/png';
  if (!body.image || body.image.length > 6_000_000)
    return send(400, {error: {type: 'bad_request', message: 'image missing or over ~4.5 MB'}});
  try {
    return send(200, await readDrawing(body.image, mt, env, fetchImpl));
  } catch (e) {
    return send(200, {error: {type: e.kind || 'upstream', message: String(e.message).slice(0, 400)}});
  }
}

function readStream(req) {
  return new Promise((resolve, reject) => {
    let d = ''; req.on('data', c => d += c);
    req.on('end', () => resolve(d)); req.on('error', reject);
  });
}

module.exports = handler;
module.exports.readDrawing = readDrawing;   // for tests
