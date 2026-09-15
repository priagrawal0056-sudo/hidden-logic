"""Adapter from evidence/scheduling records to the existing approved editor."""
from pathlib import Path
import editorial_media
from config_loader import load_config
from .core import save, file_hash, tokens


def config_for(config):
    from json import loads
    profile = loads((editorial_media.ROOT/'editorial_profile.json').read_text())
    return {**load_config(), **config, **profile}


def metadata(episode):
    return {**episode, 'script':' '.join(episode['beats']),
            'visual_thesis':episode.get('claim',''),
            'diagram_type':'barcode_lookup' if episode.get('claim_id')=='barcode-mechanism-v1' else 'storyboard'}


def synthesize(episode, folder, config):
    from .media import punctuated_words
    cfg = config_for(config)
    words = editorial_media.synthesize(metadata(episode),folder,cfg)
    punctuated = punctuated_words(' '.join(episode['beats']),
                                [{'text':w['word'],'start':w['start'],'end':w['end']} for w in words])
    canonical = [{'word':w['text'],'start':w['start'],'end':w['end']} for w in punctuated]
    save(Path(folder)/'timings.json',canonical)
    scenes, cursor = [], 0
    for beat in episode['beats']:
        count, selected = 0, []
        while cursor < len(canonical) and count < len(tokens(beat)):
            word = canonical[cursor]; selected.append(word); cursor += 1
            count += len(tokens(word['word']))
        if count != len(tokens(beat)): raise ValueError('Cannot align editorial beat')
        scenes.append({'start':0 if not scenes else selected[0]['start'],
                       'end':selected[-1]['end'],'narration_end':selected[-1]['end']})
    duration = canonical[-1]['end']+.8
    for a,b in zip(scenes,scenes[1:]): a['end'] = b['start']
    scenes[-1]['end'] = duration
    import captions
    captions.build_ass(str(Path(folder)/'timings.json'),str(Path(folder)/'captions.ass'),accent='gold')
    episode.update(duration=duration, scenes=scenes, beats_timing=scenes,
        first_answer_end=scenes[1]['narration_end'],
        captions=editorial_media.caption_records(Path(folder)/'captions.ass'),
        voice={'engine':'gemini','name':cfg['gemini_voice'],'timing_source':'Whisper word alignment'},
        assets=[{'path':'voice.mp3','sha256':file_hash(Path(folder)/'voice.mp3'),'origin':'Gemini Orus'}])
    save(Path(folder)/'words.json',punctuated)
    return episode


def render(episode, folder, config):
    result = editorial_media.render(metadata(episode),folder,config_for(config))
    episode.update(result)
    return Path(folder)/'short.mp4'
