"""One GPU lease shared by local generation and ML workers; Ollama stays available."""
import threading
import time
from contextlib import contextmanager

import httpx
from . import runs

_condition = threading.Condition()
_owner = None
_readers = 0


def status():
    with _condition:
        return {'owner': _owner, 'generation_calls': _readers, 'generation_waiting': _owner is not None}


def reserve(owner):
    global _owner
    with _condition:
        if _owner is not None: raise runs.Busy('Another training or comparison is using the GPU.')
        _owner = owner


def release(owner):
    global _owner
    with _condition:
        if _owner == owner:
            _owner = None
            _condition.notify_all()


@contextmanager
def generation():
    """Existing generation drains before ML starts. New calls wait and can be stopped."""
    global _readers
    with _condition:
        try:
            while _owner is not None:
                runs.set_waiting(True)
                runs.check()
                _condition.wait(0.2)
            runs.check()
            _readers += 1
        finally:
            runs.set_waiting(False)
    try:
        yield
    finally:
        with _condition:
            _readers -= 1
            _condition.notify_all()


def unload_ollama(url, timeout=30):
    """Release weights, not the service or the selected model. Never restore a stale large model eagerly."""
    try:
        with httpx.Client(base_url=url.rstrip('/'), timeout=timeout) as client:
            response = client.get('/api/ps')
            response.raise_for_status()
            models = response.json().get('models', [])
            names = [m.get('name') or m['model'] for m in models]
            for name in names:
                response = client.post('/api/generate', json={'model': name, 'keep_alive': 0, 'stream': False})
                response.raise_for_status()
            deadline = time.monotonic() + timeout
            while True:
                runs.check()
                response = client.get('/api/ps'); response.raise_for_status()
                if not response.json().get('models'): return names
                if time.monotonic() >= deadline: raise RuntimeError('Ollama did not release its models. Training did not start.')
                time.sleep(0.2)
    except httpx.ConnectError:
        # A stopped Ollama needs no unloading; never start/kill its daemon behind the operator's back.
        return []
    except httpx.HTTPError as exc:
        raise RuntimeError(f'Could not release Ollama memory: {exc}') from exc


@contextmanager
def exclusive(owner, url):
    try:
        with _condition:
            if _owner != owner: raise runs.Busy('The GPU reservation changed.')
            deadline = time.monotonic() + 620
            while _readers:
                runs.check()
                if time.monotonic() > deadline: raise RuntimeError('A model call did not finish. Stop it before training.')
                _condition.wait(0.2)
        runs.check()
        unloaded = unload_ollama(url)
        yield unloaded
    finally:
        release(owner)
