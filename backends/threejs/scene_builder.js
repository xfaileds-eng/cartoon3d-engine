/**
 * scene_builder.js — dựng cảnh Three.js từ scene_bundle.json và render từng khung theo yêu cầu.
 *
 * Nguyên tắc: không tự tính chuyển động gốc của máy quay hay nhân vật. Track từng khung đã nằm
 * trong bundle (do Python tính, cổng G5 đã kiểm). Ở đây chỉ dựng hình, vật liệu theo phong cách,
 * vung tay chân theo pha bước, và áp thủ pháp nhạy cảm.
 *
 * Giao diện chụp khung (dùng chung với chart-engine): window.capture.ready · .frames · .renderFrame(i) → dataURL PNG
 */
import * as THREE from 'three';

const params = new URLSearchParams(location.search);
const bundleUrl = params.get('bundle');
if (!bundleUrl) throw new Error('thiếu ?bundle=');

const bundle = await (await fetch(bundleUrl)).json();
const { render: R, style, set, characters, props, sensitivity, tracks, shot } = bundle;
const device = sensitivity.device;
const devSpec = sensitivity.spec || {};

// ---------------------------------------------------------------- renderer
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({
  canvas, antialias: !!style.renderer.antialias, preserveDrawingBuffer: true, alpha: false,
});
renderer.setPixelRatio(1);
renderer.setSize(R.width, R.height, false);
renderer.shadowMap.enabled = (style.lights || []).some(l => l.shadow);
renderer.shadowMap.type = THREE.PCFShadowMap;

const scene = new THREE.Scene();
const bg = devSpec.background_override === 'diagram'
  ? (style.sensitivity?.diagram_background || '#101420') : style.renderer.background;
scene.background = new THREE.Color(bg);

const dim = devSpec.dim ? Number(devSpec.dim) : 1.0;
for (const l of style.lights || []) {
  let light;
  if (l.type === 'hemisphere') {
    light = new THREE.HemisphereLight(new THREE.Color(l.sky), new THREE.Color(l.ground), l.intensity * dim);
  } else if (l.type === 'directional') {
    light = new THREE.DirectionalLight(new THREE.Color(l.color), l.intensity * dim);
    light.position.set(...l.position);
    if (l.shadow) {
      light.castShadow = true;
      light.shadow.mapSize.set(2048, 2048);
      const s = 14;
      Object.assign(light.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 0.5, far: 60 });
      light.shadow.bias = -0.0005;
    }
  } else if (l.type === 'ambient') {
    light = new THREE.AmbientLight(new THREE.Color(l.color), l.intensity * dim);
  }
  if (light) scene.add(light);
}

// ---------------------------------------------------------------- materials
let gradientMap = null;
function makeGradientMap(steps) {
  const data = new Uint8Array(steps);
  for (let i = 0; i < steps; i++) data[i] = Math.round((i / (steps - 1)) * 255);
  const tex = new THREE.DataTexture(data, steps, 1, THREE.RedFormat, THREE.UnsignedByteType);
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.needsUpdate = true;
  return tex;
}

function makeMaterial(colorHex, opts = {}) {
  const color = new THREE.Color(colorHex);
  const m = style.material || {};
  let mat;
  if (opts.override === 'silhouette') {
    mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(style.sensitivity?.silhouette_color || '#000000') });
  } else if (m.type === 'toon') {
    gradientMap ||= makeGradientMap(m.gradient_steps || 4);
    mat = new THREE.MeshToonMaterial({ color, gradientMap });
  } else {
    mat = new THREE.MeshLambertMaterial({ color, flatShading: true });
  }
  if (opts.emissive && 'emissive' in mat) {
    mat.emissive = new THREE.Color(opts.emissive);
    mat.emissiveIntensity = 0.9;
  }
  return mat;
}

const outlineCfg = style.material?.outline || { enabled: false };
const outlineMat = outlineCfg.enabled
  ? new THREE.MeshBasicMaterial({ color: new THREE.Color(outlineCfg.color || '#000'), side: THREE.BackSide })
  : null;

/** Viền kiểu "inverted hull": bản sao phóng to, vẽ mặt sau. Ổn với khối lồi đơn giản. */
function addOutline(mesh, geometry) {
  if (!outlineMat) return;
  geometry.computeBoundingSphere();
  const r = geometry.boundingSphere.radius || 1;
  const s = 1 + (outlineCfg.width || 0.02) / r;
  const o = new THREE.Mesh(geometry, outlineMat);
  o.scale.setScalar(s);
  o.name = 'outline';
  mesh.add(o);
}

// ---------------------------------------------------------------- primitives
const minSeg = style.geometry?.min_segments || 32;
function geometryFor(o) {
  const seg = Math.max(minSeg, o.segments || 0);
  switch (o.shape) {
    case 'box': return new THREE.BoxGeometry(...o.size);
    case 'cylinder': return new THREE.CylinderGeometry(o.radius, o.radius, o.height, seg);
    case 'sphere': return new THREE.SphereGeometry(o.radius, seg, Math.max(16, seg / 2));
    case 'plane': return new THREE.PlaneGeometry(o.size[0], o.size[1]);
    default: throw new Error(`shape '${o.shape}' chưa hỗ trợ`);
  }
}

function buildObject(o, matOpts = {}) {
  const geo = geometryFor(o);
  const mesh = new THREE.Mesh(geo, makeMaterial(o.color, { emissive: o.emissive, ...matOpts }));
  mesh.name = o.name || o.shape;
  if (o.position) mesh.position.set(...o.position);
  if (o.rotation) mesh.rotation.set(...o.rotation.map(d => THREE.MathUtils.degToRad(d)));
  mesh.castShadow = o.shape !== 'plane' && !(o.name || '').startsWith('wall') && !(o.name || '').startsWith('ceiling');
  mesh.receiveShadow = true;
  if (!(o.name || '').startsWith('wall') && !(o.name || '').startsWith('floor') && !(o.name || '').startsWith('ceiling')) {
    addOutline(mesh, geo);
  }
  return mesh;
}

// ---------------------------------------------------------------- set
const setGroup = new THREE.Group();
setGroup.name = `set:${set.asset_id}`;
for (const o of set.objects || []) setGroup.add(buildObject(o));
scene.add(setGroup);

// ---------------------------------------------------------------- characters
/** Người khối (biped_blocks): mỗi bộ phận là một khối, khớp quay ở vai và hông. Mặt hướng +Z. */
function buildBiped(ch, matOpts) {
  const P = ch.parts;
  const g = new THREE.Group();
  const legH = P.leg_l.size[1];
  const torsoH = P.torso.size[1];
  const headR = P.head.radius;

  const part = (spec, name) => {
    const geo = geometryFor(spec);
    const mesh = new THREE.Mesh(geo, makeMaterial(spec.color, matOpts));
    mesh.name = name;
    mesh.castShadow = true;
    addOutline(mesh, geo);
    return mesh;
  };

  const torso = part(P.torso, 'torso');
  torso.position.y = legH + torsoH / 2;
  g.add(torso);

  if (P.apron) {
    const apron = part(P.apron, 'apron');
    apron.position.set(0, legH + torsoH / 2 - 0.05, P.torso.size[2] / 2 + P.apron.size[2] / 2);
    g.add(apron);
  }

  const headPivot = new THREE.Group();
  headPivot.name = 'head_pivot';
  headPivot.position.y = legH + torsoH + headR * 1.05;
  const head = part(P.head, 'head');
  headPivot.add(head);
  if (P.hat) {
    const hat = part(P.hat, 'hat');
    hat.position.y = headR * 0.75 + (P.hat.height || 0.1) / 2;
    headPivot.add(hat);
  }
  if (ch.face) {
    const eyeGeo = new THREE.SphereGeometry(headR * 0.13, 16, 8);
    const eyeMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(ch.face.eyes || '#111') });
    for (const sx of [-1, 1]) {
      const eye = new THREE.Mesh(eyeGeo, eyeMat);
      eye.position.set(sx * headR * 0.38, headR * 0.15, headR * 0.86);
      headPivot.add(eye);
    }
    const mouth = new THREE.Mesh(new THREE.BoxGeometry(headR * 0.5, headR * 0.08, headR * 0.1),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(ch.face.mouth || '#622') }));
    mouth.position.set(0, -headR * 0.35, headR * 0.92);
    headPivot.add(mouth);
  }
  g.add(headPivot);

  const limb = (spec, name, x, y, sign) => {
    const pivot = new THREE.Group();
    pivot.name = name;
    pivot.position.set(x, y, 0);
    const geo = geometryFor(spec);
    geo.translate(0, -spec.size[1] / 2 * sign, 0);
    const mesh = new THREE.Mesh(geo, makeMaterial(spec.color, matOpts));
    mesh.castShadow = true;
    addOutline(mesh, geo);
    pivot.add(mesh);
    g.add(pivot);
    return pivot;
  };
  const shoulderY = legH + torsoH - 0.04;
  const armX = P.torso.size[0] / 2 + P.arm_l.size[0] / 2 + 0.01;
  const legX = P.torso.size[0] / 4;
  const rig = {
    arm_l: limb(P.arm_l, 'arm_l', -armX, shoulderY, 1),
    arm_r: limb(P.arm_r, 'arm_r', armX, shoulderY, 1),
    leg_l: limb(P.leg_l, 'leg_l', -legX, legH, 1),
    leg_r: limb(P.leg_r, 'leg_r', legX, legH, 1),
    head: headPivot,
    hands: new THREE.Group(),
    hand_r: new THREE.Group(),
    legH,
  };
  rig.hands.position.set(0, shoulderY - P.arm_l.size[1] * 0.85, P.torso.size[2] / 2 + 0.28);
  rig.hand_r.position.set(armX, shoulderY - P.arm_r.size[1] - 0.12, 0.05);
  g.add(rig.hands, rig.hand_r);

  const natural = legH + torsoH + headR * 2.1 + (P.hat?.height || 0);
  const scale = (ch.height_m || natural) / natural;
  g.scale.setScalar(scale);
  g.userData.rig = rig;
  return g;
}

/** Nhân vật voxel: lưới (x, y, z, màu) → InstancedMesh một BoxGeometry. */
function buildVoxel(ch, matOpts) {
  const vs = ch.voxel_size || 0.1;
  const geo = new THREE.BoxGeometry(vs, vs, vs);
  const mat = matOpts.override === 'silhouette'
    ? makeMaterial('#000', matOpts)
    : (style.material?.type === 'toon' ? new THREE.MeshToonMaterial({ gradientMap: (gradientMap ||= makeGradientMap(4)) })
      : new THREE.MeshLambertMaterial({ flatShading: true }));
  const inst = new THREE.InstancedMesh(geo, mat, ch.voxels.length);
  const m = new THREE.Matrix4();
  const c = new THREE.Color();
  ch.voxels.forEach((v, i) => {
    m.makeTranslation(v[0] * vs, v[1] * vs + vs / 2, v[2] * vs);
    inst.setMatrixAt(i, m);
    inst.setColorAt(i, c.set(matOpts.override === 'silhouette' ? '#000' : v[3]));
  });
  inst.castShadow = true;
  inst.instanceMatrix.needsUpdate = true;
  const g = new THREE.Group();
  g.add(inst);
  g.userData.rig = null;
  return g;
}

/** Thủ pháp top_down_diagram: nhân vật thành chấm tròn trên sơ đồ. */
function buildMarker(ch) {
  const geo = new THREE.CylinderGeometry(0.35, 0.35, 0.08, minSeg);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: new THREE.Color('#ff5a5f') }));
  mesh.position.y = 0.04;
  const g = new THREE.Group();
  g.add(mesh);
  g.userData.rig = null;
  return g;
}

function buildProp(prop, matOpts = {}) {
  const g = new THREE.Group();
  g.name = `prop:${prop.asset_id}`;
  for (const o of prop.objects || []) g.add(buildObject(o, matOpts));
  return g;
}

const castNodes = {};
const castMaterialOverride = devSpec.cast_material === 'silhouette' ? { override: 'silhouette' } : {};
for (const member of shot.cast) {
  const ch = characters[member.id];
  let node;
  if (member.action === 'hidden' || devSpec.hide_cast) {
    node = new THREE.Group();
    node.visible = false;
  } else if (devSpec.cast_material === 'marker') {
    node = buildMarker(ch);
  } else if (ch.rig === 'voxel_static' || ch.style === 'voxel') {
    node = buildVoxel(ch, castMaterialOverride);
  } else {
    node = buildBiped(ch, castMaterialOverride);
  }
  node.name = `cast:${member.id}`;
  node.userData.member = member;
  // Đồ vật cầm tay
  const rig = node.userData.rig;
  if (rig && !devSpec.hide_cast) {
    for (const pid of member.props || []) {
      const p = props[pid];
      if (!p) continue;
      const pg = buildProp(p, castMaterialOverride);
      const slot = rig[p.attach || 'hands'] || rig.hands;
      if ((p.attach || 'hands') === 'hands') pg.rotation.x = Math.PI / 2;
      slot.add(pg);
    }
  }
  scene.add(node);
  castNodes[member.id] = node;
}

// Thủ pháp symbol_object: một đồ vật tượng trưng xoay chậm tại điểm nhìn của máy quay.
let symbolNode = null;
if (devSpec.symbol) {
  const pid = Object.keys(props)[0];
  if (pid) {
    symbolNode = buildProp(props[pid]);
    symbolNode.scale.setScalar(style.sensitivity?.symbol_scale || 1.6);
    scene.add(symbolNode);
  }
}

// ---------------------------------------------------------------- camera
const cam0 = tracks.camera[0];
const camera = new THREE.PerspectiveCamera(cam0.fov_deg, R.width / R.height, 0.05, 200);
scene.add(camera);

// pixel3d: render nội bộ ở độ phân giải thấp rồi phóng to kiểu nearest.
const internalScale = Number(style.renderer.internal_scale || 1);
let rt = null, blitScene = null, blitCam = null;
if (internalScale < 1) {
  rt = new THREE.WebGLRenderTarget(Math.max(8, Math.round(R.width * internalScale)),
    Math.max(8, Math.round(R.height * internalScale)),
    { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: true });
  blitScene = new THREE.Scene();
  blitCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  blitScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial({ map: rt.texture })));
}

// ---------------------------------------------------------------- animation
const TAU = Math.PI * 2;
function poseCast(node, frame) {
  const member = node.userData.member;
  const tr = tracks.cast[member.id]?.[frame];
  if (!tr) return;
  node.position.set(tr.position[0], tr.position[1], tr.position[2]);
  node.rotation.y = THREE.MathUtils.degToRad(tr.yaw_deg || 0);
  const rig = node.userData.rig;
  if (!rig) return;
  const ph = tr.phase || 0;
  const swing = Math.sin(ph * TAU);
  const a = member.action;
  const reset = () => { for (const k of ['arm_l', 'arm_r', 'leg_l', 'leg_r', 'head']) rig[k].rotation.set(0, 0, 0); };
  reset();
  if (a === 'walk' || a === 'walk_carry') {
    rig.leg_l.rotation.x = swing * 0.55;
    rig.leg_r.rotation.x = -swing * 0.55;
    if (a === 'walk') {
      rig.arm_l.rotation.x = -swing * 0.5;
      rig.arm_r.rotation.x = swing * 0.5;
    } else {
      rig.arm_l.rotation.x = rig.arm_r.rotation.x = -1.25;
      rig.arm_l.rotation.z = 0.25; rig.arm_r.rotation.z = -0.25;
    }
    node.position.y += Math.abs(Math.sin(ph * TAU)) * 0.03;
  } else if (a === 'idle') {
    node.position.y += Math.sin(ph * TAU * 2) * 0.01;
    rig.arm_l.rotation.x = rig.arm_r.rotation.x = 0.05;
  } else if (a === 'talk') {
    rig.head.rotation.x = Math.sin(ph * TAU * 3) * 0.06;
    rig.arm_r.rotation.x = -0.9 + Math.sin(ph * TAU * 2) * 0.25;
    rig.arm_r.rotation.z = -0.3;
  } else if (a === 'point') {
    rig.arm_r.rotation.x = -1.55;
    rig.head.rotation.y = 0.15;
  } else if (a === 'sit') {
    rig.leg_l.rotation.x = rig.leg_r.rotation.x = -Math.PI / 2;
    node.position.y -= rig.legH * node.scale.y * 0.95;
    rig.arm_l.rotation.x = rig.arm_r.rotation.x = -0.6;
  }
}

function renderFrame(i) {
  const n = R.n_frames;
  i = Math.max(0, Math.min(n - 1, i | 0));
  const c = tracks.camera[i];
  camera.position.set(...c.position);
  camera.lookAt(...c.look_at);
  if (camera.fov !== c.fov_deg) { camera.fov = c.fov_deg; camera.updateProjectionMatrix(); }
  for (const node of Object.values(castNodes)) poseCast(node, i);
  if (symbolNode) {
    symbolNode.position.set(c.look_at[0], Math.max(1.0, c.look_at[1]), c.look_at[2]);
    symbolNode.rotation.y = (i / Math.max(1, n - 1)) * TAU * 0.5;
  }
  if (rt) {
    renderer.setRenderTarget(rt);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.render(blitScene, blitCam);
  } else {
    renderer.render(scene, camera);
  }
  return canvas.toDataURL('image/png');
}

window.capture = {
  ready: true,
  frames: R.n_frames,
  width: R.width,
  height: R.height,
  shotId: shot.shot_id,
  renderFrame,
};
renderFrame(0);
