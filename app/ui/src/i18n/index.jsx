import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import en from './en.js';
import ptBR from './pt-BR.js';

const catalogs = { en, 'pt-BR': ptBR };
export const LOCALES = Object.keys(catalogs);
const STORAGE_KEY = 'academy.locale';

const I18nContext = createContext(null);

function initialLocale() {
  // The product UI is English-first. Project content language remains an independent project setting.
  return 'en';
}

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(initialLocale);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const setLocale = useCallback((next) => {
    localStorage.setItem(STORAGE_KEY, next);
    setLocaleState(next);
  }, []);
  // A missing key falls back to English, then to the key itself, so a gap is visible rather than blank.
  const t = useCallback((key, vars = {}) => {
    const text = catalogs[locale][key] ?? en[key] ?? key;
    return text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
  }, [locale]);
  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used inside <I18nProvider>');
  return ctx;
}
