"""Shared, run-scoped Gemini stop signal. No keys or quota guesses are stored."""
from contextlib import contextmanager
from contextvars import ContextVar
import time
import json
import re
from copy import deepcopy

_current = ContextVar('gemini_run_limit', default=None)

_STAGES = frozenset(('writing', 'draft', 'editorial_review', 'source_review',
                     'script_review', 'footage_review', 'narration',
                     'script_draft', 'legacy_generation'))
_QUOTA_METRICS = frozenset('generativelanguage.googleapis.com/' + metric for metric in (
    'generate_content_free_tier_requests', 'generate_content_free_tier_input_token_count',
    'generate_content_paid_tier_requests', 'generate_content_paid_tier_input_token_count',
    'generate_content_requests', 'generate_content_input_token_count',
    'generate_content_output_token_count'))
_QUOTA_ID = re.compile(
    r'(?:GenerateRequests|GenerateContentRequests|GenerateContentInputTokens|'
    r'GenerateContentOutputTokens|GenerateContentTokens|GenerateTokens)'
    r'(?:Per(?:Day|Minute|Project|Model|User|Region|Second|Hour))+'
    r'(?:-(?:FreeTier|PaidTier))?')


def _model_label(value):
    if isinstance(value, str):
        value = value.removeprefix('models/')
        if re.fullmatch(r'gemini-[a-z0-9][a-z0-9._-]{0,99}', value):
            return value
    return 'unknown'


def _stage_label(value):
    return value if isinstance(value, str) and value in _STAGES else 'unknown'


def _safe_violation(violation):
    if not isinstance(violation, dict):
        return {}
    safe = {}
    quota_id = violation.get('quotaId')
    metric = violation.get('quotaMetric')
    if isinstance(quota_id, str) and _QUOTA_ID.fullmatch(quota_id):
        safe['quota_id'] = quota_id
    if isinstance(metric, str) and metric in _QUOTA_METRICS:
        safe['quota_metric'] = metric
    # A value without a recognized quota identity is not a useful cap.
    if not safe:
        return {}
    value = violation.get('quotaValue')
    if type(value) is int and 0 <= value <= 10**18:
        safe['quota_value'] = value
    elif isinstance(value, str) and re.fullmatch(r'\d{1,18}', value):
        safe['quota_value'] = int(value)
    dimensions = violation.get('quotaDimensions')
    model = _model_label(dimensions.get('model')) if isinstance(dimensions, dict) else 'unknown'
    if model != 'unknown':
        safe['model'] = model
    return safe


def _quota_violations(response):
    """Keep only recognized quota identifiers and numeric limits, never messages.

    Quota dimensions can include a project identifier. Only a valid Gemini model
    name is retained from them; arbitrary provider fields are deliberately lost.
    """
    try:
        envelope = response.json()
        error = envelope.get('error', {}) if isinstance(envelope, dict) else {}
        details = error.get('details', []) if isinstance(error, dict) else []
        result = []
        for item in details if isinstance(details, list) else []:
            if not isinstance(item, dict):
                continue
            violations = item.get('violations', [])
            for violation in violations if isinstance(violations, list) else []:
                safe = _safe_violation(violation)
                if safe and safe not in result:
                    result.append(safe)
        return result[:16]
    except (ValueError, AttributeError, TypeError):
        return []


def _safe_diagnostics(value):
    if not isinstance(value, dict):
        return {}
    safe = {}
    for field, sanitize in (('model', _model_label), ('stage', _stage_label)):
        label = sanitize(value.get(field))
        if label != 'unknown':
            safe[field] = label
    violations = value.get('violations', [])
    rows = []
    for row in violations[:16] if isinstance(violations, list) else []:
        if not isinstance(row, dict):
            continue
        violation = _safe_violation({
            'quotaId': row.get('quota_id'), 'quotaMetric': row.get('quota_metric'),
            'quotaValue': row.get('quota_value'), 'quotaDimensions': {'model': row.get('model')}})
        if violation:
            rows.append(violation)
    if rows:
        safe['violations'] = rows
    return safe


class ServiceUnavailable(RuntimeError):
    def __init__(self, status, limit_kind=None, retry_after=None, *, diagnostics=None):
        self.status = int(status)
        descriptions = {401: 'authentication rejected', 403: 'access denied',
                        404: 'configured model unavailable; check model access',
                        429: 'rate limit or quota exhausted'}
        self.limit_kind = limit_kind
        self.retry_after = retry_after
        self.quota_diagnostics = _safe_diagnostics(diagnostics)
        # The CLI can report this after a decorated session has reset its state.
        self.request_report = report()
        detail = descriptions.get(self.status, 'service unavailable')
        if self.status == 429 and limit_kind in ('daily','per_minute'):
            detail = 'daily quota exhausted' if limit_kind=='daily' else 'per-minute rate limit reached'
        super().__init__(f'Gemini HTTP {self.status}: {detail}; new API work stopped for this run')

@contextmanager
def session():
    token = _current.set({})
    try:
        yield
    except Exception as exc:
        # A CLI may handle the error after this context has reset. Preserve only
        # safe aggregate counts, never the request or its credentials.
        if not hasattr(exc, 'request_report'):
            exc.request_report = report()
        raise
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
        diagnostics = error.quota_diagnostics
    else:
        state = _current.get() or {}
        if state.get('status') != 429:
            return None
        kind, retry = state.get('limit_kind'), state.get('retry_after')
        diagnostics = state.get('quota_diagnostics', {})
    return {'http_status': 429, 'limit_kind': kind or 'unknown', 'retry_after': retry,
            **deepcopy(diagnostics)}


def quota_message(quota):
    kind = quota.get('limit_kind')
    label = ('Gemini daily quota exhausted' if kind == 'daily' else
             'Gemini per-minute rate limit reached' if kind == 'per_minute' else
             'Gemini rate limit or quota exhausted')
    return label + ' (HTTP 429). No further Gemini requests will be made in this run.'

def check():
    status = (_current.get() or {}).get('status')
    if status:
        state = _current.get()
        raise ServiceUnavailable(status, state.get('limit_kind'), state.get('retry_after'),
                                 diagnostics=state.get('quota_diagnostics'))

def quota_details(response):
    """Extract fixed classifications, never provider messages or project IDs."""
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
    if state is not None:
        attempt = state.get('active_request')
        if attempt is not None:
            attempt['status'] = str(status) if isinstance(status, int) and 100 <= status <= 599 else 'unknown'
            state['active_request'] = None
    if state is not None and status in (401, 403, 404, 429):
        state['status'] = status
        if status == 429:
            diagnostics = {}
            if attempt is not None:
                for field in ('model', 'stage'):
                    if attempt[field] != 'unknown':
                        diagnostics[field] = attempt[field]
            if response is not None:
                state['limit_kind'],state['retry_after']=quota_details(response)
                violations = _quota_violations(response)
                if violations:
                    diagnostics['violations'] = violations
            state['quota_diagnostics'] = diagnostics
        check()


def before_request(model=None, stage=None):
    """Space live requests across writer, narration and footage review."""
    check()
    state = _current.get()
    if state is None:
        return
    model = _model_label(model)
    stage = _stage_label(stage)
    previous = state.get('last_request')
    per_model = state.setdefault('last_request_by_model', {})
    narration_previous = per_model.get(model) if stage == 'narration' and model != 'unknown' else None
    if previous is not None or narration_previous is not None:
        now = time.monotonic()
        delay = 15 - (now - previous) if previous is not None else 0
        # Conservative pacing for the selected low-throughput narration model.
        # This is a local interval, not an assertion of the provider's quota cap.
        if narration_previous is not None:
            delay = max(delay, 20.5 - (now - narration_previous))
        if delay > 0:
            time.sleep(delay)
    started = time.monotonic()
    state['last_request'] = started
    if model != 'unknown':
        per_model[model] = started
    attempt = {'model': model, 'stage': stage, 'status': 'no_response'}
    state.setdefault('requests', []).append(attempt)
    state['active_request'] = attempt


def report():
    """Count attempted HTTP calls, including retries, only for the current run.

    These are request counts, not token usage or the project's remaining quota.
    A timeout or other missing response remains ``no_response`` rather than a
    claimed provider failure. Calls blocked before dispatch are never counted.
    """
    rows = {}
    attempts = (_current.get() or {}).get('requests', [])
    for attempt in attempts:
        key = (attempt['model'], attempt['stage'], attempt['status'])
        rows[key] = rows.get(key, 0) + 1
    return {'total_attempts': len(attempts), 'requests': [
        {'model': model, 'stage': stage, 'status': status, 'attempts': count}
        for (model, stage, status), count in sorted(rows.items())]}


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


def request_with_retry(send, max_attempts=3, *, model=None, stage=None):
    """Retry only temporary server failures, respecting shared pacing and quota.

    ``send`` owns its call budget and is invoked for every actual request. A
    retry cannot bypass authentication, quota, or a caller's remaining budget.
    """
    max_attempts = max(1, min(3, int(max_attempts)))
    for attempt in range(max_attempts):
        before_request(model=model, stage=stage)
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
