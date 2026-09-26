"""Shared, run-scoped Gemini stop signal. No keys or quota guesses are stored."""
from contextlib import contextmanager
from contextvars import ContextVar
import time
import json

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


def quota_deferral(error=None):
    """Return safe quota details from a typed exception or this run's signal."""
    if error is not None:
        if not isinstance(error, ServiceUnavailable) or error.status != 429:
            return None
        kind, retry = error.limit_kind, error.retry_after
    else:
        state = _current.get() or {}
        if state.get('status') != 429:
            return None
        kind, retry = state.get('limit_kind'), state.get('retry_after')
    return {'http_status': 429, 'limit_kind': kind or 'unknown', 'retry_after': retry}


def quota_message(quota):
    kind = quota.get('limit_kind')
    label = ('Gemini daily quota exhausted' if kind == 'daily' else
             'Gemini per-minute rate limit reached' if kind == 'per_minute' else
             'Gemini rate limit or quota exhausted')
    return label + ' (HTTP 429). No further Gemini requests will be made in this run.'

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


class ResponseFormatError(ValueError):
    """A successful HTTP response did not contain the requested JSON object."""


class TransientServiceError(RuntimeError):
    """A bounded request attempt ended with a temporary provider failure."""


def is_retryable(error):
    """Keep verified work when a provider could not complete its assessment.

    A negative editorial verdict or ordinary validation error is not a service
    failure. They must not be silently retained as publishable work.
    """
    import requests
    return isinstance(error, (ServiceUnavailable, ResponseFormatError,
                              TransientServiceError, requests.Timeout,
                              requests.ConnectionError))


def request_with_retry(send, max_attempts=3):
    """Retry only temporary server failures, respecting shared pacing and quota.

    ``send`` owns its call budget and is invoked for every actual request. A
    retry cannot bypass authentication, quota, or a caller's remaining budget.
    """
    max_attempts = max(1, min(3, int(max_attempts)))
    for attempt in range(max_attempts):
        before_request()
        response = send()
        observe(response.status_code, response)
        if response.status_code not in (502, 503, 504) or attempt + 1 == max_attempts:
            return response
        time.sleep((5, 15)[attempt])


def response_object(response):
    """Validate the provider envelope and JSON root without exposing its body."""
    try:
        envelope = response.json()
        if not isinstance(envelope, dict):
            raise ResponseFormatError('Gemini returned an invalid response envelope')
        candidates = envelope.get('candidates')
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise ResponseFormatError('Gemini returned no complete text candidate')
        candidate = candidates[0]
        if candidate.get('finishReason') not in (None, 'STOP'):
            raise ResponseFormatError('Gemini returned an incomplete text candidate')
        content = candidate.get('content')
        parts = content.get('parts') if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ResponseFormatError('Gemini returned no JSON text')
        chunks = [part['text'] for part in parts if isinstance(part, dict)
                  and isinstance(part.get('text'), str) and not part.get('thought')]
        result = json.loads(''.join(chunks))
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ResponseFormatError):
            raise
        raise ResponseFormatError('Gemini returned malformed JSON') from None
    if not isinstance(result, dict):
        raise ResponseFormatError('Gemini returned a JSON list or scalar; one object is required')
    return result
