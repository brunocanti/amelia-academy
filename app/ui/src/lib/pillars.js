// What a pair teaches about the subject: what is known, what is known to be wrong, and what is not known.
// Behavior is about the model itself, so it stands apart from the three.
export const PILLARS = [
  { key: 'known', label: 'Known', note: 'What the files establish, with the quote that proves it.', kinds: ['file', 'connection', 'true_premise', 'complex'] },
  { key: 'false_premise', label: 'False premise', note: 'What is known to be wrong: the question assumes it, a quote rules it out, the answer corrects it.', kinds: ['false_premise'] },
  { key: 'not_known', label: 'Not known', note: 'Where the files stop: details they do not give, and subjects they do not cover.', kinds: ['refusal', 'neighbour'] },
  { key: 'behavior', label: 'Behavior', note: 'How the model acts. Not knowledge: the files do not check it.', kinds: ['behavior'] },
];
export const KIND_LABEL = {
  file: 'Known',
  connection: 'Connected',
  true_premise: 'True version',
  complex: 'In tension',
  false_premise: 'False premise',
  refusal: 'Not known',
  neighbour: 'Neighbouring subject',
  behavior: 'Behavior',
};
export const PILLAR_OF = Object.fromEntries(PILLARS.flatMap((p) => p.kinds.map((kind) => [kind, p.key])));
export const PILLAR_COLOR = { known: '#10a37f', false_premise: '#e8743b', not_known: '#7c7ff0', behavior: '#d65db1' };

// The same pairs, hanging from their pillars instead of their themes.
export function arrangeByPillar(graph) {
  const root = graph.nodes.find((n) => n.type === 'project');
  const present = PILLARS.filter((p) => graph.nodes.some((n) => n.pillar === p.key));
  const nodes = [
    root,
    ...present.map((p) => ({ id: `pillar:${p.key}`, type: 'pillar', label: p.label, pillar: p.key })),
    ...graph.nodes.filter((n) => n.type === 'pair' || n.type === 'file'),
  ];
  const links = [
    ...present.map((p) => ({ source: root.id, target: `pillar:${p.key}`, kind: 'theme' })),
    ...graph.nodes.filter((n) => n.type === 'pair').map((n) => ({ source: `pillar:${n.pillar}`, target: n.id, kind: 'member' })),
    ...graph.links.filter((l) => l.kind !== 'theme' && l.kind !== 'member'),
  ];
  return { ...graph, nodes, links };
}
