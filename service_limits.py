"""Shared, run-scoped Gemini stop signal. No keys or quota guesses are stored."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_current = ContextVar('gemini_run_limit', default=None)

class ServiceUnavailable(RuntimeError):
    pass

@contextmanager
def session():
    token = _current.set({})
    try:
        yield
    finally:
        _current.reset(token)

def blocked():
    return bool((_current.get() or {}).get('status'))

def check():
    status = (_current.get() or {}).get('status')
    if status:
        raise ServiceUnavailable(f'Gemini HTTP {status}; new API work stopped for this run')

def observe(status):
    state = _current.get()
    if state is not None and status in (401, 403, 429):
        state['status'] = status
        check()


def before_request():
    """Space live requests across writer, narration and footage review."""
    check()
    state = _current.get()
    if state is None:
        return
    previous = state.get('last_request')
    if previous is not None:
        delay = 15 - (time.monotonic() - previous)
        if delay > 0:
            time.sleep(delay)
    state['last_request'] = time.monotonic()
