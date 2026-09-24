"""Shared, run-scoped Gemini stop signal. No keys or quota guesses are stored."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_current = ContextVar('gemini_run_limit', default=None)

class ServiceUnavailable(RuntimeError):
    def __init__(self, status, limit_kind=None, retry_after=None):
        self.status = int(status)
        descriptions = {401: 'authentication rejected', 403: 'access denied',
                        429: 'rate limit or quota exhausted'}
        self.limit_kind = limit_kind
        self.retry_after = retry_after
        detail = descriptions.get(self.status, 'service unavailable')
        if self.status == 429 and limit_kind in ('daily','per_minute'):
            detail = 'daily quota exhausted' if limit_kind=='daily' else 'per-minute rate limit reached'
        super().__init__(f'Gemini HTTP {self.status}: {detail}; new API work stopped for this run')

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
        raise ServiceUnavailable(status, (_current.get() or {}).get('limit_kind'), (_current.get() or {}).get('retry_after'))

def quota_details(response):
    """Extract fixed classifications, never provider messages or project IDs."""
    import re
    kind=None; retry=None
    try:
        error=response.json().get('error',{})
        ids=[]
        for item in error.get('details',[]):
            if not isinstance(item,dict): continue
            for violation in item.get('violations',[]):
                ids.append(str(violation.get('quotaId','')).lower())
            delay=item.get('retryDelay')
            if isinstance(delay,str) and re.fullmatch(r'\d+(?:\.\d+)?s',delay):
                retry=float(delay[:-1])
        if any('perday' in q or 'per_day' in q for q in ids):kind='daily'
        elif any('perminute' in q or 'per_minute' in q for q in ids):kind='per_minute'
    except (ValueError,AttributeError,TypeError):
        pass
    return kind,retry


def observe(status, response=None):
    state = _current.get()
    if state is not None and status in (401, 403, 429):
        state['status'] = status
        if status==429 and response is not None:
            state['limit_kind'],state['retry_after']=quota_details(response)
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
