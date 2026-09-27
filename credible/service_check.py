"""Check the GitHub secret and configured models without generating any content."""
import argparse
import json
import os
import re
from pathlib import Path

import requests
from .core import now, read, save


def check(key, models, get=requests.get):
    report = {'at': now().isoformat(), 'published': False, 'generation_requests': 0,
              'models': dict(models), 'status': 'checking'}
    if not key:
        return {**report, 'status': 'missing_secret',
                'message': 'Set the repository Actions secret HL_GEMINI_API_KEY.'}
    if key != key.strip() or any(c.isspace() for c in key) or key.startswith(('"', "'", 'Bearer ', 'HL_GEMINI_API_KEY=')):
        return {**report, 'status': 'invalid_secret_format',
                'message': 'The secret value must contain only the API key, without quotes or an assignment.'}
    available, token = set(), None
    try:
        for _ in range(5):
            params = {'pageSize': 1000}
            if token:
                params['pageToken'] = token
            response = get('https://generativelanguage.googleapis.com/v1beta/models',
                           headers={'x-goog-api-key': key}, params=params, timeout=30)
            report['http_status'] = response.status_code
            if response.status_code != 200:
                status = ('authentication_rejected' if response.status_code in (400, 401, 403)
                          else 'rate_limited' if response.status_code == 429 else 'service_unavailable')
                return {**report, 'status': status,
                        'message': 'Model access check returned HTTP ' + str(response.status_code) + '.'}
            payload = response.json()
            for model in payload['models']:
                name = model.get('name', '').removeprefix('models/')
                if (re.fullmatch(r'gemini-[a-z0-9][a-z0-9._-]{0,99}', name) and
                        'generateContent' in model.get('supportedGenerationMethods', [])):
                    available.add(name)
            token = payload.get('nextPageToken')
            if not token:
                break
        else:
            return {**report, 'status': 'incomplete_model_list',
                    'message': 'Model list exceeded bounded pagination; generation was not attempted.'}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        # Exceptions may include request headers or URLs; never log their bodies.
        return {**report, 'status': 'service_unavailable',
                'message': 'Model access could not be verified; generation was not attempted.'}
    missing = {role: model for role, model in models.items() if model not in available}
    return {**report, 'status': 'model_unavailable' if missing else 'connected',
            'authentication': 'accepted', 'missing_models': missing,
            'available_generate_models': sorted(available),
            'message': ('The key connects, but a configured model is unavailable.' if missing else
                        'The key connects and configured models are listed. Generation quota is not tested.')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('outputs/connection-check.json'))
    args = parser.parse_args()
    config = read('credible/settings.json')
    profile = read('editorial_profile.json')
    result = check(os.environ.get('HL_GEMINI_API_KEY', ''), {
        'writing': config['model'],
        'footage_review': profile.get('footage_review_model', 'gemini-3.5-flash-lite'),
        'narration': profile['gemini_tts_model']})
    save(args.output, result)
    print(json.dumps(result, indent=2))
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as stream:
            stream.write('ready=' + str(result['status'] == 'connected').lower() + '\n')
    # Metadata rate limiting is also an expected deferral; callers use ready to
    # skip generation, while auth/model/configuration failures remain visible.
    return 0 if result['status'] in ('connected', 'rate_limited') else 1


if __name__ == '__main__':
    raise SystemExit(main())
