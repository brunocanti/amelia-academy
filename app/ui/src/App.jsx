import { useEffect, useState } from 'react';
import { Prototype } from './Prototype.jsx';
import { ProjectNew } from './views/ProjectNew.jsx';
import { useI18n } from './i18n/index.jsx';
import { useProjects } from './ProjectContext.jsx';
import { Button } from './components/Button.jsx';
import './views/project.css';

export function App() {
  const { t } = useI18n();
  const { projects, error, recovering, refresh } = useProjects();
  const [view, setView] = useState(() => location.hash.startsWith('#curate') ? 'curate' : (location.hash.slice(1) || 'files'));
  useEffect(() => {
    const sync = () => setView(location.hash.startsWith('#curate') ? 'curate' : (location.hash.slice(1) || 'files'));
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);

  if (recovering) return <div className="shell-loading">{t('project.restarting')}</div>;
  if (error) {
    return (
      <div className="shell-error">
        <h2>{t('project.unreachable')}</h2>
        <p>{error}</p>
        <p>{t('project.unreachable.hint')}</p>
        <div><Button variant="primary" title={t('project.retry.tip')} onClick={refresh}>{t('project.retry')}</Button></div>
      </div>
    );
  }
  if (projects === null) return <div className="shell-loading">{t('project.loading')}</div>;
  if (projects.length === 0) return <ProjectNew first onDone={() => setView('files')} />;

  return <Prototype activeView={view} onNavigate={setView} />;
}
