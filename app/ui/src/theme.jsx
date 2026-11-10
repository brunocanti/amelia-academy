import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

export const THEME_MODES = ['system', 'light', 'dark'];
const STORAGE_KEY = 'academy.theme';
const ThemeContext = createContext(null);

const systemPrefersDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches;

function initialMode() {
  const saved = localStorage.getItem(STORAGE_KEY);
  return THEME_MODES.includes(saved) ? saved : 'system';
}

// `mode` is what the person chose; `resolved` is what is on screen ("system" follows the OS live).
export function ThemeProvider({ children }) {
  const [mode, setModeState] = useState(initialMode);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (e) => setSystemDark(e.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const resolved = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;
  useEffect(() => { document.documentElement.dataset.theme = resolved; }, [resolved]);

  const setMode = useCallback((next) => {
    localStorage.setItem(STORAGE_KEY, next);
    setModeState(next);
  }, []);

  const value = useMemo(() => ({ mode, resolved, setMode }), [mode, resolved, setMode]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx;
}
