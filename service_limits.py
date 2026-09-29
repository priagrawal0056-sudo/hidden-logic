"""Shared, run-scoped Gemini stop signal. No keys or quota guesses are stored."""
from contextlib import contextmanager
from contextvars import ContextVar
import time
import json
import re
from copy import deepcopy

_current = ContextVar('gemini_run_limit', default=None)
_TRANSIENT_HTTP = (408, 500, 502, 503, 504)

# Explicit compatible free-tier candidates, not model aliases or paid-only Pro
# models. The repository's model-access check verifies availability separately.
TEXT_MODELS = ('gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite',
               'gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-2.5-flash-lite')
TTS_MODELS = ('gemini-3.1-flash-tts-preview', 'gemini-3.8-flash-tts',
              'gemini-2.5-flash-preview-tts')

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
        if isinstance(exc, TransientServiceError):
            stop_transient(exc)
        if not hasattr(exc, 'request_report'):
            exc.request_report = report()
        raise
    finally:
        _current.reset(token)

def blocked():
    state = _current.get() or {}
    return bool(state.get('status') or state.get('service_outage'))


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
    outage = service_deferral()
    if outage:
        raise TransientServiceError(**outage)

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


def observe(status, response=None, *, model_failure=False):
    state = _current.get()
    if state is not None:
        attempt = state.get('active_request')
        if attempt is not None:
            attempt['status'] = str(status) if isinstance(status, int) and 100 <= status <= 599 else 'unknown'
            state['active_request'] = None
    if model_failure and status in (404, 429):
        diagnostics = {}
        if state is not None and attempt is not None:
            diagnostics = {field: attempt[field] for field in ('model', 'stage')}
        kind, retry = quota_details(response) if response is not None else (None, None)
        if response is not None:
            diagnostics['violations'] = _quota_violations(response)
        error = ServiceUnavailable(status, kind, retry, diagnostics=diagnostics)
        error.model_scoped = True
        raise error
    if status in (401, 403, 404, 429) and state is None:
        kind, retry = quota_details(response) if response is not None else (None, None)
        error = ServiceUnavailable(status, kind, retry)
        if status == 403 and response is not None:
            try:
                if 'leak' in response.json().get('error', {}).get('message', '').lower():
                    error.args = (str(error) + '; key_blocked_as_leaked_replace_in_ai_studio',)
            except (ValueError, AttributeError, TypeError):
                pass
        raise error
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

    def __init__(self, message=None, *, http_status=None, kind='unavailable', model=None, stage=None):
        self.service_details = {
            'http_status': http_status if type(http_status) is int and http_status in _TRANSIENT_HTTP else None,
            'kind': kind if kind in ('server_error', 'timeout', 'connection_error', 'unavailable', 'request_budget') else 'unavailable',
            'model': _model_label(model), 'stage': _stage_label(stage)}
        super().__init__(message or service_message(self.service_details))


def service_deferral(error=None):
    """Only a typed Gemini outage may become a clean generation deferral."""
    if error is not None:
        return deepcopy(error.service_details) if isinstance(error, TransientServiceError) else None
    return deepcopy((_current.get() or {}).get('service_outage'))


def service_message(details):
    if details.get('kind') == 'request_budget':
        return 'Gemini request budget reached. Unfinished work will resume in a later run.'
    status = details.get('http_status')
    detail = ('HTTP ' + str(status) if status in _TRANSIENT_HTTP else
              'request timed out' if details.get('kind') == 'timeout' else
              'connection failed' if details.get('kind') == 'connection_error' else 'temporary outage')
    return ('Gemini service temporarily unavailable (' + detail + '). '
            'No further Gemini requests will be made in this run.')


def stop_transient(error):
    """Open the run's circuit only after a caller exhausts its recovery policy.

    The caller exhausts its configured compatible models first. A successful
    backup does not disable narration or review. No outage state survives the
    next run, and no raw provider text or credential is persisted here.
    """
    if not isinstance(error, TransientServiceError):
        raise TypeError('A typed Gemini service failure is required')
    state = _current.get()
    if state is not None:
        details = deepcopy(error.service_details)
        attempts = state.get('requests', [])
        if attempts:
            for field in ('model', 'stage'):
                if details[field] == 'unknown':
                    details[field] = attempts[-1][field]
            # Older callers already emit a typed terminal service failure. Use
            # the measured HTTP result, never parse arbitrary exception text.
            if details['kind'] == 'unavailable' and attempts[-1]['status'] in tuple(map(str, _TRANSIENT_HTTP)):
                details.update(http_status=int(attempts[-1]['status']), kind='server_error')
        state.setdefault('service_outage', details)
        error.service_details = deepcopy(state['service_outage'])
    return error


def is_retryable(error):
    """Keep verified work when a provider could not complete its assessment.

    A negative editorial verdict or ordinary validation error is not a service
    failure. They must not be silently retained as publishable work.
    """
    import requests
    return isinstance(error, (ServiceUnavailable, ResponseFormatError,
                              TransientServiceError, requests.Timeout,
                              requests.ConnectionError))


def wait_for_retry(model, stage, next_attempt=None):
    """Back off after failure; normal request pacing may require a longer wait."""
    check()
    label = f' (attempt {next_attempt})' if next_attempt else ''
    print(f'[gemini] {_model_label(model)} {_stage_label(stage)}: retrying in 10s{label}', flush=True)
    time.sleep(10)


def model_quota(response):
    """Only explicit per-model limits permit trying another model's allowance."""
    try:
        rows = [row for detail in response.json()['error']['details']
                for row in detail.get('violations', [])]
        return bool(rows) and all(isinstance(row, dict)
            and isinstance(row.get('quotaId'), str)
            and _QUOTA_ID.fullmatch(row['quotaId'])
            and 'PerModel' in row['quotaId'] for row in rows)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def request_with_retry(send, max_attempts=3, *, model=None, stage=None, stop_on_failure=True,
                       allow_model_fallback=False):
    """Retry network failures and temporary HTTP errors with ten-second pauses.

    ``send`` owns its call budget and is invoked for every actual request. A
    retry cannot bypass authentication, quota, or a caller's remaining budget.
    Only a caller with its own bounded fallback may delay the terminal stop.
    """
    max_attempts = max(1, min(3, int(max_attempts)))
    import requests
    for attempt in range(max_attempts):
        before_request(model=model, stage=stage)
        try:
            response = send()
        except (requests.Timeout, requests.ConnectionError) as exc:
            state = _current.get()
            if state is not None:
                state['active_request'] = None  # Counted as no_response, not an HTTP status.
            kind = 'timeout' if isinstance(exc, requests.Timeout) else 'connection_error'
            error = TransientServiceError(kind=kind, model=model, stage=stage)
            if attempt + 1 < max_attempts:
                wait_for_retry(model, stage, attempt + 2)
                continue
            raise (stop_transient(error) if stop_on_failure else error) from None
        observe(response.status_code, response, model_failure=allow_model_fallback and
                (response.status_code == 404 or (response.status_code == 429 and model_quota(response))))
        if response.status_code not in _TRANSIENT_HTTP or attempt + 1 == max_attempts:
            if response.status_code in _TRANSIENT_HTTP and stop_on_failure:
                raise stop_transient(TransientServiceError(http_status=response.status_code,
                    kind='server_error', model=model, stage=stage))
            return response
        wait_for_retry(model, stage, attempt + 2)


class ModelChain:
    """Exhaust bounded retries and compatible backups before deferring a run.

    Remember failed models for this run so later reviews don't retry a known
    outage. A successful response never bypasses the caller's quality checks.
    """

    def __init__(self, models, budget=None):
        self.models = tuple(dict.fromkeys(models))
        if not self.models or any(_model_label(m) != m for m in self.models):
            raise ValueError('Configure explicit Gemini model IDs')
        self.model = self.models[0]
        self.remaining = len(self.models) * 3 if budget is None else int(budget)
        self.failed = {}
        self.stopped = None

    def request(self, send, *, stage):
        check()
        if self.stopped is not None:
            raise self.stopped
        state = _current.get()
        failed = state.setdefault('failed_models', {}) if state is not None else self.failed
        candidates = tuple(dict.fromkeys((self.model, *self.models)))
        last = None
        switching = False
        for model in candidates:
            if model in failed:
                last = failed[model]
                continue
            if self.remaining <= 0:
                raise stop_transient(TransientServiceError(kind='request_budget', model=model, stage=stage))
            if switching:
                print(f'[gemini] Trying backup model {model} for {_stage_label(stage)}', flush=True)
                wait_for_retry(model, stage)
            self.model = model

            def dispatch():
                self.remaining -= 1
                return send(model)

            try:
                response = request_with_retry(dispatch, max_attempts=min(3, self.remaining),
                    model=model, stage=stage, stop_on_failure=False, allow_model_fallback=True)
                if response.status_code not in _TRANSIENT_HTTP:
                    return response
                last = TransientServiceError(http_status=response.status_code, kind='server_error',
                                             model=model, stage=stage)
            except TransientServiceError as exc:
                last = exc
            except ServiceUnavailable as exc:
                # Global/unknown quota and auth failures have already opened the
                # stop signal. Only explicitly model-scoped limits may rotate.
                if blocked() or not getattr(exc, 'model_scoped', False):
                    self.stopped = exc
                    raise
                last = exc
            failed[model] = last
            switching = True

        if isinstance(last, ServiceUnavailable) and last.status == 429:
            if state is not None:
                state.update(status=429, limit_kind=last.limit_kind, retry_after=last.retry_after,
                             quota_diagnostics=last.quota_diagnostics)
            last.request_report = report()
            raise last
        if not isinstance(last, TransientServiceError):
            last = TransientServiceError(model=self.model, stage=stage)
        raise stop_transient(last)


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
