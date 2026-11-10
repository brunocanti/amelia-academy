import { useEffect, useState } from 'react';
import { api } from '../lib/api.js';

const KEY = 'academy.model';

function storedModel() {
  return localStorage.getItem(KEY)
    || localStorage.getItem('academy.model.extract')
    || localStorage.getItem('academy.model.samples')
    || '';
}

// What a run saved says who ran it. The person only needs the model's own name.
export const modelName = (name) => (name || '').replace(/^(claude|codex|agy)-cli:/, '');

const noticeOf = (items, model) => items.find((item) => item.name === model)?.notice || '';

export function useModel() {
  const [model, setModel] = useState(storedModel);
  const [models, setModels] = useState([]);
  const [items, setItems] = useState([]);
  const [vision, setVision] = useState({});
  const [error, setError] = useState('');

  useEffect(() => {
    const sync = () => setModel(storedModel());
    window.addEventListener('academy-model', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('academy-model', sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.listModels().then((data) => {
      if (cancelled) return;
      const names = data.models.map((item) => item.name);
      setModels(names);
      setItems(data.models);
      if (data.problems?.length) setError(data.problems.join(' '));
      setVision(Object.fromEntries(
        data.models.filter((item) => item.vision === true || item.vision === false).map((item) => [item.name, item.vision]),
      ));
      setModel((current) => {
        const next = current && names.includes(current) ? current : data.default;
        if (next) localStorage.setItem(KEY, next);
        return next;
      });
    }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, []);

  function choose(name) {
    setModel(name);
    localStorage.setItem(KEY, name);
    window.dispatchEvent(new Event('academy-model'));
  }

  return {
    model, models, items, error, choose,
    notice: noticeOf(items, model),
    sees: vision[model] === true,
    known: Object.prototype.hasOwnProperty.call(vision, model),
  };
}

export function ModelSelect({ label, model, items, error, onChange, compact = false }) {
  const here = items.filter((item) => !item.online);
  const tools = [...new Set(items.filter((item) => item.online).map((item) => item.group))];
  return (
    <label className={`model-select${compact ? ' is-compact' : ''}`}>
      {compact ? null : label}
      <select aria-label={label} value={model} onChange={(e) => onChange(e.target.value)} disabled={!items.length}>
        {!items.length && <option value="">{error ? 'No model available' : 'Loading models…'}</option>}
        {!model && items.length > 0 && <option value="">Choose a model</option>}
        {here.length > 0 && tools.length === 0 && here.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
        {here.length > 0 && tools.length > 0 && (
          <optgroup label="On this computer">
            {here.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
          </optgroup>
        )}
        {tools.map((tool) => (
          <optgroup key={tool} label={`${tool} (online)`}>
            {items.filter((item) => item.online && item.group === tool).map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
          </optgroup>
        ))}
      </select>
      {error && <small>{error}</small>}
    </label>
  );
}
