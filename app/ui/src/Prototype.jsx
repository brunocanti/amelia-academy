import { useState } from 'react';
import { useI18n } from './i18n/index.jsx';
import { useProjects } from './ProjectContext.jsx';
import { ProjectNew } from './views/ProjectNew.jsx';
import { ProjectSwitcher } from './ProjectSwitcher.jsx';
import { Files } from './views/Files.jsx';
import { Curate } from './views/Curate.jsx';
import { Behaviors } from './views/Behaviors.jsx';
import { Export } from './views/Export.jsx';
import { Train } from './views/Train.jsx';
import { Compare } from './views/Compare.jsx';
import { Button } from './components/Button.jsx';
import { ThemeToggle } from './ThemeToggle.jsx';
import { ModelSelect, useModel } from './components/ModelSelect.jsx';
import { Console } from './components/Console.jsx';
import { RunsProvider } from './components/Runs.jsx';
import { ActivityBar } from './components/Activity.jsx';
import './workflow.css';
import './views/qa.css';

const NAV = [
  { key: 'files', title: 'Files', glyph: '↑' },
  { key: 'curate', title: 'Curate', glyph: '✓' },
  { key: 'behaviors', title: 'Behaviors', glyph: '◇' },
  { key: 'export', title: 'Export', glyph: '▤' },
  { key: 'train', title: 'Train', glyph: '↗' },
  { key: 'compare', title: 'Compare', glyph: '⇄' },
];

export function Prototype({ activeView, onNavigate }) {
  const { t } = useI18n();
  const { current: project, update } = useProjects();
  const model = useModel();
  const [params, setParams] = useState(() => {
    const bits = location.hash.slice(1).split('/');
    return bits[0] === 'curate' && bits[1] ? { view: bits[1] } : null;
  });
  const [rail, setRail] = useState(() => localStorage.getItem('academy.nav.rail') === '1');

  function toggleRail() {
    setRail((open) => {
      localStorage.setItem('academy.nav.rail', open ? '0' : '1');
      return !open;
    });
  }

  function go(view, next = null) {
    const target = view === 'overview' ? 'files' : view;
    setParams(next);
    onNavigate(target);
    history.replaceState(null, '', target === 'curate' ? `#curate${next?.view ? `/${next.view}` : ''}` : `#${target}`);
  }

  const shared = { project, model: model.model, onNavigate: go, initial: params };
  let body;
  if (activeView === 'project-new') body = <ProjectNew onDone={() => go('files')} onCancel={() => go('files')} />;
  else if (activeView === 'curate') body = <Curate key={project.id + (params?.source || '') + (params?.view || '')} project={project} model={model.model} initial={params || { view: location.hash.split('/')[1] }} />;
  else if (activeView === 'behaviors') body = <Behaviors key={project.id} {...shared} />;
  else if (activeView === 'export') body = <Export key={project.id} {...shared} />;
  else if (activeView === 'train') body = <Train key={project.id + (params?.run_id || '')} {...shared} />;
  else if (activeView === 'compare') body = <Compare key={project.id + (params?.run_id || '')} {...shared} />;
  else body = <Files key={project.id} {...shared} initial={params} modelSees={model.known ? model.sees : null} />;

  const title = activeView === 'project-new' ? t('project.new.title')
    : (NAV.find((item) => item.key === activeView) || NAV[0]).title;

  return (
    <div className={`prototype-shell${rail ? ' rail-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="mark" title="Amelia Academy">A</span>
          {!rail && <span>Amelia Academy</span>}
          <button className="rail-toggle" title={rail ? 'Expand navigation' : 'Collapse navigation'} aria-label={rail ? 'Expand navigation' : 'Collapse navigation'} onClick={toggleRail}>{rail ? '›' : '‹'}</button>
        </div>
        <ProjectSwitcher onNavigate={go} compact={rail} />
        <nav className="workflow-nav" aria-label="Project">
          {NAV.map((item) => (
            <button key={item.key} className={`nav-item${activeView === item.key ? ' active' : ''}`} title={item.title} aria-label={item.title} onClick={() => go(item.key)}>
              <span className="nav-glyph" aria-hidden="true">{item.glyph}</span>
              {!rail && <span>{item.title}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot" title="Project data stored locally"><span className="green-dot" />{!rail && ' Project data stored locally'}</div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div>
            <div className="crumb">Amelia Academy <span>/</span> {project.display_name}</div>
            <h1>{title}</h1>
          </div>
          <div className="top-actions">
            {!['train', 'compare'].includes(activeView) && <ModelSelect label="Model" model={model.model} items={model.items} error={model.error} onChange={model.choose} />}
            <ThemeToggle compact />
          </div>
        </header>
        {project.status === 'archived' && (
          <div className="archived-banner">
            <span>{t('project.archived.banner')}</span>
            <Button variant="secondary" title={t('project.archived.restore.tip')} onClick={() => update(project.id, { status: 'active' })}>{t('project.archived.restore')}</Button>
          </div>
        )}
        {model.notice && <div className="model-notice">{model.notice}</div>}
        <RunsProvider key={project.id} projectId={project.id}>
          <main className="content">{body}</main>
          <ActivityBar projectId={project.id} onGo={go} onConsole={() => window.dispatchEvent(new Event('academy-console-toggle'))} />
        </RunsProvider>
        <Console />
      </div>
    </div>
  );
}
