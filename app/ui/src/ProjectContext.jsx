import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from './lib/api.js';

const STORAGE_KEY = 'academy.project';
const ProjectContext = createContext(null);

// Holds the project list and which one is open. Every screen below reads its project from here.
export function ProjectProvider({ children }) {
  const [projects, setProjects] = useState(null); // null while loading
  const [error, setError] = useState('');
  const [recovering, setRecovering] = useState(false);
  const [selectedId, setSelectedId] = useState(() => localStorage.getItem(STORAGE_KEY));

  const refresh = useCallback(async () => {
    setError('');
    try {
      setProjects(await api.listProjects());
      setRecovering(false);
    } catch (e) {
      setProjects(null);
      setRecovering(true);
      let recovered = false;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        try {
          setProjects(await api.listProjects());
          setError('');
          setRecovering(false);
          recovered = true;
          break;
        } catch (_) { /* keep reconnecting while the backend restarts */ }
      }
      if (!recovered) {
        setRecovering(false);
        setError(e.message);
      }
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const select = useCallback((id) => {
    localStorage.setItem(STORAGE_KEY, id);
    setSelectedId(id);
  }, []);

  const create = useCallback(async (body) => {
    const created = await api.createProject(body);
    await refresh();
    select(created.id);
    return created;
  }, [refresh, select]);

  const update = useCallback(async (id, patch) => {
    const updated = await api.updateProject(id, patch);
    await refresh();
    return updated;
  }, [refresh]);

  // Fall back to the first project when the remembered one no longer exists.
  const current = useMemo(
    () => projects?.find((p) => p.id === selectedId) ?? projects?.[0] ?? null,
    [projects, selectedId],
  );

  const value = useMemo(
    () => ({ projects, current, error, recovering, refresh, select, create, update }),
    [projects, current, error, recovering, refresh, select, create, update],
  );
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProjects() {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error('useProjects must be used inside <ProjectProvider>');
  return ctx;
}
