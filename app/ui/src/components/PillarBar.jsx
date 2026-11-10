import { PILLARS, PILLAR_COLOR } from '../lib/pillars.js';

// The project's knowledge at a glance. Each pillar's width is its share; with onChoose, each is also a filter.
export function PillarBar({ counts, active = '', onChoose, detail }) {
  const shown = PILLARS.filter((p) => counts[p.key]);
  const total = shown.reduce((sum, p) => sum + counts[p.key], 0);
  if (!total) return null;
  const Tag = onChoose ? 'button' : 'div';
  return (
    <div className={`qa-pillars${active ? ' has-active' : ''}`} role={onChoose ? 'group' : undefined} aria-label="Pillars">
      {shown.map((p) => (
        <Tag key={p.key} title={p.note} style={{ '--pillar': PILLAR_COLOR[p.key], flexGrow: Math.max(counts[p.key], total * 0.14) }}
             className={`qa-pillar${active === p.key ? ' active' : ''}`} aria-pressed={onChoose ? active === p.key : undefined}
             onClick={onChoose ? () => onChoose(active === p.key ? '' : p.key) : undefined}>
          <span className="qa-pillar-name">{p.label}</span>
          <strong>{counts[p.key]}</strong>
          <small>{detail ? detail(p.key) : `${Math.round((counts[p.key] / total) * 100)}%`}</small>
        </Tag>
      ))}
    </div>
  );
}
