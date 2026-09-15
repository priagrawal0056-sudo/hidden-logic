from __future__ import annotations

import re
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

from .core import FORMATS, PILLARS, file_hash, tokens
from .media import ffmpeg, font, wrap

SCENES = {'queue', 'comparison', 'process', 'signal', 'map', 'barcode', 'roundabout', 'payment', 'storyboard'}


def editorial_checks(episode, history=()):
    """Concrete failure checks, not an AI detector or a guarantee of craft."""
    from .storyboard import validate_storyboard, visual_signature
    script = ' '.join(episode['beats']).casefold().replace('\u2019', "'")
    banned = ('have you ever wondered', "here's the thing", 'mind-blowing',
              'this changes everything', 'stay until the end', 'you won\'t believe',
              'in this simple illustration', 'as an ai', 'insert hook', '[pause]',
              'narrator:', 'voiceover:')
    if any(phrase in script for phrase in banned):
        raise ValueError('Stock phrasing or leaked production instruction')
    if re.search(r'\byou always\b', script+' '+episode['title'].casefold()):
        raise ValueError('Unsupported universal viewer claim')
    sentences = [s for s in re.split(r'[.!?]+\s*', script) if tokens(s)]
    starts = [tuple(tokens(s)[:3]) for s in sentences]
    if len(starts) != len(set(starts)):
        raise ValueError('Repetitive sentence openings')
    validate_storyboard(episode.get('storyboard'))
    if not episode.get('source_label') or len(episode['source_label']) > 42:
        raise ValueError('Readable source credit required')
    for old in history:
        if old.get('id') == episode.get('id') or not old.get('storyboard'):
            continue
        if visual_signature(episode) == visual_signature(old):
            raise ValueError('Visual sameness: another topic uses this identical drawing')
    return True

def script_checks(episode):
    if episode.get('pillar') not in PILLARS or episode.get('format') not in FORMATS:
        raise ValueError('Invalid editorial category')
    beats, labels = episode.get('beats', []), episode.get('labels', [])
    if len(beats) != 4 or len(labels) != 4 or any(not isinstance(b, str) or not b.strip() for b in beats):
        raise ValueError('Four complete narration beats and labels required')
    if not episode.get('title') or len(episode['title']) > 100 or any(len(x) > 28 for x in labels):
        raise ValueError('Title or label length invalid')
    if episode.get('scene_kind') not in SCENES:
        raise ValueError('Unsupported animation component')
    script = ' '.join(beats)
    if not 45 <= len(tokens(script)) <= (75 if episode.get('production_version',0)>=4 else 70):
        raise ValueError('Script length outside editorial bounds')
    if len(tokens(beats[0])) > 11:
        raise ValueError('Opening too long')
    if re.search(r'\b(sinister|hostage strategy|biological surrender)\b', script, re.I):
        raise ValueError('Unsupported dramatic framing')
    if (not re.search(r'[.!?]$', script.strip()) or re.search(r'(which is why|right as|because)[.!?\s]*$', script, re.I)):
        raise ValueError('Incomplete ending')
    if episode.get('evidence_status') != 'source_checked':
        raise ValueError('Evidence not verified')
    if episode.get('editorial_review', {}).get('title_matches') is not True:
        raise ValueError('Title promise not verified')
    if episode.get('production_version',0) >= 3:
        editorial_checks(episode)
    if episode.get('production_version',0) >= 4:
        if not re.search(r'\b(?:follow|subscribe to) Hidden Logic\b',' '.join(script.split()[-15:]),re.I):
            raise ValueError('Short closing spoken CTA required after payoff')
        if not episode.get('broll_keywords') or len(set(episode['broll_keywords'])) < 3:
            raise ValueError('Distinct topic-specific footage queries required')
    return True


def timeline_checks(episode, folder, config):
    script_checks(episode)
    duration = episode['duration']
    if not config['duration_min'] <= duration <= config['duration_max']:
        raise ValueError('Measured duration outside trial band')
    scenes = episode['scenes']
    modern = episode.get('production_version',0) >= 4
    if (not scenes or (not modern and len(scenes) != 4)
            or abs(scenes[0]['start']) > .01 or abs(scenes[-1]['end'] - duration) > .1):
        raise ValueError('Incomplete scene coverage')
    for a, b in zip(scenes, scenes[1:]):
        if abs(a['end'] - b['start']) > .01:
            raise ValueError('Gap or overlap between scenes')
    if not modern and scenes[1]['start'] > 6:
        raise ValueError('First answer arrives too late')
    if episode.get('production_version') == 3 and scenes[1].get('narration_end', scenes[1]['end']) > 6:
        raise ValueError('First useful answer must finish within six seconds')
    if modern and episode.get('first_answer_end',float('inf')) > 6:
        raise ValueError('First useful answer must finish within six seconds')
    draw = ImageDraw.Draw(Image.new('RGB', (540,960)))
    previous_end = 0
    for caption in episode['captions']:
        if not 0 <= caption['start'] < caption['end'] <= duration + .05:
            raise ValueError('Invalid caption timing')
        if caption['start'] < previous_end - .01:
            raise ValueError('Overlapping captions')
        previous_end = caption['end']
        if not modern and len(wrap(draw, caption['text'], font(30), 422)) > 2:
            raise ValueError('Caption overflow')
    spoken = tokens(' '.join(episode['beats']))
    captioned = tokens(' '.join(c['text'] for c in episode['captions']))
    if spoken != captioned:
        raise ValueError('Caption/narration mismatch')
    if modern:
        from editorial_media import caption_records
        if caption_records(Path(folder)/'captions.ass') != episode['captions']:
            raise ValueError('Caption file differs from checked captions')
    for asset in episode.get('assets', []):
        if asset.get('path'):
            path = Path(folder) / asset['path']
            if not path.is_file() or file_hash(path) != asset['sha256']:
                raise ValueError('Asset missing or changed')
    return True


def rendered_checks(episode, folder, config):
    timeline_checks(episode, folder, config)
    path = Path(folder) / 'short.mp4'
    if not path.exists() or path.stat().st_size < 10000:
        raise ValueError('Rendered video missing')
    expected = episode.get('quality', {}).get('video_sha256')
    if expected and file_hash(path) != expected:
        raise ValueError('Rendered video changed since its quality check')
    result = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path),
        '-vf', 'blackdetect=d=0.1:pix_th=0.02',
        '-af', 'astats=metadata=0:reset=0,silencedetect=noise=-45dB:d=1.5',
        '-f', 'null', '-'], capture_output=True, text=True)
    if result.returncode or 'black_start:' in result.stderr:
        raise ValueError('Video decode or black-frame failure')
    peaks = re.findall(r'Peak level dB:\s*(-?[\d.]+)', result.stderr)
    if not peaks or max(map(float, peaks)) > -.2:
        raise ValueError('Missing audio analysis or clipping')
    # Long internal silence is an audible production failure, not a pacing effect.
    silences = re.findall(r'silence_start:\s*([\d.]+)', result.stderr)
    if any(float(s) < episode['duration'] - 1.5 for s in silences):
        raise ValueError('Unexpected narration silence')
    if episode.get('production_version',0) >= 4:
        from assemble import _measure_loudness
        measured = _measure_loudness(str(path))
        if abs(float(measured['input_i'])+14) > .7 or float(measured['input_tp']) > -1.2:
            raise ValueError('Final encoded loudness outside approved bounds')
        stock = [s.get('source_id') for s in episode['scenes'] if s.get('kind')=='stock']
        if len(stock)<2 or None in stock or len(stock)!=len(set(stock)):
            raise ValueError('Distinct stock sources required')
        if sum(s.get('kind')=='diagram' for s in episode['scenes']) != 1:
            raise ValueError('One visible mechanism demonstration required')
    editorial = ['stock_phrasing', 'executable_storyboard', 'diagram_bounds', 'visual_state_changes'] if episode.get('production_version') == 3 else []
    return {'passed': True, 'checks': editorial + ['source_record', 'title_promise', 'complete_script',
        'duration', 'captions', 'scene_coverage', 'asset_hashes', 'decode', 'black_frames', 'audio_peak', 'silence'],
        'video_sha256': file_hash(path), 'limitations': 'Automated checks cannot prove truth or artistic quality.'}
