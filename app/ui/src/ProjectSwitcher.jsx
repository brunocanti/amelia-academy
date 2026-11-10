import { useEffect, useRef, useState } from 'react';
import { useI18n } from './i18n/index.jsx';
import { useProjects } from './ProjectContext.jsx';

export function ProjectSwitcher({ onNavigate, compact = false }) {
  const { t } = useI18n();
  const { projects, current, select } = useProjects();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  if (!current) return null;
  const languageName = (language) => ({ en: 'English', 'pt-BR': 'Portuguese (Brazil)', es: 'Spanish' }[language] ?? language);
  const meta = (p) => languageName(p.language);

  return (
    <div className="ps" ref={ref}>
      <button className={`project-switch${compact ? ' compact' : ''}`} aria-haspopup="listbox" aria-expanded={open} title={current.display_name} onClick={() => setOpen(!open)}>
        <span className="project-dot" />
        {compact ? <strong>{current.display_name.slice(0, 1).toUpperCase()}</strong> : (
          <span>
            <strong>{current.display_name}</strong>
            <small>{meta(current)}</small>
          </span>
        )}
        {!compact && <span className="chevron">⌄</span>}
      </button>
      {open && (
        <div className={`ps-menu${compact ? ' ps-menu-rail' : ''}`} role="listbox" aria-label={t('project.switch.label')}>
          {projects.map((p) => (
            <button key={p.id} role="option" aria-selected={p.id === current.id}
                    className={`ps-item${p.id === current.id ? ' active' : ''}`} title={p.display_name}
                    onClick={() => { select(p.id); setOpen(false); onNavigate('overview'); }}>
              <strong>{p.display_name}{p.status === 'archived' && <span className="ps-badge">{t('project.status.archived')}</span>}</strong>
              <small>{meta(p)}</small>
            </button>
          ))}
          <button className="ps-item ps-new" title={t('project.switch.new.tip')} onClick={() => { setOpen(false); onNavigate('project-new'); }}>
            + {t('project.switch.new')}
          </button>
        </div>
      )}
    </div>
  );
}
