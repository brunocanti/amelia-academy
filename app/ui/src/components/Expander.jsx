import { useState } from 'react';
import { api } from '../lib/api.js';
import { Button } from './Button.jsx';
import { useI18n } from '../i18n/index.jsx';
import '../views/qa.css';

// The model writes out what a person drafted. It stays a suggestion until the person takes it.
export function Expander({ field, text, context = '', language, model, onUse }) {
  const { t } = useI18n();
  const [suggestion, setSuggestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function run() {
    setError('');
    setSuggestion('');
    if (!model) { setError('Choose a model at the top first.'); return; }
    setBusy(true);
    try {
      setSuggestion((await api.expand({ field, text, context, language, model })).text);
    } catch (e) {
      setError(e.message === 'Nothing to add' ? t('expander.nothingToAdd') : e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qa-expander">
      <Button type="button" variant="ghost" disabled={busy || !text.trim()} title={text.trim() ? 'The model suggests a fuller version. Nothing changes until you choose.' : 'Write something first.'} onClick={run}>{busy ? 'Expanding…' : 'Expand'}</Button>
      {error && <p className="qa-bad">{error}</p>}
      {suggestion && (
        <div className="qa-suggestion">
          <p>{suggestion}</p>
          <div className="qa-pair-actions">
            <Button type="button" variant="primary" title="Replaces your text with this suggestion." onClick={() => { onUse(suggestion); setSuggestion(''); }}>Use this</Button>
            <Button type="button" variant="ghost" title="Drops this suggestion and keeps your text." onClick={() => setSuggestion('')}>Keep mine</Button>
          </div>
        </div>
      )}
    </div>
  );
}
