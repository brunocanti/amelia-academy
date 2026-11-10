import { useI18n } from './i18n/index.jsx';
import { THEME_MODES, useTheme } from './theme.jsx';

const ICONS = { system: '◐', light: '○', dark: '●' };

export function ThemeToggle({ compact = false }) {
  const { t } = useI18n();
  const { mode, setMode } = useTheme();
  return (
    <div className={`theme-toggle${compact ? ' compact' : ''}`} role="radiogroup" aria-label={t('theme.label')}>
      {THEME_MODES.map((m) => (
        <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? 'active' : ''}
                title={t(`theme.${m}`)} onClick={() => setMode(m)}>
          <span aria-hidden="true">{ICONS[m]}</span>
          {!compact && <span className="theme-toggle-label">{t(`theme.${m}`)}</span>}
        </button>
      ))}
    </div>
  );
}
