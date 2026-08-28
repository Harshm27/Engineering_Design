// Drawing to Solid: in-browser port of drawing2solid.builder's profile solver.
// Same maths, same refusal behaviour, same TOL_SNAP.
'use strict';
const TOL_SNAP = 0.06;

class ChainError extends Error {}

function arcPoints(c, p0, p1, R, n) {
  let a0 = Math.atan2(p0[1]-c[1], p0[0]-c[0]);
  let a1 = Math.atan2(p1[1]-c[1], p1[0]-c[0]);
  if (a1 - a0 >  Math.PI) a1 -= 2*Math.PI;
  if (a0 - a1 >  Math.PI) a1 += 2*Math.PI;
  const pts = [];
  n = n || Math.max(6, Math.ceil(Math.abs(a1-a0)*R*2));
  for (let i = 1; i <= n; i++) {
    const a = a0 + (a1-a0)*i/n;
    pts.push([c[0]+R*Math.cos(a), c[1]+R*Math.sin(a)]);
  }
  return pts;
}
function circleXatR(cx, cy, R, y, side) {
  const d2 = R*R - (cy-y)*(cy-y);
  if (d2 < 0) throw new ChainError(
    `arc R${R} centred at r=${cy} never reaches radius ${y} (short by ${(Math.abs(cy-y)-R).toFixed(3)})`);
  return cx + side*Math.sqrt(d2);
}
function filletArcToLine(cx, cy, R, yLine, rf, side) {
  const fy = yLine + rf, reach = R - rf;
  const d2 = reach*reach - (cy-fy)*(cy-fy);
  if (d2 < 0) throw new ChainError(
    `blend R${rf}: arc R${R} (centre r=${cy}) cannot reach radius ${yLine} (short by ${(Math.abs(cy-fy)-reach).toFixed(3)})`);
  const fx = cx + side*Math.sqrt(d2);
  const ux = (fx-cx)/reach, uy = (fy-cy)/reach;
  return [[fx,fy], [cx+R*ux, cy+R*uy], [fx,yLine]];
}
function checkStated(solved, stated, what) {
  if (stated != null && Math.abs(stated - solved) > TOL_SNAP)
    throw new ChainError(
      `${what}: solved x=${solved.toFixed(3)} but the spec states x=${stated} (residual ${(stated-solved) >= 0 ? '+' : ''}${(stated-solved).toFixed(3)})`);
  return solved;
}

function parseProfile(profile) {
  const verts = [], gaps = [];
  let cur = [];
  for (const it of profile) {
    if ('pt' in it) {
      verts.push({x: it.pt[0], r: it.pt[1], chamfer: it.chamfer, fillet: it.fillet});
      gaps.push(cur); cur = [];
    } else if ('arc' in it)   cur.push(['arc', it.arc]);
    else if ('blend' in it)   cur.push(['blend', it.blend.radius]);
    else throw new ChainError('unknown profile item: ' + JSON.stringify(it));
  }
  if (cur.length) throw new ChainError('profile must end on a pt');
  return [verts, gaps.slice(1)];
}

// -> polyline [[x,r]...] plus solved vertex list (for corner ops)
function solveProfile(profile) {
  const [verts, gaps] = parseProfile(profile);
  if (verts[0].x == null) throw new ChainError('first vertex needs an explicit x');
  let pts = [[verts[0].x, verts[0].r]];
  const vidx = [0];                       // polyline index of each spec vertex

  for (let i = 0; i < gaps.length; i++) {
    const gap = gaps[i], A = verts[i], B = verts[i+1];
    const pa = [A.x, A.r];

    if (!gap.length) {
      if (B.x == null) throw new ChainError(`vertex ${i+1}: null x with no arc/blend to solve it`);
      if (B.x < pa[0]-1e-9 && Math.abs(B.r-pa[1]) > 1e-9)
        throw new ChainError(`profile x goes backwards into (${B.x},${B.r})`);
      pts.push([B.x, B.r]);
    }
    else if (gap.length === 1 && gap[0][0] === 'arc') {
      const a = gap[0][1], R = a.radius, cy = a.center_r;
      const anchored = Math.abs(Math.hypot(pa[0]-a.center_x, pa[1]-cy) - R) <= TOL_SNAP;
      const anchor = anchored ? pa : [B.x, B.r];
      if (anchor[0] == null) throw new ChainError('arc anchored on a null-x vertex');
      const dx = Math.sqrt(Math.max(R*R - (cy-anchor[1])*(cy-anchor[1]), 0));
      const cx = a.center_x >= anchor[0] ? anchor[0]+dx : anchor[0]-dx;
      checkStated(cx, a.center_x, `arc R${R} centre location`);
      const dPrev = Math.hypot(pa[0]-cx, pa[1]-cy);
      if (Math.abs(dPrev-R) > TOL_SNAP)
        throw new ChainError(`arc R${R}: previous vertex (${pa}) is ${(dPrev-R).toFixed(3)} off the arc`);
      const side = (B.x == null || B.x >= cx) ? 1 : -1;
      const xb = circleXatR(cx, cy, R, B.r, side);
      B.x = checkStated(xb, B.x, `arc R${R} onto r=${B.r}`);
      pts = pts.concat(arcPoints([cx,cy], pa, [B.x,B.r], R));
    }
    else if (gap.length === 2 && gap[0][0] === 'arc' && gap[1][0] === 'blend') {
      const a = gap[0][1], rf = gap[1][1], R = a.radius, cy = a.center_r;
      const dx = Math.sqrt(Math.max(R*R - (cy-pa[1])*(cy-pa[1]), 0));
      const cx = a.center_x >= pa[0] ? pa[0]+dx : pa[0]-dx;
      checkStated(cx, a.center_x, `arc R${R} centre location`);
      const side = cx > pa[0] ? -1 : 1;
      const [fc, tArc, tLine] = filletArcToLine(cx, cy, R, B.r, rf, side);
      pts = pts.concat(arcPoints([cx,cy], pa, tArc, R));
      pts = pts.concat(arcPoints(fc, tArc, tLine, rf));
      B.x = checkStated(tLine[0], B.x, `blend R${rf} onto r=${B.r}`);
    }
    else if (gap.length === 2 && gap[0][0] === 'blend' && gap[1][0] === 'arc') {
      const rf = gap[0][1], a = gap[1][1], R = a.radius, cy = a.center_r;
      if (B.x == null) throw new ChainError('blend+arc: far vertex needs explicit x');
      const pb = [B.x, B.r];
      const dx = Math.sqrt(Math.max(R*R - (cy-pb[1])*(cy-pb[1]), 0));
      const cx = a.center_x >= pb[0] ? pb[0]+dx : pb[0]-dx;
      checkStated(cx, a.center_x, `arc R${R} centre location`);
      const side = cx < pb[0] ? 1 : -1;
      const [fc, tArc, tLine] = filletArcToLine(cx, cy, R, pa[1], rf, side);
      if (tLine[0] < pa[0]-1e-6)
        throw new ChainError(`blend R${rf} would start at x=${tLine[0].toFixed(3)}, before the current vertex (${pa})`);
      pts.push(tLine);
      pts = pts.concat(arcPoints(fc, tLine, tArc, rf));
      pts = pts.concat(arcPoints([cx,cy], tArc, pb, R));
    }
    else throw new ChainError('unsupported connector sequence');
    vidx.push(pts.length - 1);
  }
  return {pts, verts, vidx};
}

// corner chamfers/fillets, purely visual
function applyCorners(pts, verts, vidx) {
  const out = pts.map(p => p.slice());
  // process from the end so indices stay valid
  for (let k = verts.length-1; k >= 0; k--) {
    const v = verts[k], c = v.chamfer, f = v.fillet;
    if (!c && !f) continue;
    const i = vidx[k];
    if (i <= 0 || i >= out.length-1) {
      // end-of-part chamfer: pull the endpoint in along its one neighbour
      if (c && i === out.length-1) {
        const P = out[i], Q = out[i-1];
        const d = Math.hypot(P[0]-Q[0], P[1]-Q[1]);
        if (d > c) out.splice(i, 0, [P[0]+(Q[0]-P[0])*c/d, P[1]+(Q[1]-P[1])*c/d]);
      } else if (c && i === 0) {
        const P = out[0], Q = out[1];
        const d = Math.hypot(P[0]-Q[0], P[1]-Q[1]);
        if (d > c) out.splice(1, 0, [P[0]+(Q[0]-P[0])*c/d, P[1]+(Q[1]-P[1])*c/d]);
      }
      continue;
    }
    const P = out[i], A = out[i-1], B = out[i+1];
    const dA = Math.hypot(P[0]-A[0], P[1]-A[1]), dB = Math.hypot(P[0]-B[0], P[1]-B[1]);
    const size = c || f;
    if (dA < size*1.05 || dB < size*1.05) continue;      // no room, skip (visual only)
    const uA = [(A[0]-P[0])/dA, (A[1]-P[1])/dA], uB = [(B[0]-P[0])/dB, (B[1]-P[1])/dB];
    if (c) {
      out.splice(i, 1, [P[0]+uA[0]*c, P[1]+uA[1]*c], [P[0]+uB[0]*c, P[1]+uB[1]*c]);
    } else {
      const cosT = uA[0]*uB[0] + uA[1]*uB[1];
      const theta = Math.acos(Math.max(-1, Math.min(1, cosT)));
      const t = f / Math.tan(theta/2);
      if (dA < t || dB < t) continue;
      const p1 = [P[0]+uA[0]*t, P[1]+uA[1]*t], p2 = [P[0]+uB[0]*t, P[1]+uB[1]*t];
      // sample the fillet arc as a quadratic-ish through the corner region
      const seg = [];
      for (let s = 1; s < 6; s++) {
        const u = s/6;
        const q = [
          (1-u)*(1-u)*p1[0] + 2*(1-u)*u*P[0] + u*u*p2[0],
          (1-u)*(1-u)*p1[1] + 2*(1-u)*u*P[1] + u*u*p2[1]];
        seg.push(q);
      }
      out.splice(i, 1, p1, ...seg, p2);
    }
  }
  return out;
}

function runChecks(pts, checks) {
  const results = [];
  const xs = pts.map(p => p[0]), rs = pts.map(p => p[1]);
  const L = Math.max(...xs) - Math.min(...xs);
  const D = 2*Math.max(...rs);
  if (checks && checks.overall_length) {
    const want = checks.overall_length.value, tol = checks.overall_length.tol ?? 0.1;
    const ok = Math.abs(L-want) <= tol + 1e-9;
    results.push({name: 'overall length', got: L.toFixed(3), want: `${want} ±${tol}`, ok});
  }
  if (checks && checks.max_diameter) {
    const want = checks.max_diameter.value, tol = checks.max_diameter.tol ?? 0.05;
    const ok = Math.abs(D-want) <= tol + 1e-9;
    results.push({name: 'max diameter', got: D.toFixed(3), want: `${want} ±${tol}`, ok});
  }
  const fails = results.filter(r => !r.ok);
  if (fails.length)
    throw new ChainError('closure checks FAILED: ' +
      fails.map(f => `${f.name} ${f.got} != ${f.want}`).join('; '));
  return results;
}

// Pappus: volume of the revolved closed profile (before holes)
function revolvedVolume(pts) {
  const poly = pts.concat([[pts[pts.length-1][0], 0], [pts[0][0], 0]]);
  let A = 0, Sy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x0,y0] = poly[i], [x1,y1] = poly[(i+1)%poly.length];
    const cr = x0*y1 - x1*y0;
    A  += cr;
    Sy += (y0+y1)*cr;
  }
  A /= 2; const yc = Sy/(6*A);
  return Math.abs(2*Math.PI*yc*A);
}

if (typeof module !== 'undefined') module.exports =
  {solveProfile, applyCorners, runChecks, revolvedVolume, ChainError};
