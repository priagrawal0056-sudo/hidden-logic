"""Deterministic original scenes and measured, single-voice narration."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from .core import file_hash, read, save, tokens

BG = '#101924'
PANEL = '#1b2b3b'
WHITE = '#f4f7fa'
MUTED = '#99adbc'
CYAN = '#4ce2c0'
GOLD = '#ffd17a'


def ffmpeg():
    command = os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg')
    if command:
        return command
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, AttributeError, RuntimeError) as exc:
        raise RuntimeError('FFmpeg unavailable. Install requirements-credible.txt in a clean '
                           'virtual environment or set FFMPEG_BINARY to a working FFmpeg executable.') from exc


@lru_cache(maxsize=32)
def font(size):
    candidates = [Path(__file__).resolve().parent.parent/'assets/fonts/Arimo.ttf',
                  Path('assets/DejaVuSans.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                  Path('C:/Windows/Fonts/arial.ttf')]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def wrap(draw, text, face, width):
    lines, current = [], ''
    for word in text.split():
        proposed = (current + ' ' + word).strip()
        if draw.textlength(word, font=face) > width:
            raise ValueError('Unbreakable text overflows caption width')
        if current and draw.textlength(proposed, font=face) > width:
            lines.append(current)
            current = word
        else:
            current = proposed
    return lines + ([current] if current else [])


def text_block(draw, text, box, size=32, color=WHITE, max_lines=3):
    x, y, width = box
    face = font(size)
    lines = wrap(draw, text, face, width)
    if len(lines) > max_lines:
        raise ValueError('Caption overflow')
    for i, line in enumerate(lines):
        draw.text((x, y + i * (size + 8)), line, font=face, fill=color)
    return len(lines) * (size + 8)


def arrow(draw, start, end, color=CYAN, width=5):
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    pts = [end, (end[0] - 15 * math.cos(angle - .5), end[1] - 15 * math.sin(angle - .5)),
           (end[0] - 15 * math.cos(angle + .5), end[1] - 15 * math.sin(angle + .5))]
    draw.polygon(pts, fill=color)


def scene_frame(episode, elapsed, config):
    if episode.get('production_version') == 3:
        return editorial_frame(episode, elapsed, config)
    # Design at 540x960 with conservative Shorts UI margins, render at configured resolution.
    image = Image.new('RGB', (540, 960), BG)
    d = ImageDraw.Draw(image)
    scenes = episode['scenes']
    index = next((i for i, s in enumerate(scenes) if s['start'] <= elapsed < s['end']), len(scenes)-1)
    scene = scenes[index]
    p = max(0, min(1, (elapsed - scene['start']) / max(.01, scene['end'] - scene['start'])))
    text_block(d, 'HIDDEN LOGIC', (38, 45, 420), 18, CYAN)
    text_block(d, episode['title'], (38, 102, 422), 30, max_lines=3)
    text_block(d, scene['label'], (38, 262, 420), 22, GOLD, 2)
    d.rounded_rectangle((32, 335, 465, 650), radius=22, fill=PANEL)
    kind = episode['scene_kind']
    if kind == 'comparison':
        # Explicit arithmetic example: same unit, never claimed as observed retail data.
        for x, h, label, sub in [(82, 95, '$2 / 100 g', '$2 per 100 g'), (280, 165, '$3 / 200 g', '$1.50 per 100 g')]:
            d.rounded_rectangle((x, 548-h, x+102, 548), radius=10, fill=CYAN if x > 100 else GOLD)
            text_block(d, label, (x-18, 572, 178), 18, WHITE, 2)
            if index >= 2:
                text_block(d, sub, (x-18, 610, 178), 15, CYAN, 1)
    elif kind == 'map':
        for x in (75, 335):
            d.rectangle((x, 385, x+65, 563), fill='#526679')
        target = (240, 570)
        d.ellipse((229, 559, 251, 581), fill=CYAN)
        arrow(d, (220, 365), target)
        if index >= 2:
            d.line([(220,365), (335,445), target], fill=GOLD, width=5)
            radius = 25 + int(p*35)
            d.ellipse((240-radius,570-radius,240+radius,570+radius), outline=GOLD, width=2)
    elif kind == 'signal':
        for i in range(6):
            x = 66+i*62
            d.rectangle((x, 407, x+30, 583), fill='#415567' if i != 2 else '#bc5866')
        choices = [0,1,3,4,5] if index >= 2 else list(range(6))
        x = 81 + choices[int(elapsed*2) % len(choices)] * 62
        d.ellipse((x-13, 475, x+13, 501), fill=CYAN)
        text_block(d, 'RADIO CHANNELS', (95, 600, 325), 17, MUTED)
    elif kind == 'roundabout':
        d.ellipse((128,377,366,615), outline='#5b7082', width=46)
        d.ellipse((200,449,294,543), fill='#285b50')
        angle = elapsed*.8
        x,y = 247+119*math.cos(angle),496-119*math.sin(angle)
        d.rounded_rectangle((x-14,y-9,x+14,y+9), radius=4, fill=CYAN)
        d.line([(60,624),(102,608),(144,570)], fill='#5b7082', width=30)
        d.polygon([(95,574),(123,574),(109,598)], outline=GOLD, width=3)
        if index >= 2:
            text_block(d, 'YIELD', (47, 365, 100), 17, GOLD)
        # A second car visibly waits, then joins after the circulating car passes.
        if index < 2 or p < .55:
            ex,ey = 86,610
        else:
            q = min(1,(p-.55)/.45)
            ex,ey = 86+q*70,610-q*39
        d.rounded_rectangle((ex-12,ey-8,ex+12,ey+8),radius=4,fill=GOLD)
    elif kind == 'barcode':
        for i in range(34):
            x = 74+i*4
            if i % 3 != 1:
                d.rectangle((x,397,x+2,482), fill=WHITE)
        d.line((70, 404+int(p*72), 215, 404+int(p*72)), fill=CYAN, width=3)
        arrow(d, (228,442), (298,442))
        d.rounded_rectangle((307,394,435,505), radius=10, outline=CYAN, width=3)
        text_block(d, 'BAG ID' if episode['subject'] == 'baggage-identification' else 'DATABASE', (315,420,114), 15, WHITE, 1)
        if episode['subject'] == 'baggage-identification':
            for bx,code in ((90,'BAG A'),(290,'BAG B')):
                d.rounded_rectangle((bx,536,bx+92,604),radius=10,outline=GOLD,width=3)
                d.arc((bx+27,520,bx+65,552),180,360,fill=GOLD,width=3)
                text_block(d,code,(bx+11,564,80),16,WHITE,1)
        else:
            text_block(d, '$2.00' if index < 3 else '$3.00', (322,466,105),22,GOLD,1)
            text_block(d, 'Example price changes', (76,560,370), 22, GOLD)
    elif kind == 'payment':
        x = 72+int(p*70)
        d.rounded_rectangle((x,410,x+115,485), radius=13, fill=GOLD)
        d.rounded_rectangle((311,398,417,539), radius=13, outline=CYAN, width=4)
        label = 'CODE A' if index < 2 else 'CODE B'
        text_block(d, label, (151,574,250), 29, CYAN)
    elif kind == 'queue':
        for lane in range(3):
            y = 410+lane*72
            d.line((68,y+24,426,y+24), fill=MUTED, width=2)
            for j in range(4):
                x = 90+j*70+int(p*25)
                d.ellipse((x-12,y-12,x+12,y+12), fill=CYAN)
        text_block(d, 'ILLUSTRATIVE SERVICE FLOW', (55,607,380), 15, GOLD)
    else:
        labels = (['NAME','RESOLVER','ADDRESS'] if episode['subject'] == 'dns-resolution' else
                  ['BAG','SCREEN','INSPECT'] if episode['subject'] == 'checked-bag-screening' else
                  episode['labels'][1:4])
        for i, label in enumerate(labels):
            x = 54+i*139
            d.rounded_rectangle((x,435,x+113,525), radius=12, fill=CYAN if index == i else '#344b60')
            text_block(d, label, (x+7,451,101), 14, BG if index == i else WHITE, 3)
            if i < 2:
                arrow(d, (x+116,480), (x+135,480), GOLD, 3)
        x = 68+int(p*330)
        d.ellipse((x,554,x+12,566), fill=GOLD)
    text_block(d, 'ILLUSTRATION  /  NOT MEASURED DATA', (39,670,425), 13, MUTED, 1)
    captions = [c for c in episode['captions'] if c['start'] <= elapsed < c['end']]
    if captions:
        text_block(d, captions[0]['text'], (38,730,422), 30, WHITE, 2)
    # Progress is tied to narration, not an arbitrary animation cycle.
    d.rectangle((38,858,38+int(420*elapsed/episode['duration']),861), fill=CYAN)
    return image.resize((config['width'], config['height']), Image.Resampling.LANCZOS)


def audio_duration(path):
    result = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True, text=True)
    match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', result.stderr)
    if not match:
        raise ValueError('Cannot measure audio')
    return int(match[1])*3600 + int(match[2])*60 + float(match[3])


async def _voice(text, path, voice, rate='+0%'):
    import edge_tts
    stream = edge_tts.Communicate(text, voice, rate=rate, boundary='WordBoundary')
    words = []
    with open(path, 'wb') as output:
        async for chunk in stream.stream():
            if chunk['type'] == 'audio':
                output.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                words.append({'text': chunk['text'], 'start': chunk['offset']/1e7,
                              'end': (chunk['offset']+chunk['duration'])/1e7})
    if not words or Path(path).stat().st_size < 1000:
        raise ValueError('Missing voice or real word timings')
    return words


def synthesize(episode, folder, config):
    if episode.get('production_version', 0) >= 4:
        from .approved import synthesize as approved_synthesize
        return approved_synthesize(episode, folder, config)
    path = Path(folder) / 'voice.mp3'
    text = ' '.join(episode['beats'])
    for attempt in range(2):
        try:
            words = asyncio.run(_voice(text, path, config['voice'], config.get('voice_rate', '+0%')))
            break
        except Exception:
            if attempt == 1:
                raise
    duration = audio_duration(path)
    if not config['duration_min'] <= duration <= config['duration_max']:
        raise ValueError(f'Narration is {duration:.2f}s; revise script, never stretch voice')
    if tokens(' '.join(w['text'] for w in words)) != tokens(text):
        raise ValueError('Narration timing transcript mismatch')
    # Restore punctuation and contractions from the actual script. Service word
    # boundaries may split "don't" and omit full stops. Never invent timings.
    words = punctuated_words(text, words)
    scenes, captions, cursor = [], [], 0
    for i, beat in enumerate(episode['beats']):
        count = len(tokens(beat))
        selected, consumed = [], 0
        while cursor < len(words) and consumed < count:
            selected.append(words[cursor]); consumed += len(tokens(words[cursor]['text'])); cursor += 1
        if consumed != count:
            raise ValueError('Cannot align narration beat')
        start = 0 if i == 0 else selected[0]['start']
        scenes.append({'start': start, 'end': selected[-1]['end'], 'label': episode['labels'][i],
                       'narration': beat, 'narration_end': selected[-1]['end'],
                       'kind': episode['scene_kind']})
        group = []
        for word in selected:
            group.append(word)
            if len(group) == 5 or re.search(r'[,;:.!?][\"\u201d\u2019]*$', word['text']):
                captions.append({'start': group[0]['start'], 'end': group[-1]['end'], 'text': ' '.join(w['text'] for w in group)})
                group = []
        if group:
            captions.append({'start': group[0]['start'], 'end': group[-1]['end'], 'text': ' '.join(w['text'] for w in group)})
    for a,b in zip(scenes, scenes[1:]):
        a['end'] = b['start']
    scenes[-1]['end'] = duration
    for a,b in zip(captions,captions[1:]):
        a['end'] = min(b['start'], a['end'] + .25)
    captions[-1]['end'] = min(duration, captions[-1]['end'] + .25)
    episode.update(duration=duration, scenes=scenes, captions=captions,
                   voice={'engine': 'edge-tts', 'name': config['voice'],
                          'rate': config.get('voice_rate', '+0%'), 'timing_source': 'WordBoundary'},
                   assets=[{'path': 'voice.mp3', 'sha256': file_hash(path), 'origin': 'edge-tts'},
                           {'origin': 'original Pillow animation', 'license': 'project-authored'}])
    save(Path(folder)/'words.json', words)
    return episode


def punctuated_words(text, words):
    """Align service lexical tokens to written words, including contractions."""
    # Use the same character comparison as sentence_segments. ASR may split
    # DNS into D / N / S or join a contraction; spelling must still match exactly.
    from assemble import sentence_segments
    measured = [{'word': w['text'], 'start': w['start'], 'end': w['end'],
                 'estimated': w.get('estimated', False)} for w in words]
    try:
        sentence_segments(measured, text)
    except ValueError as exc:
        raise ValueError('Narration punctuation alignment mismatch: ' + str(exc)) from exc
    clean = lambda value: re.sub(r'[^a-z0-9]', '', value.lower())
    ends, offset = {}, 0
    for i, word in enumerate(words):
        offset += len(clean(word['text']))
        ends[offset] = i
    output, offset, first, pending = [], 0, 0, []
    for written in text.split():
        pending.append(written)
        offset += len(clean(written))
        if offset in ends and ends[offset] >= first:
            last = ends[offset]
            output.append({'text': ' '.join(pending), 'start': words[first]['start'],
                           'end': words[last]['end']})
            first, pending = last + 1, []
    if pending:
        if clean(''.join(pending)) or not output:
            raise ValueError('Narration punctuation alignment mismatch')
        output[-1]['text'] += ' ' + ' '.join(pending)
    if first != len(words):
        raise ValueError('Extra narration words')
    return output



def editorial_frame(episode, elapsed, config):
    from .storyboard import COLORS, draw_storyboard
    image = Image.new('RGB', (540, 960), '#10241e')
    draw = ImageDraw.Draw(image)
    index = next((i for i,s in enumerate(episode['scenes']) if s['start'] <= elapsed < s['end']), 3)
    timing, scene = episode['scenes'][index], episode['storyboard'][index]
    progress = max(0,min(1,(elapsed-timing['start']) / max(.01,timing['end']-timing['start'])))
    # The diagram gets most of the screen. No persistent full title, enclosing
    # template card, decorative progress bar or competing bouncing captions.
    text_block(draw, 'HIDDEN LOGIC', (38,62,310), 17, COLORS['accent'], 1)
    text_block(draw, scene['heading'], (38,115,422), 30, COLORS['ink'], 2)
    draw_storyboard(draw, scene, progress)
    text_block(draw, 'Illustrative example' if scene['example'] else 'Simplified diagram',
               (38,689,422), 15, COLORS['muted'], 1)
    caption = next((c for c in episode['captions'] if c['start'] <= elapsed < c['end']), None)
    if caption:
        text_block(draw, caption['text'], (38,735,422), 30, COLORS['ink'], 2)
    text_block(draw, 'Source: '+episode['source_label'], (38,855,422), 15, COLORS['muted'], 1)
    return image.resize((config['width'],config['height']),Image.Resampling.LANCZOS)


def render(episode, folder, config):
    if episode.get('production_version', 0) >= 4:
        from .approved import render as approved_render
        return approved_render(episode, folder, config)
    folder = Path(folder)
    width, height, fps = config['width'], config['height'], config['fps']
    frames = math.ceil(episode['duration']*fps)
    command = [ffmpeg(), '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-i', str(folder/'voice.mp3'),
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p',
               '-af', 'loudnorm=I=-16:TP=-1.5:LRA=9', '-c:a', 'aac', '-b:a', '128k',
               '-t', str(episode['duration']), '-movflags', '+faststart', str(folder/'short.mp4')]
    with (folder/'render.log').open('wb') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for n in range(frames):
                process.stdin.write(scene_frame(episode, n/fps, config).tobytes())
        finally:
            process.stdin.close()
            code = process.wait()
        if code:
            raise RuntimeError('Render failed; see render.log')
    contact = Image.new('RGB', (1080, 960), BG)
    for i, scene in enumerate(episode['scenes']):
        frame = scene_frame(episode, (scene['start']+scene['end'])/2, {**config,'width':270,'height':480})
        contact.paste(frame, (i*270, 0))
    # A second row catches captions late in each scene as well.
    for i, scene in enumerate(episode['scenes']):
        frame = scene_frame(episode, scene['end']-.3, {**config,'width':270,'height':480})
        contact.paste(frame, (i*270,480))
    contact.save(folder/'contact-sheet.jpg')
    return folder/'short.mp4'
