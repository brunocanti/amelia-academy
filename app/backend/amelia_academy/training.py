"""Persistent training and blind comparison; small isolated MLX subprocesses own the GPU."""
import hashlib
import io
import json
import math
import os
import platform
import queue
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, gpu, projects, qa, runs, workshop

TRAINER = Path(__file__).resolve().parents[2] / 'trainer'
PYTHON = TRAINER / '.venv/bin/python'
WORKER = TRAINER / 'worker.py'
CATALOG = [{'id': 'mlx-community/Qwen3-4B-4bit', 'label': 'Qwen3 4B · 4-bit', 'parameters_b': 4,
            'revision': '4dcb3d101c2a062e5c1d4bb173588c54ea6c4d25', 'num_layers': 36}]
_processes = {}
_process_lock = threading.Lock()
TERMINATE_SECONDS = 10
KILL_SECONDS = 5


def model_info(model):
    item = next((dict(m) for m in CATALOG if m['id'] == model), None)
    if not item: raise ValueError('Choose a supported model of at most 4B parameters.')
    cache = Path(os.environ.get('HF_HUB_CACHE', Path.home()/'.cache/huggingface/hub'))
    path = cache / ('models--' + model.replace('/', '--')) / 'snapshots' / item['revision']
    item.update(base_path=str(path), cached=(path/'config.json').is_file() and any(path.glob('*.safetensors')))
    return item


def models():
    return [{k: v for k, v in model_info(m['id']).items() if k != 'base_path'} for m in CATALOG]


def _public(row):
    if not row: return None
    row['config'] = json.loads(row['config'])
    return row


def _summary(conn, root, row):
    item = _public(row)
    item['label'] = item.get('name') or f"Version {item.get('version') or '?'}"
    item['samples'] = item['pairs'] = 0
    item['answer_model'] = ''
    item['size_bytes'] = 0
    item['better'] = item['worse'] = item['same'] = item['total'] = 0
    item['deleting_at'] = item.get('deleting_at')
    try:
        folder = _folder(root, item['id']) if root is not None else None
        if folder is None: raise OSError('No storage root supplied')
        data = folder / 'data'
        for path in folder.rglob('*'):
            if path.is_file(): item['size_bytes'] += path.stat().st_size
        manifest_path = data / 'training-manifest.json'
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            item['samples'] = int(manifest.get('statistics', {}).get('total_samples', 0))
            item['pairs'] = int(manifest.get('statistics', {}).get('by_origin', {}).get('pairs') or manifest.get('statistics', {}).get('direct', 0))
            models = sorted({e.get('answer_model') for e in manifest.get('entries', []) if e.get('answer_model')})
            if not models: models = sorted({c.get('answer_model') for c in manifest.get('preparation', {}).get('configurations', []) if c.get('answer_model')})
            item['answer_model'] = ', '.join(m.rsplit('/', 1)[-1] for m in models)
        else:
            ds = db.row(conn, 'SELECT manifest_path FROM datasets WHERE id=?', (item['dataset_id'],))
            if ds and ds.get('manifest_path') and Path(ds['manifest_path']).is_file():
                manifest = json.loads(Path(ds['manifest_path']).read_text())
                item['samples'] = manifest.get('statistics', {}).get('total_samples', 0)
                item['pairs'] = int(manifest.get('statistics', {}).get('by_origin', {}).get('pairs') or manifest.get('statistics', {}).get('direct', 0))
                models = sorted({e.get('answer_model') for e in manifest.get('entries', []) if e.get('answer_model')})
                if not models: models = sorted({c.get('answer_model') for c in manifest.get('preparation', {}).get('configurations', []) if c.get('answer_model')})
                item['answer_model'] = ', '.join(m.rsplit('/', 1)[-1] for m in models)
        scores = db.rows(conn, "SELECT choice,base_on_left FROM train_comparisons WHERE run_id=? AND choice IS NOT NULL AND set_name!='try'", (item['id'],))
        for score in scores:
            item['total'] += 1
            trained = score['choice'] == ('right' if score['base_on_left'] else 'left')
            if score['choice'] in ('same', 'both_wrong'): item['same'] += 1
            elif trained: item['better'] += 1
            else: item['worse'] += 1
    except (OSError, ValueError):
        pass
    return item


def get(conn, project_id, run_id, root=None):
    row = db.row(conn, 'SELECT * FROM train_runs WHERE id=? AND project_id=?', (run_id, project_id))
    if not row: raise workshop.NotFound('Training run not found.')
    return _summary(conn, root, row) if root is not None else _public(row)


def list_runs(conn, project_id, root=None):
    if root is not None:
        cleanup_deletions(conn, root)
    return [_summary(conn, root, r) for r in db.rows(conn, 'SELECT * FROM train_runs WHERE project_id=? AND deleting_at IS NULL ORDER BY version DESC,created_at DESC', (project_id,))]


def _purge(conn, root, run_id):
    row = db.row(conn, 'SELECT * FROM train_runs WHERE id=?', (run_id,))
    if not row: return
    config = json.loads(row['config'])
    conn.execute('DELETE FROM train_events WHERE run_id=?', (run_id,))
    conn.execute('DELETE FROM train_comparisons WHERE run_id=?', (run_id,))
    conn.execute('DELETE FROM train_recall WHERE run_id=?', (run_id,))
    conn.execute('DELETE FROM train_runs WHERE id=?', (run_id,)); conn.commit()
    if config.get('auto_dataset') and not conn.execute('SELECT 1 FROM train_runs WHERE dataset_id=?', (row['dataset_id'],)).fetchone():
        dataset = db.row(conn, 'SELECT path,manifest_path FROM datasets WHERE id=?', (row['dataset_id'],))
        if dataset:
            folder = Path(dataset['path']).resolve().parent
            if folder.is_relative_to((Path(root) / 'datasets').resolve()): shutil.rmtree(folder, ignore_errors=True)
            conn.execute('DELETE FROM datasets WHERE id=?', (row['dataset_id'],)); conn.commit()
    shutil.rmtree(_folder(root, run_id), ignore_errors=True)
    if row['in_use']:
        fallback = conn.execute("SELECT id FROM train_runs WHERE project_id=? AND status='finished' AND deleting_at IS NULL ORDER BY version DESC LIMIT 1", (row['project_id'],)).fetchone()
        if fallback:
            conn.execute('UPDATE train_runs SET in_use=1 WHERE id=?', (fallback[0],)); conn.commit()


def cleanup_deletions(conn, root):
    for item in db.rows(conn, 'SELECT id FROM train_runs WHERE deleting_at IS NOT NULL AND deleting_at<=?', (db.now(),)):
        _purge(conn, root, item['id'])


def update_version(conn, project_id, run_id, *, name=None, in_use=None):
    item = get(conn, project_id, run_id)
    if item.get('deleting_at'): raise ValueError('Undo deletion before changing this version.')
    if name is not None:
        name = name.strip()
        if len(name) > 120: raise ValueError('Use a name up to 120 characters.')
        conn.execute('UPDATE train_runs SET name=? WHERE id=?', (name, run_id))
    if in_use is not None:
        if in_use and item['status'] != 'finished': raise ValueError('Only a finished version can be in use.')
        conn.execute('UPDATE train_runs SET in_use=0 WHERE project_id=?', (project_id,))
        if in_use: conn.execute('UPDATE train_runs SET in_use=1 WHERE id=?', (run_id,))
    conn.commit()
    return _summary(conn, None, db.row(conn, 'SELECT * FROM train_runs WHERE id=?', (run_id,)))


def delete_version(conn, root, project_id, run_id):
    item = get(conn, project_id, run_id)
    if item['status'] in ('preparing', 'training'): raise workshop.Conflict('Stop training before deleting this version.')
    deleting_at = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    conn.execute('UPDATE train_runs SET deleting_at=? WHERE id=?', (deleting_at, run_id)); conn.commit()
    if item['in_use']:
        fallback = conn.execute("SELECT id FROM train_runs WHERE project_id=? AND id!=? AND status='finished' AND deleting_at IS NULL ORDER BY version DESC LIMIT 1", (project_id, run_id)).fetchone()
        if fallback:
            conn.execute('UPDATE train_runs SET in_use=1 WHERE id=?', (fallback[0],)); conn.commit()
    return {'id': run_id, 'version': item.get('version'), 'label': item.get('name') or f"Version {item.get('version')}", 'deleting_at': deleting_at}


def undo_delete(conn, project_id, run_id):
    item = get(conn, project_id, run_id)
    if not item.get('deleting_at'): raise ValueError('This version is not waiting to be deleted.')
    if item['deleting_at'] <= db.now(): raise ValueError('The delete period has passed.')
    conn.execute('UPDATE train_runs SET deleting_at=NULL WHERE id=?', (run_id,))
    if item['in_use']:
        conn.execute('UPDATE train_runs SET in_use=0 WHERE project_id=?', (project_id,))
        conn.execute('UPDATE train_runs SET in_use=1 WHERE id=?', (run_id,))
    conn.commit()
    return get(conn, project_id, run_id)


def delete_others(conn, root, project_id):
    ids = [r['id'] for r in db.rows(conn, "SELECT id FROM train_runs WHERE project_id=? AND in_use=0 AND status NOT IN ('preparing','training') AND deleting_at IS NULL", (project_id,))]
    stamp = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    conn.executemany('UPDATE train_runs SET deleting_at=? WHERE id=?', [(stamp, item) for item in ids]); conn.commit()
    return {'deleted': len(ids), 'ids': ids, 'deleting_at': stamp}


def changes(conn, project_id):
    current = conn.execute("SELECT id,revision FROM qa_samples WHERE project_id=? AND status='approved' ORDER BY id", (project_id,)).fetchall()
    active = db.row(conn, 'SELECT * FROM train_runs WHERE project_id=? AND in_use=1 AND deleting_at IS NULL', (project_id,))
    if not active: return {'since_version': None, 'pairs_changed': len(current)}
    frozen = {}
    frozen_examples = set()
    try:
        root = Path(json.loads(active['config']).get('data', ''))
        rows = (root / 'samples.jsonl').read_text().splitlines()
        for line in rows:
            sample = json.loads(line)
            if sample.get('derived_from'):
                frozen_examples.add(sample.get('sample_id'))
            else:
                frozen[sample.get('sample_id')] = sample.get('revision')
    except (OSError, ValueError):
        pass
    try:
        from .datasets import canonical_id
        now = {canonical_id(row['id']): row['revision'] for row in current}
    except Exception:
        now = {}
    changed = sum(1 for key, value in now.items() if frozen.get(key) != value)
    changed += sum(1 for key in frozen if key not in now)
    try:
        from . import prepare
        current_examples = set()
        for variant in db.rows(conn, "SELECT v.id,v.pair_id,v.pair_version FROM training_variants v JOIN qa_samples s ON s.id=v.pair_id WHERE v.project_id=? AND v.status='kept' AND s.status='approved'", (project_id,)):
            if variant['pair_version'] == prepare.version(qa.get_sample(conn, variant['pair_id'])):
                current_examples.add(canonical_id(variant['id']))
        changed += len(frozen_examples ^ current_examples)
    except (NameError, ValueError, workshop.NotFound):
        pass
    return {'since_version': active['version'], 'pairs_changed': changed}


def events(conn, project_id, run_id, after=0):
    get(conn, project_id, run_id)
    return [{**r, 'payload': json.loads(r['payload'])} for r in db.rows(conn,
            'SELECT seq,type,payload,created_at FROM train_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 2000', (run_id, after))]


def event(conn, run_id, kind, payload):
    encoded = json.dumps(payload, allow_nan=False)
    conn.execute('INSERT INTO train_events(run_id,seq,type,payload,created_at) VALUES (?,(SELECT COALESCE(MAX(seq),0)+1 FROM train_events WHERE run_id=?),?,?,?)',
                 (run_id, run_id, kind, encoded, db.now()))
    conn.commit()


def _folder(root, run_id):
    return Path(root)/'runs'/run_id


def _dataset(conn, root, project_id, dataset_id):
    row = db.row(conn, 'SELECT * FROM datasets WHERE id=? AND project_id=?', (dataset_id, project_id))
    if not row: raise workshop.NotFound('Dataset not found in this project.')
    folder = Path(row['path']).resolve().parent
    if not folder.is_relative_to((Path(root)/'datasets').resolve()): raise ValueError('Dataset is outside its storage folder.')
    path = folder/'training-manifest.json'
    if not path.is_file(): raise ValueError('Export this again to train with it.')
    manifest = json.loads(path.read_text())
    if manifest.get('schema_version') != '2.0' or not manifest.get('split_policy'): raise ValueError('Export this again with the current split rules.')
    canonical = folder/'samples.jsonl'
    if not canonical.exists() or hashlib.sha256(canonical.read_bytes()).hexdigest() != manifest['canonical_sha256']:
        raise ValueError('The canonical dataset changed after export. Export it again.')
    for name in ('train.jsonl', 'valid.jsonl'):
        asset = manifest.get('files', {}).get(name)
        if not asset or not (folder/name).is_file(): raise ValueError(f'The dataset has no {name}. More independent reviewed pairs are needed.')
        if hashlib.sha256((folder/name).read_bytes()).hexdigest() != asset['sha256']: raise ValueError(f'{name} changed after export. Export it again.')
    return folder, manifest


def _configuration(conn, root, project_id, body):
    projects.get(conn, project_id)
    if platform.system() != 'Darwin' or platform.machine() != 'arm64': raise ValueError('Training needs a Mac with Apple silicon.')
    if body.get('profile', 'direct') != 'direct': raise ValueError('Training explanations needs a verified renderer first. Choose final answers for now.')
    if not PYTHON.exists(): raise ValueError('Install app/trainer/requirements.txt in app/trainer/.venv first.')
    model = model_info(body['model'])
    if not model['cached']: raise ValueError('The selected model is not downloaded in the local Hugging Face cache.')
    dataset_id = body.get('dataset_id')
    if not dataset_id:
        from . import datasets
        result = datasets.export_dataset(conn, Path(root) / 'datasets', 'Training dataset', project_id,
                                         outputs=['finetune'], profile='direct')
        dataset_id = result['id']
        body['dataset_id'] = dataset_id
    folder, manifest = _dataset(conn, root, project_id, dataset_id)
    batch = int(body.get('batch_size', 4)); epochs = float(body.get('epochs', 3)); lr = float(body.get('learning_rate', 1e-5))
    if not 1 <= batch <= 8 or not 0 < epochs <= 10 or not math.isfinite(lr) or not 0 < lr <= 0.001:
        raise ValueError('Use batch 1–8, epochs above 0 and at most 10, and a learning rate above 0 and at most 0.001.')
    count = manifest['files']['train.jsonl']['lines']
    iters = int(body.get('iters') or math.ceil(epochs*count/batch))
    if not 2 <= iters <= 10000: raise ValueError('Use between 2 and 10000 training steps.')
    has_variants = bool(manifest.get('statistics', {}).get('by_origin', {}).get('variants', 0))
    default_lr = 5e-5 if has_variants else 1e-5
    default_layers = model.get('num_layers', 16) if has_variants else 16
    default_epochs = 2.8 if has_variants else 3
    if 'learning_rate' not in body: lr = default_lr
    if 'epochs' not in body: epochs = default_epochs
    return {'model': model['id'], 'base_path': model['base_path'], 'base_revision': model['revision'],
            'dataset_id': body['dataset_id'], 'data': str(folder), 'canonical_sha256': manifest['canonical_sha256'],
            'rendered_sha256': {k: manifest['files'][k]['sha256'] for k in ('train.jsonl', 'valid.jsonl')},
            'language': projects.get(conn, project_id)['language'], 'identity': manifest.get('identity', ''), 'identity_sha256': manifest.get('identity_sha256'),
            'profile': 'direct', 'engine_version': '0.32.2', 'epochs': epochs, 'batch_size': batch,
            'learning_rate': lr, 'iters': int(body.get('iters') or math.ceil(epochs*count/batch)), 'max_seq_length': 2048,
            'num_layers': default_layers, 'training_variants': has_variants,
            'seed': 0, 'eval_every': min(25, iters), 'thinking': False, 'loss_mask': 'assistant_final_only'}


def command(config_path, mode):
    return [str(PYTHON), str(WORKER), '--config', str(config_path), '--mode', mode]


def answer_variants(root, rows, url, connection, *, train_model=None):
    """Run teacher answers in the isolated MLX worker while holding the shared GPU lease."""
    import uuid
    if not rows:
        return {}
    model = model_info(train_model or CATALOG[0]['id'])
    if not model['cached']:
        raise ValueError('Download Qwen3 4B in Train before preparing examples.')
    lease = 'prepare:' + uuid.uuid4().hex
    gpu.reserve(lease)
    try:
        with gpu.exclusive(lease, url):
            answers = {}
            for offset in range(0, len(rows), 8):
                with tempfile.TemporaryDirectory(prefix='academy-prepare-') as directory:
                    path = Path(directory) / 'config.json'
                    path.write_text(json.dumps({'base_path': model['base_path'], 'rows': rows[offset:offset+8]}))
                    result = subprocess.run(command(path, 'variants'), capture_output=True, text=True, timeout=300, env=_environment())
                    messages = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                    payload = next((item['payload'] for item in messages if item['type'] == 'result'), None)
                    if result.returncode or payload is None:
                        error = next((item['payload'].get('message') for item in messages if item['type'] == 'error'), result.stderr[-1000:])
                        raise ValueError(error or 'The local model could not write the answers.')
                    answers.update(payload['answers'])
            return answers
    finally:
        gpu.release(lease)


def _environment():
    return {**os.environ, 'HF_HUB_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false', 'PYTHONUNBUFFERED': '1'}


def preflight(conn, root, project_id, body):
    try:
        config = _configuration(conn, root, project_id, body)
        with tempfile.TemporaryDirectory(prefix='academy-preflight-') as directory:
            path = Path(directory)/'config.json'; path.write_text(json.dumps(config))
            result = subprocess.run(command(path, 'preflight'), capture_output=True, text=True, timeout=90, env=_environment())
            messages = [json.loads(l) for l in result.stdout.splitlines() if l.strip()]
            payload = next((m['payload'] for m in messages if m['type'] == 'result'), None)
            if result.returncode or payload is None:
                reason = next((m['payload'].get('message') for m in messages if m['type'] == 'error'), result.stderr[-1000:])
                raise ValueError(reason or 'The dataset could not be tokenized.')
        if payload['train_count'] < config['batch_size'] or payload['valid_count'] < config['batch_size']:
            raise ValueError('Training and validation each need at least one full batch of independent pairs. Choose a smaller batch or add more reviewed data.')
        warnings = [f"{payload['too_long']} pair(s) would have their answer cut at 2048 tokens."] if payload['too_long'] else []
        manifest_path = db.row(conn, 'SELECT manifest_path FROM datasets WHERE id=? AND project_id=?', (body['dataset_id'], project_id))
        if manifest_path:
            try:
                manifest = json.loads(Path(manifest_path['manifest_path']).read_text())
                answer_models = sorted({e.get('answer_model') for e in manifest.get('entries', []) if e.get('answer_model')})
                if answer_models and body.get('model') not in answer_models:
                    names = ', '.join(m.rsplit('/', 1)[-1] for m in answer_models)
                    warnings.append(f"These examples were written by {names}. Training another model on them teaches it their way of writing.")
            except (OSError, ValueError):
                pass  # Legacy or unreadable metadata never blocks a valid training run.
        return {'ready': True, 'errors': [], 'warnings': warnings, **payload, 'config': config}
    except (ValueError, subprocess.TimeoutExpired) as exc:
        return {'ready': False, 'errors': [str(exc)], 'warnings': []}


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value): raise ValueError('The worker reported an invalid number.')
    if isinstance(value, dict):
        for v in value.values(): _finite(v)
    if isinstance(value, list):
        for v in value: _finite(v)


def supervise(conn, run_id, folder, config, mode='train'):
    path = folder / ('run.json' if mode == 'train' else 'comparison.json')
    path.write_text(json.dumps(config, indent=2))
    queue_out = queue.Queue()
    process = subprocess.Popen(command(path, mode), stdout=subprocess.PIPE, stderr=(folder/f'{mode}.log').open('a'),
                               text=True, bufsize=1, start_new_session=True, env=_environment())
    with _process_lock: _processes[run_id] = process
    def read():
        for line in process.stdout: queue_out.put(line)
        queue_out.put(None)
    threading.Thread(target=read, daemon=True).start()
    result = None
    try:
        while True:
            runs.check()
            try: raw = queue_out.get(timeout=0.15)
            except queue.Empty:
                if process.poll() is not None and not process.stdout: break
                continue
            if raw is None: break
            if len(raw) > 100000: raise ValueError('The worker emitted an oversized event.')
            try:
                item = json.loads(raw)
            except ValueError:
                event(conn, run_id, 'log', {'message': raw[:2000]}); continue
            kind, payload = item.get('type'), item.get('payload')
            if not isinstance(payload, dict) or kind not in ('accepted', 'progress', 'checkpoint', 'answer', 'recall_draft', 'result', 'error'):
                raise ValueError('The worker emitted an invalid event.')
            _finite(payload)
            event(conn, run_id, kind, payload)
            if kind == 'error': raise ValueError(payload.get('message', 'Training failed.'))
            if kind == 'checkpoint':
                conn.execute('UPDATE train_runs SET best_val_loss=?,best_iteration=? WHERE id=?', (payload['val_loss'], payload['iteration'], run_id)); conn.commit()
            if kind == 'result': result = payload
        code = process.wait(timeout=10)
        if code != 0 or result is None: raise ValueError('The worker stopped before it finished. See the run log.')
        if mode == 'train' and not (folder/'adapters/best/adapters.safetensors').is_file(): raise ValueError('The worker did not produce a validated adapter.')
        return result
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=KILL_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
        process.stdout.close()
        with _process_lock: _processes.pop(run_id, None)


def launch(conn, root, project_id, body, url, connection):
    # Starting a training run makes its model the project's shared Prepare/Train choice.
    projects.update(conn, project_id, train_model=body['model'])
    auto_dataset = not body.get('dataset_id')
    checked = preflight(conn, root, project_id, body)
    if not checked['ready']: raise ValueError(' '.join(checked['errors']))
    run_id = db.new_id('trn'); config = checked['config']
    folder = _folder(root, run_id); folder.mkdir(parents=True)
    data = folder/'data'; data.mkdir()
    # Immutable, validated rendering is tiny. Never copy base weights.
    for name in ('train.jsonl', 'valid.jsonl', 'test.jsonl', 'samples.jsonl'):
        source = Path(config['data'])/name
        if source.is_file():
            shutil.copyfile(source, data/name)
            if name in config['rendered_sha256'] and hashlib.sha256((data/name).read_bytes()).hexdigest() != config['rendered_sha256'][name]:
                raise ValueError('The dataset changed during preparation. Export it again.')
    config.update(data=str(data), output=str(folder/'adapters'), auto_dataset=auto_dataset)
    version = conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM train_runs WHERE project_id=?', (project_id,)).fetchone()[0]
    conn.execute('INSERT INTO train_runs(id,project_id,dataset_id,model,config,status,created_at,version) VALUES (?,?,?,?,?,?,?,?)',
                 (run_id, project_id, config['dataset_id'], config['model'], json.dumps(config), 'preparing', db.now(), version))
    conn.commit()
    return _start(conn, root, project_id, run_id, config, url, connection)


def _start(conn, root, project_id, run_id, config, url, connection, continuing=False):
    folder = _folder(root, run_id)
    for name, expected in config['rendered_sha256'].items():
        if not (folder/'data'/name).is_file() or hashlib.sha256((folder/'data'/name).read_bytes()).hexdigest() != expected:
            raise ValueError('The frozen training data changed. Start again from a new export.')
    lease = run_id + ':' + secrets.token_hex(6)
    gpu.reserve(lease)
    try:
        folder = _folder(root, run_id)
        if continuing:
            conn.execute("UPDATE train_runs SET status='preparing',config=?,error='',finished_at=NULL WHERE id=?", (json.dumps(config), run_id))
        else:
            exists = conn.execute('SELECT 1 FROM train_runs WHERE id=?', (run_id,)).fetchone()
            if exists:
                conn.execute("UPDATE train_runs SET status='preparing',config=? WHERE id=?", (json.dumps(config), run_id))
            else:
                version = conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM train_runs WHERE project_id=?', (project_id,)).fetchone()[0]
                conn.execute("INSERT INTO train_runs(id,project_id,dataset_id,model,config,status,created_at,version) VALUES (?,?,?,?,?,'preparing',?,?)",
                             (run_id, project_id, config['dataset_id'], config['model'], json.dumps(config), db.now(), version))
        conn.commit()
        (folder/'run.json').write_text(json.dumps(config, indent=2))
        (folder/'run.yaml').write_text(json.dumps(config, indent=2))  # JSON is valid YAML, no backend YAML dependency
        (folder/'command.txt').write_text(' '.join(command(folder/'run.json', 'train')) + '\n')
        def work():
            c = conn
            try:
                c = connection()
                with gpu.exclusive(lease, url) as unloaded:
                    event(c, run_id, 'log', {'message': 'Ollama memory released. Generation resumes on its next request.', 'unloaded': unloaded})
                    c.execute("UPDATE train_runs SET status='training' WHERE id=?", (run_id,)); c.commit()
                    result = supervise(c, run_id, folder, config)
                    c.execute('UPDATE train_runs SET in_use=0 WHERE project_id=?', (project_id,))
                    c.execute("UPDATE train_runs SET status='finished',finished_at=?,in_use=1 WHERE id=?", (db.now(), run_id)); c.commit()
                    return result
            except runs.Stopped:
                c.execute("UPDATE train_runs SET status='stopped',finished_at=? WHERE id=?", (db.now(), run_id)); c.commit()
                event(c, run_id, 'cancelled', {'message': 'Stopped. The last saved adapter is kept.'}); raise
            except Exception as exc:
                c.execute("UPDATE train_runs SET status='failed',error=?,finished_at=? WHERE id=?", (str(exc), db.now(), run_id)); c.commit()
                event(c, run_id, 'error', {'message': str(exc)}); raise
            finally: gpu.release(lease)
        runs.launch(project_id, 'training', run_id, 'Training your model', {'view': 'train', 'params': {'run_id': run_id}}, work,
                    note=lambda _: 'Training finished. Compare it with the base model.')
    except BaseException:
        gpu.release(lease)
        conn.execute("UPDATE train_runs SET status='failed',error='Training could not start',finished_at=? WHERE id=? AND status='preparing'", (db.now(), run_id))
        conn.commit()
        raise
    return get(conn, project_id, run_id)


def stop(conn, project_id, run_id):
    item = get(conn, project_id, run_id)
    if item['status'] not in ('preparing', 'training'): raise ValueError('This training is not running.')
    runs.stop('training', run_id)
    return get(conn, project_id, run_id)


def continue_run(conn, root, project_id, run_id, url, connection):
    item = get(conn, project_id, run_id)
    if item['status'] not in ('stopped', 'failed'): raise ValueError('Only stopped or failed training can continue.')
    folder = _folder(root, run_id)
    checkpoint = folder/'adapters/adapters.safetensors'
    if not checkpoint.is_file(): raise ValueError('There is no saved checkpoint to continue from. Start a new training.')
    config = item['config']; config['resume_adapter_file'] = str(checkpoint)
    # The checkpoint is written at every progress report, so the last reported step is where it stands.
    trained = [e['payload']['iteration'] for e in events(conn, project_id, run_id) if e['type'] == 'progress' and 'train_loss' in e['payload']]
    config['start_iteration'] = max(trained, default=0)
    if config['start_iteration'] >= config.get('iters', float('inf')): raise ValueError('This training already ran all its steps. Start a new training.')
    config['optimizer_restarted'] = True
    config['previous_best_val_loss'] = item['best_val_loss']
    config['previous_best_iteration'] = item['best_iteration']
    # Existing snapshots and validation history stay immutable; this is another segment.
    return _start(conn, root, project_id, run_id, config, url, connection, continuing=True)


def recover(conn):
    conn.execute("UPDATE train_runs SET status='failed',error='Stopped when the app closed',finished_at=? WHERE status IN ('preparing','training')", (db.now(),))
    conn.commit()


def _shareable(value):
    """Drops every absolute path, at any depth."""
    if isinstance(value, dict): return {k: _shareable(v) for k, v in value.items() if not (isinstance(v, str) and v.startswith(('/', '~')))}
    if isinstance(value, list): return [_shareable(v) for v in value if not (isinstance(v, str) and v.startswith(('/', '~')))]
    return value


def download(conn, root, project_id, run_id):
    run = get(conn, project_id, run_id); folder = _folder(root, run_id)
    if not (folder/'adapters/best/adapters.safetensors').is_file(): raise ValueError('There is no validated adapter to download yet.')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        # Paths of this machine stay here: the zip names the base model by repository and revision.
        for p in sorted((folder/'adapters/best').glob('*')):
            if p.name == 'adapter_config.json':
                adapter = _shareable(json.loads(p.read_text())); adapter['model'] = run['model']
                archive.writestr('adapter/'+p.name, json.dumps(adapter, indent=2))
            elif p.is_file(): archive.write(p, 'adapter/'+p.name)
        archive.writestr('run.yaml', json.dumps(_shareable(run['config']), indent=2))
        card = {'base': run['model'], 'revision': run['config']['base_revision'], 'dataset_sha256': run['config']['canonical_sha256'],
                'best_validation_loss': run['best_val_loss'], 'quality': 'Not measured automatically. Validation loss is not correctness.',
                'profile': 'direct', 'thinking': False, 'release': False}
        archive.writestr('model-card.json', json.dumps(card, indent=2))
    return buffer.getvalue()


def comparison(conn, project_id, run_id):
    get(conn, project_id, run_id)
    rows = db.rows(conn, "SELECT id,question,set_name,left_answer AS left,right_answer AS right,choice,expected,base_on_left FROM train_comparisons WHERE run_id=? ORDER BY created_at,id", (run_id,))
    aliases = {'recall': 'studied', 'held_out': 'new', 'manual': 'yours'}
    for row in rows: row['set_name'] = aliases.get(row['set_name'], row['set_name'])
    groups = ('studied', 'new', 'general', 'yours')
    sets = {name: {'count': sum(r['set_name'] == name for r in rows)} for name in groups}
    judged = [r for r in rows if r['set_name'] != 'try']
    revealed = bool(judged) and all(r['choice'] is not None for r in judged)
    for row in rows:
        row.pop('base_on_left', None)
    identities = {}
    scores = {name: {'better': 0, 'worse': 0, 'same': 0, 'both_wrong': 0} for name in groups}
    if revealed:
        identities = {r['id']: ('left' if r['base_on_left'] else 'right') for r in db.rows(conn, 'SELECT id,base_on_left FROM train_comparisons WHERE run_id=?', (run_id,))}
        for row in judged:
            group = scores.setdefault(row['set_name'], {'better': 0, 'worse': 0, 'same': 0, 'both_wrong': 0})
            choice = 'both_right' if row['choice'] == 'same' else row['choice']
            if choice == 'both_right': group['same'] += 1
            elif choice == 'both_wrong': group['both_wrong'] += 1
            else:
                trained_side = 'right' if identities[row['id']] == 'left' else 'left'
                group['better' if choice == trained_side else 'worse'] += 1
        for name in groups: sets[name].update(scores[name])
    tries = []
    for row, raw in zip(rows, db.rows(conn, "SELECT id,base_on_left FROM train_comparisons WHERE run_id=? ORDER BY created_at,id", (run_id,))):
        if row['set_name'] == 'try':
            tries.append({**row, 'before': row['left'] if raw['base_on_left'] else row['right'], 'after': row['right'] if raw['base_on_left'] else row['left']})
    return {'items': judged, 'tries': tries, 'sets': sets,
            'revealed': revealed, 'base_side': identities,
            'recall_drafts': db.rows(conn, 'SELECT id,source_question,question,approved FROM train_recall WHERE run_id=? ORDER BY created_at,id', (run_id,)),
            'running': runs.is_running('comparison', run_id)}


def choose(conn, project_id, run_id, item_id, choice):
    get(conn, project_id, run_id)
    if choice == 'both_right': choice = 'same'
    if choice not in ('left', 'right', 'same', 'both_wrong', None): raise ValueError('Unknown comparison choice.')
    changed = conn.execute('UPDATE train_comparisons SET choice=? WHERE id=? AND run_id=?', (choice, item_id, run_id)).rowcount
    if not changed: raise workshop.NotFound('Comparison item not found.')
    conn.commit()
    return comparison(conn, project_id, run_id)


def start_compare(conn, root, project_id, run_id, body, url, connection, try_only=False, llm=None):
    run = get(conn, project_id, run_id)
    if run['status'] != 'finished': raise ValueError('Finish training before comparing it.')
    folder = _folder(root, run_id)
    supplied = body.get('questions') or ([body['question']] if body.get('question') else [])
    questions = []
    if supplied:
        if len(supplied) > 6 or any(not q.strip() or len(q)>2000 for q in supplied): raise ValueError('Use up to 6 short questions.')
    if try_only:
        questions = [{'id': db.new_id('cmp'), 'question': q, 'set_name': 'try', 'expected': ''} for q in supplied]
    else:
        questions = [{'id': db.new_id('cmp'), 'question': q, 'set_name': 'yours', 'expected': ''} for q in supplied]
        data = folder/'data'
        # Studied facts are sampled across kinds and rewritten by the project's chosen model.
        train_file, samples_file = data/'train.jsonl', data/'samples.jsonl'
        if train_file.is_file() and samples_file.is_file():
            kinds = {}
            for line in samples_file.read_text().splitlines():
                if line.strip():
                    sample = json.loads(line); kinds[sample.get('sample_id')] = sample.get('kind', '')
            candidates = []
            for line in train_file.read_text().splitlines():
                if not line.strip(): continue
                sample = json.loads(line); msgs = sample.get('messages', [])
                user = next((m for m in msgs if m.get('role') == 'user'), None)
                assistant = next((m for m in reversed(msgs) if m.get('role') == 'assistant'), None)
                if user and assistant:
                    q = user.get('content', ''); a = assistant.get('content', '')
                    candidates.append({'question': q, 'answer': a, 'kind': sample.get('kind', kinds.get(sample.get('sample_id'), 'known'))})
            random_order = sorted(candidates, key=lambda _: secrets.randbits(64))
            picked = []
            for kind in ('known', 'false_premise', 'not_known'):
                item = next((x for x in random_order if x['kind'] == kind and x not in picked), None)
                if item: picked.append(item)
            for item in random_order:
                if len(picked) >= 5: break
                if item not in picked: picked.append(item)
            for item in picked:
                q = item['question']
                if llm is not None:
                    from . import agents
                    schema = {'type':'object','properties':{'question':{'type':'string'}},'required':['question']}
                    varied = llm.complete_json(agents.prompt('question_varier', 'compare_rewrite', question=q, answer=item['answer']), schema, temperature=.5)
                    q = str(varied.get('question') or q).strip()
                questions.append({'id': db.new_id('cmp'), 'question': q, 'set_name': 'studied', 'expected': item['answer']})
        for q in held_out(data):
            line = next((json.loads(x) for x in (data/'test.jsonl').read_text().splitlines() if x.strip() and json.loads(x)['messages'][-2]['content'] == q), None)
            expected = line['messages'][-1]['content'] if line else ''
            if not any(qa.questions_similar(q, prior['question']) for prior in questions):
                questions.append({'id': db.new_id('cmp'), 'question': q, 'set_name': 'new', 'expected': expected})
        language = projects.get(conn, project_id)['language']
        general = ['Quanto é 17 vezes 3?', 'Qual é a capital da França?', 'Por que o céu parece azul?'] if language.startswith('pt') else ['What is 17 times 3?', 'What is the capital of France?', 'Why does the sky look blue?']
        for q in general:
            if not any(qa.questions_similar(q, prior['question']) for prior in questions):
                questions.append({'id': db.new_id('cmp'), 'question': q, 'set_name': 'general', 'expected': ''})
        unique = []
        for question in questions:
            if not any(qa.questions_similar(question['question'], prior['question'], question.get('expected', ''), prior.get('expected', '')) for prior in unique):
                unique.append(question)
        questions = unique
        if not questions: raise ValueError('Could not prepare questions. Add some questions and try again.')
    lease = run_id + ':' + secrets.token_hex(6)
    gpu.reserve(lease)
    def work():
        try:
            c=connection()
            with gpu.exclusive(lease, url):
                config = {**run['config'], 'adapter_path': str(folder/'adapters/best'), 'questions': questions}
                before = c.execute('SELECT COALESCE(MAX(seq),0) FROM train_events WHERE run_id=?', (run_id,)).fetchone()[0]
                supervise(c, run_id, folder, config, mode='compare')
                answers = {}
                for item in events(c, project_id, run_id, before):
                    if item['type'] == 'answer':
                        p=item['payload']; answers.setdefault(p['item_id'], {})[p['model']] = p['answer']
                for question in questions:
                    pair = answers.get(question['id'], {})
                    if 'base' not in pair or 'trained' not in pair: raise ValueError('The comparison did not produce both answers.')
                    left = bool(secrets.randbits(1))
                    c.execute('INSERT INTO train_comparisons(id,run_id,question,set_name,left_answer,right_answer,base_on_left,created_at,expected) VALUES (?,?,?,?,?,?,?,?,?)',
                              (question['id'],run_id,question['question'],question['set_name'],pair['base' if left else 'trained'],pair['trained' if left else 'base'],int(left),db.now(),question.get('expected','')))
                c.commit()
                return {'count': len(questions)}
        finally: gpu.release(lease)
    try:
        entry = runs.launch(project_id, 'comparison', run_id, 'Comparing your model', {'view': 'compare', 'params': {'run_id': run_id}}, work,
                            note=lambda result: f"{result['count']} questions ready to compare.")
        return runs.public(entry)
    except BaseException:
        gpu.release(lease); raise



def held_out(data, most=6):
    """Test questions taken in turn from each kind of pair, so an "I don't know" learned too well shows next to known answers."""
    test = data/'test.jsonl'
    if not test.is_file(): return []
    kinds = {}
    if (data/'samples.jsonl').is_file():
        for line in (data/'samples.jsonl').read_text().splitlines():
            if not line.strip(): continue
            sample = json.loads(line)
            asked = next((m for m in sample['messages'] if m['role'] == 'user'), None)
            if asked: kinds[''.join(p.get('text', '') for p in asked['content'])] = sample.get('kind', '')
    by_kind = {}
    for line in test.read_text().splitlines():
        if line.strip():
            question = json.loads(line)['messages'][-2]['content']
            by_kind.setdefault(kinds.get(question, ''), []).append(question)
    picked, lists = [], [by_kind[k] for k in sorted(by_kind)]
    while len(picked) < most and any(lists):
        for group in lists:
            if group and len(picked) < most: picked.append(group.pop(0))
    return picked


def review_recall(conn, project_id, run_id, item_id, question, approved):
    get(conn, project_id, run_id)
    if not question.strip() or len(question)>2000: raise ValueError('Write a short paraphrase of the training question.')
    changed = conn.execute('UPDATE train_recall SET question=?,approved=? WHERE id=? AND run_id=?', (question.strip(), int(approved), item_id, run_id)).rowcount
    if not changed: raise workshop.NotFound('Recall question not found.')
    conn.commit()
    return comparison(conn, project_id, run_id)


def draft_recall(conn, root, project_id, run_id, url, connection):
    run = get(conn, project_id, run_id)
    if run['status'] != 'finished': raise ValueError('Finish training before preparing its questions.')
    folder = _folder(root, run_id)
    examples = [json.loads(line)['messages'][-2]['content'] for line in (folder/'data/train.jsonl').read_text().splitlines()[:3] if line.strip()]
    questions = [{'id': db.new_id('rec'), 'question': q} for q in examples]
    lease = run_id + ':' + secrets.token_hex(6)
    gpu.reserve(lease)
    def work():
        try:
            c = connection()
            with gpu.exclusive(lease, url):
                before = c.execute('SELECT COALESCE(MAX(seq),0) FROM train_events WHERE run_id=?', (run_id,)).fetchone()[0]
                supervise(c, run_id, folder, {**run['config'], 'task': 'recall', 'questions': questions}, mode='compare')
                for e in events(c, project_id, run_id, before):
                    if e['type'] == 'recall_draft':
                        p = e['payload']
                        c.execute('INSERT INTO train_recall(id,run_id,source_question,question,approved,created_at) VALUES (?,?,?,?,0,?)',
                                  (p['item_id'], run_id, p['source_question'], p['question'], db.now()))
                c.commit()
                return {'count': len(questions)}
        finally: gpu.release(lease)
    try:
        entry = runs.launch(project_id, 'comparison', run_id, 'Preparing questions to review', {'view': 'compare', 'params': {'run_id': run_id}}, work,
                            note=lambda _: 'Questions ready. Check that each asks the same thing in other words.')
        return runs.public(entry)
    except BaseException:
        gpu.release(lease); raise
