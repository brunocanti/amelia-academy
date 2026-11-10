import { useState } from 'react';
import { useI18n } from '../i18n/index.jsx';
import { useProjects } from '../ProjectContext.jsx';
import { Panel } from '../components/Panel.jsx';
import { Button } from '../components/Button.jsx';
import { Expander } from '../components/Expander.jsx';
import { useModel } from '../components/ModelSelect.jsx';
import './project.css';

const LANGUAGES = ['en', 'pt-BR', 'es'];

function slugify(name) {
  return name.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
}

export function ProjectNew({ first = false, onDone, onCancel }) {
  const { t } = useI18n();
  const { create } = useProjects();
  const { model } = useModel();
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugTouched, setSlugTouched] = useState(false);
  const [description, setDescription] = useState('');
  const [language, setLanguage] = useState('en');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const effectiveSlug = slugTouched ? slug : slugify(name);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const created = await create({
        display_name: name, slug: effectiveSlug || undefined, description, language,
      });
      onDone?.(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`pn${first ? ' pn-first' : ''}`}>
      <Panel as="form" fill className="pn-shell" onSubmit={submit}>
        <header className="pn-hero">
          <div className="eyebrow">{t('project.new.eyebrow')}</div>
          <h2>{t(first ? 'project.new.first.title' : 'project.new.title')}</h2>
          <p className="pn-intro">{t('project.new.intro')}</p>
        </header>

        {error && <div className="pn-error">{error}</div>}

        <div className="pn-fields">
          <div className="pn-row">
            <label className="pn-field">
              <span>{t('project.new.name')}</span>
              <input autoFocus required value={name} placeholder={t('project.new.name.placeholder')}
                     onChange={(e) => setName(e.target.value)} />
            </label>
          </div>

          <label className="pn-field">
            <span>{t('project.new.description')}</span>
            <textarea value={description} placeholder={t('project.new.description.placeholder')}
                      onChange={(e) => setDescription(e.target.value)} />
          </label>
          <Expander field="project_description" text={description} language={language} model={model}
                    context={name ? `The project is called ${name}.` : ''} onUse={setDescription} />

          <details><summary>{t('project.new.moreOptions')}</summary>
            <label className="pn-field"><span>{t('project.new.slug')}</span><input value={effectiveSlug} onChange={(e) => { setSlugTouched(true); setSlug(e.target.value); }} /></label>
          </details>

          <label className="pn-field pn-language">
            <span>{t('project.new.language')}</span>
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => <option key={l} value={l}>{t(`language.${l}`)}</option>)}
            </select>
            <small className="pn-hint">{t('project.new.language.hint')}</small>
          </label>
        </div>

        <div className="pn-actions">
          {!first && <Button variant="ghost" title={t('project.new.cancel.tip')} onClick={onCancel}>{t('project.new.cancel')}</Button>}
          <Button type="submit" variant="primary" disabled={busy || !name.trim() || !effectiveSlug} title={t('project.new.create.tip')}>
            {busy ? t('project.new.creating') : t('project.new.create')}
          </Button>
        </div>
      </Panel>
    </div>
  );
}
