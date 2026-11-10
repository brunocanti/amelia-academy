import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import SpriteText from 'three-spritetext';
import { BufferAttribute, BufferGeometry, CanvasTexture, Group, Line, LineDashedMaterial, Sprite, SpriteMaterial } from 'three';
import { PILLARS, PILLAR_COLOR } from '../lib/pillars.js';

const COLOR = { project: '#a78bfa', theme: '#06b6d4', file: '#9b9b9b', behavior: PILLAR_COLOR.behavior };
const SIZE = { project: 14, theme: 6, pillar: 10, file: 3, pair: 2.5 };
const hexToRgba = (hex, alpha) => `rgba(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(', ')}, ${alpha})`;
const NODE_SCALE = 4.5; // radius; nodeVal goes in as volume, so this is what grows a node by a set share
const DIM = { light: 'rgba(120, 118, 110, 0.18)', dark: 'rgba(150, 150, 150, 0.14)' };
const DIM_LINK = { light: 'rgba(120, 118, 110, 0.10)', dark: 'rgba(150, 150, 150, 0.07)' };
const LIT_LINK = { light: '#4a4943', dark: '#d6d4cc', width: 2.4 }; // neutral: thickness marks the selection, color keeps meaning state
const LINK = {
  theme: { light: '#a9a69b', dark: '#55554f', width: 0.8 },
  member: { light: '#c3c0b5', dark: '#3a3a3a', width: 0.3 },
  file: { light: '#dedbd0', dark: '#2a2a2a', width: 0.15 },
  passage: { light: '#c3c0b5', dark: '#3a3a3a', width: 0.2 },
  combines: { light: '#0d9668', dark: '#10b981', width: 0.7 },
  tension: { light: '#d4483b', dark: '#f0655a', width: 1.1 },
};
// By pillar, each pillar holds its own place in space: what is known, what is ruled out, where the files stop.
const PILLAR_PLACE = {
  known: [-170, 40, 0],
  false_premise: [210, 170, -60],
  not_known: [210, -170, 60],
  behavior: [-170, -300, 0],
};
const PILLAR_PULL = 0.16;
const CONFIDENCE_WIDTH = { low: 2, medium: 5, high: 9 };

function confidenceTexture(level) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const context = canvas.getContext('2d');
  context.strokeStyle = '#ffffff';
  context.lineWidth = CONFIDENCE_WIDTH[level] || CONFIDENCE_WIDTH.low;
  context.beginPath();
  context.arc(64, 64, 57 - context.lineWidth / 2, 0, Math.PI * 2);
  context.stroke();
  return new CanvasTexture(canvas);
}

function useLightTheme() {
  const [light, setLight] = useState(() => document.documentElement.getAttribute('data-theme') === 'light');
  useEffect(() => {
    const el = document.documentElement;
    const mo = new MutationObserver(() => setLight(el.getAttribute('data-theme') === 'light'));
    mo.observe(el, { attributes: true, attributeFilter: ['data-theme'] });
    return () => mo.disconnect();
  }, []);
  return light;
}

function useBox() {
  const host = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = host.current;
    if (!el) return undefined;
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [host, size];
}

function colorOf(node) {
  if (node.type === 'theme' && node.kind === 'behavior') return COLOR.behavior;
  if (node.type === 'pillar') return PILLAR_COLOR[node.pillar];
  if (node.type !== 'pair') return COLOR[node.type];
  // The color says what it teaches; the strength says whether a person has approved it.
  return node.status === 'approved' ? PILLAR_COLOR[node.pillar] : hexToRgba(PILLAR_COLOR[node.pillar], 0.55);
}

// The picture of the project's knowledge. Every link comes from the data: nothing is inferred here.
export function BrainGraph({ graph, kind, pillar, selectedId, onSelect }) {
  const light = useLightTheme();
  const [host, size] = useBox();
  const api = useRef(null);
  const fitted = useRef(false);
  const kept = useRef(new Map());

  const structure = useMemo(() => (
    graph.nodes.map((n) => n.id).join('|') + '#' + graph.links.map((l) => `${l.source}>${l.target}`).join('|')
  ), [graph]);

  // Node objects survive a refresh: approving a pair recolors it and leaves the layout alone.
  for (const node of graph.nodes) {
    const held = kept.current.get(node.id);
    if (held) Object.assign(held, node);
    else kept.current.set(node.id, { ...node });
  }

  const data = useMemo(() => ({
    nodes: graph.nodes.map((n) => kept.current.get(n.id)),
    links: graph.links.map((l) => ({ ...l })),
  }), [structure]);

  const statuses = graph.nodes.map((n) => n.status || '').join('');
  const mode = light ? 'light' : 'dark';
  const confidenceState = graph.nodes.map(n => n.confidence || '').join('|');
  // Link objects keep their simulation endpoints while editorial state changes.
  graph.links.forEach((link, index) => { if (data.links[index]) data.links[index].review_state = link.review_state; });

  // Selecting a node keeps it and what it touches in front; the rest of the graph steps back.
  const near = useMemo(() => {
    if (!selectedId || !graph.nodes.some((n) => n.id === selectedId)) return null;
    const ids = new Set([selectedId]);
    for (const l of graph.links) {
      if (l.source === selectedId) ids.add(l.target);
      if (l.target === selectedId) ids.add(l.source);
    }
    return ids;
  }, [selectedId, structure]);

  // The kind filter dims instead of removing, so the graph does not rearrange every time it changes.
  const inKind = useMemo(() => {
    if (!kind && !pillar) return null;
    const ids = new Set(graph.nodes.filter((n) => (kind ? n.origin === kind : n.pillar === pillar)).map((n) => n.id));
    const pairs = new Set(ids);
    for (const l of graph.links) {
      if (pairs.has(l.source)) ids.add(l.target);
      if (pairs.has(l.target)) ids.add(l.source);
    }
    return ids;
  }, [kind, pillar, structure]);

  const touchesSelected = useCallback((l) => [l.source, l.target].some((end) => (end?.id ?? end) === selectedId), [selectedId]);

  const nodeColor = useCallback((n) => {
    if (near && !near.has(n.id)) return DIM[mode];
    if (inKind && !inKind.has(n.id) && n.type !== 'project') return DIM[mode];
    return colorOf(n);
  }, [near, inKind, statuses, mode]);

  const textLabel = useCallback((n) => {
    const selected = n.id === selectedId;
    if (n.type === 'pair' && !selected) return null;
    if (near && !near.has(n.id)) return null;
    if (inKind && !inKind.has(n.id) && n.type !== 'project') return null;
    const sprite = new SpriteText(n.label.length > 42 ? `${n.label.slice(0, 40)}…` : n.label);
    sprite.color = light ? '#1a1a18' : '#f4f4f4';
    sprite.textHeight = (n.type === 'project' ? 5.5 : n.type === 'pillar' ? 4.4 : n.type === 'theme' ? 3.4 : 2.4) * (selected ? 1.4 : 1);
    sprite.fontWeight = n.type === 'file' && !selected ? '400' : '650';
    sprite.strokeWidth = 0.35;
    sprite.strokeColor = light ? '#ffffff' : '#0d0d0d';
    if (selected) { sprite.material.depthTest = false; sprite.renderOrder = 10; } // its own links and neighbours must not cover the name
    sprite.position.y = (n.type === 'project' ? 26 : n.type === 'pillar' ? 20 : n.type === 'theme' ? 16 : 10) * (selected ? 1.5 : 1);
    return sprite;
  }, [light, selectedId, near, inKind]);

  const nodeObject = useCallback(n => {
    const text = textLabel(n);
    if (n.type !== 'pair') return text;
    const group = new Group();
    const faded = (near && !near.has(n.id)) || (inKind && !inKind.has(n.id));
    // Camera-facing outline stays readable as the user rotates the 3D graph.
    const outline = new Sprite(new SpriteMaterial({
      map: confidenceTexture(n.confidence), color: light ? '#45443f' : '#eeeeea',
      transparent: true, opacity: faded ? 0.12 : 0.95, depthWrite: false,
    }));
    const diameter = Math.cbrt(SIZE.pair * (n.id === selectedId ? 3 : 1)) * NODE_SCALE * 2 * 1.34;
    outline.scale.set(diameter, diameter, 1);
    group.add(outline);
    if (text) group.add(text);
    return group;
  }, [textLabel, near, inKind, light, selectedId, confidenceState]);

  const linkColor = useCallback(l => {
    if (touchesSelected(l)) return LIT_LINK[mode];
    const ends = [l.source?.id ?? l.source, l.target?.id ?? l.target];
    if (inKind && !ends.every(end => inKind.has(end) || end.startsWith('project:'))) return DIM_LINK[mode];
    if (l.kind === 'tension' && !near) return LINK.tension[mode];
    return near ? DIM_LINK[mode] : (LINK[l.kind] || LINK.member)[mode];
  }, [touchesSelected, inKind, near, mode]);

  const reviewedLinks = graph.links.map(l => l.review_state || '').join('|');
  const linkObject = useCallback(l => {
    if (l.review_state !== 'proposed') return null;
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new BufferAttribute(new Float32Array(6), 3));
    const color = linkColor(l);
    const rgba = color.match(/^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/);
    return new Line(geometry, new LineDashedMaterial({
      color: rgba ? `rgb(${rgba[1]},${rgba[2]},${rgba[3]})` : color,
      dashSize: 6, gapSize: 4, transparent: true, opacity: 0.8 * (rgba ? Number(rgba[4]) : 1),
    }));
  }, [linkColor, reviewedLinks]);

  const placeLink = useCallback((object, { start, end }, link) => {
    if (link.review_state !== 'proposed' || !object?.isLine) return false;
    const points = object.geometry.attributes.position;
    points.setXYZ(0, start.x, start.y, start.z);
    points.setXYZ(1, end.x, end.y, end.z);
    points.needsUpdate = true;
    object.geometry.computeBoundingSphere();
    object.computeLineDistances();
    return true;
  }, []);

  // Bring the selected node to the front of the camera. With nothing selected, show the whole graph.
  const frame = useCallback((ms) => {
    const camera = api.current;
    const node = selectedId ? kept.current.get(selectedId) : null;
    if (node?.x === undefined) {
      if (!selectedId) camera?.zoomToFit(ms, 50);
      return;
    }
    const distance = node.type === 'pair' ? 420 : node.type === 'project' ? 700 : 560;
    const norm = Math.hypot(node.x, node.y, node.z);
    const out = norm < 1 ? { x: 0, y: 0, z: distance } : { x: node.x * (1 + distance / norm), y: node.y * (1 + distance / norm), z: node.z * (1 + distance / norm) };
    camera?.cameraPosition(out, { x: node.x, y: node.y, z: node.z }, ms);
  }, [selectedId]);

  useEffect(() => {
    if (fitted.current) frame(700);
  }, [frame]);

  useEffect(() => {
    api.current?.d3Force('charge')?.strength?.(-70);
    const arranged = data.nodes.some((n) => n.type === 'pillar');
    api.current?.d3Force('link')?.distance?.((l) => (l.kind === 'theme' ? 80 : l.kind === 'file' ? 90 : 22));
    // Passages and files cross the pillars; drawn as they are, they would pull the groups back into one ball.
    const loose = { file: 0.02, passage: arranged ? 0.005 : 0.1, tension: 0.005, combines: arranged ? 0.02 : 0.6 };
    api.current?.d3Force('link')?.strength?.((l) => loose[l.kind] ?? 0.6);
    api.current?.d3Force('pillars', !arranged ? null : (alpha) => {
      for (const n of data.nodes) {
        const place = PILLAR_PLACE[n.pillar];
        if (!place) continue;
        n.vx += (place[0] - n.x) * PILLAR_PULL * alpha;
        n.vy += (place[1] - n.y) * PILLAR_PULL * alpha;
        n.vz += (place[2] - n.z) * PILLAR_PULL * alpha;
      }
    });
  }, [structure, size.width]);

  // The first framing is measured against the box of that moment: collapsing the themes panel changes it.
  // Deferred because the renderer takes the new size on its next tick, and framing sooner uses the old aspect.
  useEffect(() => {
    if (!fitted.current) return undefined;
    const timer = setTimeout(() => frame(400), 60);
    return () => clearTimeout(timer);
  }, [size.width, size.height, frame]);

  return (
    <div className="qa-graph" ref={host}>
      {size.width > 0 && size.height > 0 && (
        <ForceGraph3D
          ref={api}
          width={size.width}
          height={size.height}
          graphData={data}
          backgroundColor={light ? '#faf9f6' : '#121212'}
          showNavInfo={false}
          controlType="orbit"
          enableNodeDrag={false}
          nodeLabel={(n) => n.type === 'pair' ? `${n.label} · Confidence: ${n.confidence} · ${(n.confidence_reasons || []).join(' ')}` : n.label}
          nodeColor={nodeColor}
          nodeVal={(n) => SIZE[n.type] * (n.id === selectedId ? 3 : 1)}
          nodeRelSize={NODE_SCALE}
          nodeOpacity={0.95}
          nodeResolution={12}
          nodeThreeObjectExtend
          nodeThreeObject={nodeObject}
          linkColor={linkColor}
          linkThreeObject={linkObject}
          linkPositionUpdate={placeLink}
          linkLabel={l => l.review_state ? `${l.kind === 'tension' ? 'Conflict' : 'Supporting relation'} · ${l.review_state === 'confirmed' ? 'Confirmed in review' : 'Needs review'}` : ({ theme: 'Theme', member: 'Theme membership', file: 'Source file', passage: 'Shared passage' }[l.kind] || l.kind)}
          linkWidth={(l) => (touchesSelected(l) ? LIT_LINK.width : (LINK[l.kind] || LINK.member).width)}
          linkOpacity={0.8}
          onNodeClick={(n) => onSelect?.(n)}
          cooldownTicks={140}
          onEngineStop={() => {
            if (fitted.current) return;
            fitted.current = true;
            frame(700);
          }}
        />
      )}
      <ul className="qa-legend" aria-label="Legend">
        {PILLARS.map((p) => <li key={p.key}><i style={{ background: PILLAR_COLOR[p.key] }} />{p.label}</li>)}
        {Object.keys(CONFIDENCE_WIDTH).map(level => <li key={level}><i className={`qa-confidence-ring is-${level}`} />{level[0].toUpperCase() + level.slice(1)} confidence</li>)}
        {graph.links.some(l => l.review_state) && <>
          <li><i className="qa-relation-dash" />Relation to review</li>
          <li><i className="qa-relation-solid" />Confirmed relation</li>
        </>}
        <li className="qa-legend-note">Faint: to review · Solid: approved</li>
        <li><i style={{ background: COLOR.theme }} />Theme</li>
        <li><i style={{ background: COLOR.file }} />File</li>
        <li><i className="qa-legend-line" style={{ background: LIT_LINK[mode] }} />Selected</li>
        {graph.links.some((l) => l.kind === 'tension') && <li><i className="qa-legend-line" style={{ background: LINK.tension[mode] }} />In conflict</li>}
      </ul>
    </div>
  );
}
