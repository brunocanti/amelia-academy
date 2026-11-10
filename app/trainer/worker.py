"""Isolated MLX worker. stdout is versioned JSONL; library logs go to stderr."""
import argparse
import contextlib
import json
import math
import shutil
import sys
import time
from pathlib import Path

EVENTS = sys.stdout
sys.stdout = sys.stderr


def emit(kind, **payload):
    EVENTS.write(json.dumps({'type': kind, 'payload': payload}, ensure_ascii=False, allow_nan=False) + '\n')
    EVENTS.flush()


def direct_tokenizer(tokenizer):
    class Direct:
        def __getattr__(self, key): return getattr(tokenizer, key)
        def apply_chat_template(self, *args, **kwargs):
            kwargs['enable_thinking'] = False
            kwargs.setdefault('return_dict', False)
            return tokenizer.apply_chat_template(*args, **kwargs)
    return Direct()


def inspect_data(config):
    from transformers import AutoTokenizer
    tokenizer = direct_tokenizer(AutoTokenizer.from_pretrained(config['base_path'], local_files_only=True, trust_remote_code=False))
    counts, lengths, too_long = {}, [], 0
    for split, filename in [('train', 'train.jsonl'), ('validation', 'valid.jsonl'), ('test', 'test.jsonl')]:
        path = Path(config['data']) / filename
        counts[split] = 0
        if not path.exists(): continue
        for line in path.read_text().splitlines():
            if not line.strip(): continue
            messages = json.loads(line)['messages']
            if not messages or messages[-1]['role'] != 'assistant': raise ValueError('A training line has no final answer.')
            tokens = tokenizer.apply_chat_template(messages, tokenize=True)
            offset = len(tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True))
            if offset >= len(tokens): raise ValueError('The template leaves no answer tokens to learn.')
            if offset >= config['max_seq_length']: raise ValueError('A question would be cut before its answer. Shorten it or increase the sequence length.')
            if tokens[:offset] != tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True):
                raise ValueError('The template does not align with the answer mask.')
            too_long += len(tokens) > config['max_seq_length']
            lengths.append(len(tokens)); counts[split] += 1
    return {'train_count': counts['train'], 'valid_count': counts['validation'], 'test_count': counts['test'],
            'max_tokens': max(lengths, default=0), 'too_long': too_long, 'thinking': False, 'loss_mask': 'assistant_final_only'}


def train(config):
    import mlx.core as mx
    from mlx.utils import tree_flatten
    from mlx_lm import load
    from mlx_lm.lora import CONFIG_DEFAULTS, train_model
    from mlx_lm.tuner.callbacks import TrainingCallback
    from mlx_lm.tuner.datasets import load_dataset
    from types import SimpleNamespace
    import mlx_lm
    if mlx_lm.__version__ != '0.32.2': raise ValueError('This worker needs mlx-lm 0.32.2.')
    output = Path(config['output']); output.mkdir(parents=True, exist_ok=True)
    start = int(config.get('start_iteration') or 0)  # a continued run counts on from where it stopped
    if not 0 <= start < config['iters']: raise ValueError('This training already ran all its steps.')
    args = SimpleNamespace(**{**CONFIG_DEFAULTS, 'model': config['base_path'], 'data': config['data'], 'train': True,
        'adapter_path': str(output), 'iters': config['iters'] - start, 'batch_size': config['batch_size'],
        'learning_rate': config['learning_rate'], 'num_layers': config['num_layers'], 'seed': config['seed'],
        'steps_per_report': min(5, config['iters'] - start), 'steps_per_eval': config['eval_every'], 'save_every': config['eval_every'],
        'val_batches': -1, 'max_seq_length': config['max_seq_length'], 'grad_checkpoint': True, 'mask_prompt': True,
        'hf_dataset': None, 'resume_adapter_file': config.get('resume_adapter_file')})
    model, tokenizer = load(config['base_path'])
    tokenizer = direct_tokenizer(tokenizer)
    args.num_layers = min(args.num_layers, len(model.layers))
    train_set, valid_set, _ = load_dataset(args, tokenizer)
    started = time.monotonic()
    class Report(TrainingCallback):
        best = config.get('previous_best_val_loss') if config.get('previous_best_val_loss') is not None else float('inf')
        best_iteration = config.get('previous_best_iteration')
        def on_train_loss_report(self, info):
            if not math.isfinite(info['train_loss']): raise ValueError('Training produced an invalid loss.')
            mx.save_safetensors(str(output / 'adapters.safetensors'), dict(tree_flatten(model.trainable_parameters())))
            emit('progress', **{**info, 'iteration': info['iteration'] + start})
        def on_val_loss_report(self, info):
            if not math.isfinite(info['val_loss']): raise ValueError('Validation produced an invalid loss.')
            info = {**info, 'iteration': info['iteration'] + start}
            emit('progress', **info)
            # Validation runs before the next step. Keep the actual current weights, not a later checkpoint.
            if info['iteration'] > 0 and info['val_loss'] < self.best:
                self.best = info['val_loss']; self.best_iteration = info['iteration']
                best = output / 'best'; best.mkdir(exist_ok=True)
                mx.save_safetensors(str(best / 'adapters.safetensors'), dict(tree_flatten(model.trainable_parameters())))
                shutil.copyfile(output / 'adapter_config.json', best / 'adapter_config.json')
                emit('checkpoint', iteration=self.best_iteration, val_loss=self.best, path='best/adapters.safetensors')
    report = Report()
    emit('accepted', engine_version=mlx_lm.__version__, base_revision=config['base_revision'])
    train_model(args, model, train_set, valid_set, report)
    if report.best_iteration is None: raise ValueError('No trained checkpoint was validated. Run at least two steps.')
    emit('result', seconds=round(time.monotonic()-started, 2), peak_gb=mx.get_peak_memory()/1e9,
         best_iteration=report.best_iteration, best_val_loss=report.best)


def compare(config):
    import mlx.core as mx
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    identity = config.get('identity')
    if config.get('task') == 'recall':
        model, tokenizer = load(config['base_path'])
        tokenizer = direct_tokenizer(tokenizer)
        for item in config['questions']:
            instruction = ('Rewrite the following question in different words, with exactly the same meaning. '
                           'Use its original language. Do not answer it or add any details. Return only the new question.\n' +
                           'Required output language: ' + ('Portuguese' if config.get('language', 'en').startswith('pt') else 'English') + '. Never translate to another language.\nQuestion: ' + item['question'])
            prompt = tokenizer.apply_chat_template([{'role': 'user', 'content': instruction}], tokenize=False, add_generation_prompt=True)
            question = generate(model, tokenizer, prompt, max_tokens=120, sampler=make_sampler(temp=0)).strip()
            if not question or len(question) > 2000: raise ValueError('A paraphrase could not be drafted.')
            emit('recall_draft', item_id=item['id'], source_question=item['question'], question=question)
        emit('result', drafted=len(config['questions']))
        return
    for adapter, tag in [(None, 'base'), (config['adapter_path'], 'trained')]:
        model, tokenizer = load(config['base_path'], adapter_path=adapter)
        tokenizer = direct_tokenizer(tokenizer)
        for item in config['questions']:
            messages = ([{'role': 'system', 'content': identity}] if identity else []) + [{'role': 'user', 'content': item['question']}]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            started = time.monotonic()
            answer = generate(model, tokenizer, prompt, max_tokens=256, sampler=make_sampler(temp=0))
            emit('answer', item_id=item['id'], model=tag, answer=answer, seconds=time.monotonic()-started)
        del model
        mx.clear_cache()
    emit('result', compared=len(config['questions']))


def answer_variants(config):
    import mlx.core as mx
    from mlx_lm import load, batch_generate
    model, tokenizer = load(config['base_path'])
    tokenizer = direct_tokenizer(tokenizer)
    answers = {}
    rows = config['rows']
    for offset in range(0, len(rows), 8):
        batch = rows[offset:offset+8]
        prompts = []
        for item in batch:
            kind, evidence = item['kind'], item.get('quote', '')
            if kind == 'not_known':
                system = ('Answer the question from the nearby project passages if they contain the answer. '
                          'If they do not, reply exactly NOT_FOUND. Answer as an expert who simply knows. '
                          'Never mention a passage, text, source, file or paper.')
            elif kind == 'false_premise':
                system = ('Correct the wrong detail first, then answer in one to three sentences as an expert who simply knows. '
                          'Keep numbers, names and terms exact. Never mention a reference, passage, text, source, file or paper.')
            else:
                system = ('Answer in one to three sentences as an expert who simply knows. Keep every number, name and term exact. '
                          'Never mention a reference, passage, text, source, file or paper.')
            messages = [{'role':'system','content':system + ('\n\nReference:\n' + evidence if kind != 'not_known' else '\n\nNearby project passages:\n' + evidence)},
                        {'role':'user','content':('Wrong detail: ' + item.get('false_claim','') + '\n' if kind == 'false_premise' else '') + item['question']}]
            prompts.append(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True))
        generated = batch_generate(model, tokenizer, prompts, max_tokens=200)
        for item, answer in zip(batch, generated.texts):
            answers.setdefault(item['id'], []).append({**item, 'answer': answer.strip()})
        mx.clear_cache()
    emit('result', answers=answers)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--mode', choices=['preflight', 'train', 'compare', 'variants'], default='train')
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text())
        if args.mode == 'preflight': emit('result', **inspect_data(config))
        elif args.mode == 'train': train(config)
        elif args.mode == 'variants': answer_variants(config)
        else: compare(config)
    except Exception as exc:
        emit('error', message=str(exc)[:2000], error_type=type(exc).__name__)
        sys.exit(1)
