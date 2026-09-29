"""Keep verified asset caches through the reviewed transport-only update.

Only exact source hashes listed here qualify. Future prompt, voice or frame
validation edits get a new hash as usual; this is not a general cache bypass.
Audio, timings and stock bytes still undergo the existing integrity checks.
"""
import hashlib
from pathlib import Path
from .core import file_hash, read


def asset_code_hash(path):
    path = Path(path)
    records = read(Path(__file__).with_name('transport_cache_compat.json'), {})
    record = records.get(path.name)
    if record:
        data = path.read_bytes()
        normalized = data.replace(b'\r\n', b'\n')
        if hashlib.sha256(normalized).hexdigest() == record['transport_update_sha256']:
            return record['previous_crlf_sha256' if b'\r\n' in data else 'previous_lf_sha256']
    return file_hash(path)
