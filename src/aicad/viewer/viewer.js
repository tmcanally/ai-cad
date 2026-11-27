// AI CAD viewer: renders a design's parts, explodes them, and animates joint motions.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);

// ---------- three.js scene (CAD convention: millimetres, Z up) ----------
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
const canvas = $("canvas");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setClearColor(0x000000, 0); // let the CSS background (light/dark) show through
renderer.setPixelRatio(window.devicePixelRatio);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100000);
camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(1, -1.5, 2);
scene.add(sun);
const fill = new THREE.DirectionalLight(0xffffff, 0.5);
fill.position.set(-1.5, 1, 0.5);
scene.add(fill);

const grid = new THREE.GridHelper(1, 20, 0x8a96a3, 0xb9c1ca);
grid.rotation.x = Math.PI / 2; // GridHelper is XZ; CAD floor is XY
grid.material.transparent = true;
grid.material.opacity = 0.5;
scene.add(grid);

const root = new THREE.Group();
scene.add(root);

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);

// ---------- state ----------
let designs = [];
let current = null; // { name, data, params }
let partObjects = new Map(); // part name -> { group, explode: Vector3 }
let motionValues = new Map(); // motion name -> degrees
let explode = 0;
let lastStateVersion = null;
let playing = false;
let playStart = 0;

function setStatus(text, isError = false) {
  const el = $("status");
  el.textContent = text || "";
  el.classList.toggle("show", !!text);
  el.classList.toggle("error", isError);
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

async function sendJSON(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function paramsQuery(params) {
  return params && Object.keys(params).length ? `?params=${encodeURIComponent(JSON.stringify(params))}` : "";
}

// ---------- building three.js objects from the API payload ----------
function makePart(p) {
  const group = new THREE.Group();
  group.matrixAutoUpdate = false;
  group.name = p.name;

  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(p.mesh.positions, 3));
  geom.setIndex(p.mesh.indices);
  geom.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({
    color: p.color, roughness: 0.55, metalness: 0.05,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, side: THREE.DoubleSide,
  });
  group.add(new THREE.Mesh(geom, mat));

  const seg = [];
  for (const line of p.edges) {
    for (let i = 0; i + 5 < line.length; i += 3) {
      seg.push(line[i], line[i + 1], line[i + 2], line[i + 3], line[i + 4], line[i + 5]);
    }
  }
  const eg = new THREE.BufferGeometry();
  eg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
  group.add(new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: 0x1b2026, transparent: true, opacity: 0.55 })));
  return group;
}

function clearScene() {
  for (const { group } of partObjects.values()) {
    group.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
    root.remove(group);
  }
  partObjects = new Map();
}

function fitCamera(bbox, keepView) {
  const min = new THREE.Vector3(...bbox.min), max = new THREE.Vector3(...bbox.max);
  const center = min.clone().add(max).multiplyScalar(0.5);
  const size = max.clone().sub(min).length();
  center.z += size * 0.1; // leave headroom for lids and arms that swing up
  grid.scale.setScalar(Math.ceil((size * 2) / 10) * 10);
  grid.position.set(center.x, center.y, min.z);
  if (keepView) return;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(1.1, -1.6, 1.0).normalize().multiplyScalar(size * 2.3));
  camera.near = size / 100; camera.far = size * 100;
  camera.updateProjectionMatrix();
}

// ---------- transforms: motion (joint rotation) then explode offset ----------
function updateTransforms() {
  if (!current) return;
  for (const [name, obj] of partObjects) {
    const m = new THREE.Matrix4();
    for (const motion of current.data.motions) {
      if (!motion.parts.includes(name)) continue;
      const value = motionValues.get(motion.name) ?? motion.range[0];
      const axis = new THREE.Vector3(...motion.direction).normalize();
      if (motion.kind === "revolute") {
        const o = new THREE.Vector3(...motion.origin);
        m.premultiply(new THREE.Matrix4().makeTranslation(o.x, o.y, o.z)
          .multiply(new THREE.Matrix4().makeRotationAxis(axis, THREE.MathUtils.degToRad(value)))
          .multiply(new THREE.Matrix4().makeTranslation(-o.x, -o.y, -o.z)));
      } else if (motion.kind === "linear") {
        const t = axis.multiplyScalar(value);
        m.premultiply(new THREE.Matrix4().makeTranslation(t.x, t.y, t.z));
      }
    }
    const e = obj.explode.clone().multiplyScalar(explode);
    m.premultiply(new THREE.Matrix4().makeTranslation(e.x, e.y, e.z));
    obj.group.matrix.copy(m);
    obj.group.matrixWorldNeedsUpdate = true;
  }
}

// ---------- UI ----------
function renderDesignSelect() {
  const sel = $("design-select");
  sel.innerHTML = "";
  for (const d of designs) {
    const opt = document.createElement("option");
    opt.value = d.name;
    opt.textContent = d.title + (d.builtin ? "" : " (yours)");
    sel.appendChild(opt);
  }
  if (current) sel.value = current.name;
}

function renderPanel() {
  const { data, name, params } = current;
  const info = data.info;
  $("design-select").value = name;
  $("design-desc").textContent = info.description || "";
  $("notes").textContent = data.notes || "";

  // Motions
  const box = $("motions");
  box.innerHTML = "";
  $("motions-section").style.display = data.motions.length ? "" : "none";
  for (const m of data.motions) {
    const wrap = document.createElement("div");
    wrap.className = "motion";
    const [lo, hi] = m.range;
    const v = motionValue(m);
    const step = m.kind === "revolute" ? 0.5 : Math.max((hi - lo) / 400, 0.1);
    wrap.innerHTML = `<div class="motion-name">${m.name.replace(/_/g, " ")}</div>
      <div class="slider-row"><input type="range" min="${lo}" max="${hi}" step="${step}" value="${v}" aria-label="${m.name}">
      <output></output></div>`;
    const input = wrap.querySelector("input"), out = wrap.querySelector("output");
    m._input = input; m._out = out;
    showMotionValue(m, v);
    input.addEventListener("input", () => {
      stopPlay();
      showMotionValue(m, +input.value);
      if (m.kind === "param") return previewParamMotion(m, +input.value);
      motionValues.set(m.name, +input.value);
      updateTransforms();
    });
    box.appendChild(wrap);
  }

  // Parts
  const ul = $("parts");
  ul.innerHTML = "";
  const q = paramsQuery(params);
  for (const p of data.parts) {
    const li = document.createElement("li");
    const sep = q ? "&" : "?";
    li.innerHTML = `<input type="checkbox" checked aria-label="Show ${p.name}">
      <span class="swatch" style="background:${p.color}"></span>
      <span class="pname">${p.name}<span class="mat">${p.material || ""}</span></span>
      <a href="/api/designs/${name}/stl${q}${sep}part=${encodeURIComponent(p.name)}" download>STL</a>`;
    li.querySelector("input").addEventListener("change", (ev) => {
      partObjects.get(p.name).group.visible = ev.target.checked;
    });
    ul.appendChild(li);
  }
  $("download-all").href = `/api/designs/${name}/stl${q}`;

  // Parameters
  const form = $("params");
  form.innerHTML = "";
  const driven = new Set(data.motions.filter((m) => m.param).map((m) => m.param));
  for (const [key, spec] of Object.entries(info.params)) {
    if (driven.has(key)) continue; // shown as a Motion slider instead
    const label = document.createElement("label");
    label.innerHTML = `<span class="ptitle"><span>${spec.description || key}</span><span class="unit">${spec.unit}</span></span>`;
    const input = document.createElement("input");
    input.type = "number";
    input.name = key;
    input.step = "any";
    if (spec.min != null) input.min = spec.min;
    if (spec.max != null) input.max = spec.max;
    input.value = params[key] ?? spec.default;
    label.appendChild(input);
    form.appendChild(label);
  }
  $("params-section").style.display = Object.keys(info.params).length ? "" : "none";
  markUnsaved();
  renderHistory();
}

// ---------- saved values and history ----------
function formParams() {
  const params = { ...current.params };
  for (const input of $("params").querySelectorAll("input")) params[input.name] = +input.value;
  return params;
}

function markUnsaved() {
  if (!current) return;
  const saved = current.data.saved_params || {};
  let dirty = false;
  for (const input of $("params").querySelectorAll("input")) {
    const changed = saved[input.name] !== undefined && +input.value !== saved[input.name];
    input.classList.toggle("changed", changed);
    dirty ||= changed;
  }
  $("unsaved").hidden = !dirty;
  $("save-params").disabled = !dirty;
  $("revert-params").disabled = !dirty;
}

let showAllVersions = false;
async function renderHistory() {
  if (!current) return;
  const name = current.name;
  let versions = [];
  try { versions = await fetchJSON(`/api/designs/${encodeURIComponent(name)}/versions`); } catch {}
  if (!current || current.name !== name) return;
  const ol = $("versions");
  ol.innerHTML = "";
  const shown = showAllVersions ? versions : versions.slice(0, 6);
  shown.forEach((v, i) => {
    const li = document.createElement("li");
    const when = new Date(v.time.replace(/([+-]\d\d)(\d\d)$/, "$1:$2"));
    const time = isNaN(when) ? v.time : when.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    li.innerHTML = `<span class="vnum">v${v.version}</span>
      <span class="vnote"></span>
      ${i === 0 ? '<span class="current">current</span>' : '<button class="ghost">Restore</button>'}`;
    const note = li.querySelector(".vnote");
    note.textContent = v.note || "(no note)";
    const t = document.createElement("span");
    t.className = "vtime";
    t.textContent = time;
    note.appendChild(t);
    li.querySelector("button")?.addEventListener("click", () => historyAction("POST", `restore/${v.version}`, `Restoring v${v.version}…`));
    ol.appendChild(li);
  });
  $("more-versions").hidden = showAllVersions || versions.length <= 6;
  $("undo").disabled = versions.length < 2 || (versions[0].restored_from ?? versions[0].version) <= 1;
}

async function historyAction(method, path, message, body) {
  if (!current) return;
  setStatus(message);
  try {
    const res = await sendJSON(method, `/api/designs/${encodeURIComponent(current.name)}/${path}`, body);
    lastStateVersion = res.state_version; // our own change; don't reload twice via Follow
    await loadDesign(current.name, {}, { keepView: true });
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function loadDesign(name, params = {}, { keepView = false } = {}) {
  setStatus(`Building ${name}…`);
  try {
    const data = await fetchJSON(`/api/designs/${encodeURIComponent(name)}${paramsQuery(params)}`);
    const sameDesign = current && current.name === name;
    clearScene();
    current = { name, data, params: data.params };
    if (!sameDesign) motionValues = new Map();
    for (const p of data.parts) {
      const group = makePart(p);
      root.add(group);
      partObjects.set(p.name, { group, explode: new THREE.Vector3(...p.explode) });
    }
    fitCamera(data.bbox, keepView && sameDesign);
    renderPanel();
    updateTransforms();
    const url = new URL(location.href);
    url.searchParams.set("design", name);
    history.replaceState(null, "", url);
    setStatus("");
  } catch (err) {
    setStatus(`Could not build ${name}:\n${err.message}`, true);
  }
}

// ---------- motions that rebuild the design (kind "param") ----------
function motionValue(m) {
  if (m.kind === "param") return current.params[m.param] ?? m.range[0];
  return motionValues.get(m.name) ?? m.range[0];
}

function showMotionValue(m, v) {
  m._input.value = v;
  m._out.textContent = m.kind === "revolute" ? `${Math.round(v)}°` : `${Math.round(v)} ${m.unit || "mm"}`;
}

const frameCache = new Map(); // JSON(params) -> payload
async function fetchFrame(params) {
  const key = current.name + JSON.stringify(Object.entries(params).sort());
  if (!frameCache.has(key)) {
    if (frameCache.size > 400) frameCache.clear();
    frameCache.set(key, await fetchJSON(`/api/designs/${encodeURIComponent(current.name)}${paramsQuery(params)}`));
  }
  return frameCache.get(key);
}

// Swap in new geometry without rebuilding the panel, so a slider keeps working while it rebuilds.
function showFrame(data) {
  const hidden = new Set([...partObjects].filter(([, o]) => !o.group.visible).map(([n]) => n));
  clearScene();
  current.data = { ...data, info: current.data.info, motions: current.data.motions }; // keep the slider wiring
  current.params = data.params;
  for (const p of data.parts) {
    const group = makePart(p);
    group.visible = !hidden.has(p.name);
    root.add(group);
    partObjects.set(p.name, { group, explode: new THREE.Vector3(...p.explode) });
  }
  updateTransforms();
  $("notes").textContent = data.notes || "";
}

let pendingParamMotion = null, paramMotionBusy = false;
async function previewParamMotion(m, value) {
  pendingParamMotion = { ...current.params, [m.param]: value };
  if (paramMotionBusy) return; // the newest value is picked up when the current build finishes
  paramMotionBusy = true;
  try {
    while (pendingParamMotion) {
      const params = pendingParamMotion;
      pendingParamMotion = null;
      showFrame(await fetchFrame(params));
    }
    markUnsaved();
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    paramMotionBusy = false;
  }
}

// Explode slider
$("explode").addEventListener("input", (ev) => {
  explode = +ev.target.value;
  $("explode-out").textContent = `${Math.round(explode * 100)}%`;
  updateTransforms();
});

// Play: swing every motion through its range and back. Joint motions move
// together; motions that rebuild the design play one after another from
// frames fetched up front.
const PLAY_PERIOD = 3200, FRAME_STEPS = 16;
let playFrames = null; // [{ data, motion, value }] for param motions

function stopPlay() { playing = false; $("play-all").textContent = "▶ Play"; }
$("play-all").addEventListener("click", async () => {
  if (playing) return stopPlay();
  const paramMotions = current.data.motions.filter((m) => m.kind === "param");
  playFrames = null;
  if (paramMotions.length) {
    const base = { ...current.params };
    const plan = [];
    for (const m of paramMotions) {
      const [lo, hi] = m.range;
      const up = Array.from({ length: FRAME_STEPS + 1 }, (_, i) => lo + ((hi - lo) * i) / FRAME_STEPS);
      for (const v of [...up, ...up.slice(0, -1).reverse()]) plan.push({ motion: m, value: v, params: { ...base, [m.param]: v } });
    }
    const unique = [...new Set(plan.map((f) => JSON.stringify(f.params)))];
    try {
      for (let i = 0; i < unique.length; i++) {
        setStatus(`Preparing animation… ${i + 1}/${unique.length}`);
        await fetchFrame(JSON.parse(unique[i]));
      }
      for (const f of plan) f.data = await fetchFrame(f.params);
    } catch (err) {
      return setStatus(err.message, true);
    }
    setStatus("");
    playFrames = plan;
  }
  playing = true;
  playStart = performance.now();
  $("play-all").textContent = "❚❚ Pause";
});

let shownFrame = null;
function stepPlay(now) {
  if (!playing || !current) return;
  const t = (Math.max(0, now - playStart) % PLAY_PERIOD) / PLAY_PERIOD; // 0..1
  const s = 0.5 - 0.5 * Math.cos(t * 2 * Math.PI); // ease in/out, 0→1→0
  for (const m of current.data.motions) {
    if (m.kind === "param") continue;
    const [lo, hi] = m.range;
    const v = lo + (hi - lo) * s;
    motionValues.set(m.name, v);
    if (m._input) showMotionValue(m, v);
  }
  if (playFrames) {
    const fps = 12;
    const frame = playFrames[Math.floor((Math.max(0, now - playStart) / 1000) * fps) % playFrames.length];
    if (frame !== shownFrame) {
      shownFrame = frame;
      showFrame(frame.data);
      for (const pm of current.data.motions) if (pm.kind === "param" && pm._input) showMotionValue(pm, current.params[pm.param]);
    }
  }
  updateTransforms();
}

$("design-select").addEventListener("change", (ev) => loadDesign(ev.target.value));
// Editing a value previews it straight away; "Save values" keeps it.
$("params").addEventListener("submit", (ev) => {
  ev.preventDefault();
  loadDesign(current.name, formParams(), { keepView: true });
});
$("params").addEventListener("input", markUnsaved);
$("params").addEventListener("change", () => loadDesign(current.name, formParams(), { keepView: true }));
$("save-params").addEventListener("click", () => {
  const saved = current.data.saved_params || {};
  const changed = Object.fromEntries(Object.entries(formParams()).filter(([k, v]) => v !== saved[k]));
  historyAction("POST", "params", "Saving…", { params: changed });
});
$("revert-params").addEventListener("click", () => current && loadDesign(current.name, {}, { keepView: true }));
$("undo").addEventListener("click", () => historyAction("POST", "undo", "Undoing…"));
$("more-versions").addEventListener("click", () => { showAllVersions = true; renderHistory(); });

// Follow Claude: reload when the MCP server builds something.
async function pollCurrent() {
  if (!$("follow").checked) return;
  try {
    const st = await fetchJSON("/api/current");
    if (st.version && st.version !== lastStateVersion) {
      const first = lastStateVersion === null;
      lastStateVersion = st.version;
      if (!first) {
        designs = await fetchJSON("/api/designs");
        renderDesignSelect();
        await loadDesign(st.name, st.params, { keepView: current?.name === st.name });
      }
    }
  } catch { /* server restarting; try again next tick */ }
}

function loop(now) {
  stepPlay(now);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}

async function init() {
  resize();
  requestAnimationFrame(loop);
  try {
    designs = await fetchJSON("/api/designs");
  } catch (err) {
    setStatus(`Cannot reach the AI CAD server: ${err.message}`, true);
    return;
  }
  const st = await fetchJSON("/api/current").catch(() => ({}));
  lastStateVersion = st.version ?? 0;
  const wanted = new URL(location.href).searchParams.get("design");
  const start = wanted || st.name || designs[0]?.name;
  renderDesignSelect();
  if (start) await loadDesign(start, !wanted && st.name === start ? st.params : {});
  setInterval(pollCurrent, 1500);
}

window.aicad = {
  loadDesign,
  // For scripted screenshots: camera position and look-at point in mm.
  setView: (position, target) => { camera.position.set(...position); controls.target.set(...target); controls.update(); },
  // Screen position (CSS pixels within the 3D view) of model points, for labelling screenshots.
  project: (points) => {
    controls.update();
    camera.updateMatrixWorld();
    const { clientWidth: w, clientHeight: h } = canvas;
    return points.map((p) => {
      const v = new THREE.Vector3(...p).project(camera);
      return [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * h];
    });
  },
  // Where a part is drawn right now (after explode and motion), so labels can follow it.
  partCenter: (name) => {
    const obj = partObjects.get(name);
    if (!obj) return null;
    const box = new THREE.Box3().setFromObject(obj.group);
    return box.getCenter(new THREE.Vector3()).toArray();
  },
  setExplode: (v) => { $("explode").value = v; $("explode").dispatchEvent(new Event("input")); } };
init();
