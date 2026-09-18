"""Shared approved editing path; retains the original narration and FFmpeg modules."""
from pathlib import Path
import io
import json
import math
import re
import subprocess

import assemble
import captions
from credible.core import file_hash, save

ROOT = Path(__file__).resolve().parent
STYLE_FILES = ('editorial_profile.json', 'editorial_media.py', 'assemble.py',
               'captions.py', 'tts.py', 'visuals.py', 'config_loader.py', 'footage_review.py',
               'credible/approved.py', 'credible/approved_seeds.py','production_brief.py',
               'assets/fonts/Arimo.ttf','Anton-Regular.ttf')


def fingerprint():
    return [(name, file_hash(ROOT/name)) for name in STYLE_FILES]


def plan_scenes(words, script, config, diagram_index=1, diagram_count=None):
    """Hold complete sentences together, never shorten or stretch spoken audio."""
    durations = assemble.sentence_segments(words, script)
    if diagram_count is not None:
        from production_brief import sentences
        if len(durations)!=len(sentences(script)):
            raise ValueError('Measured sentences are too short to preserve the authored visual plan')
    if len(durations) < 3:
        raise ValueError('Need a hook, explanation and complete ending')
    start = min(max(1, diagram_index), len(durations)-2)
    stop = start+1
    target, maximum = config.get('diagram_target_seconds', 5), config.get('diagram_max_seconds', 8)
    if diagram_count is not None:
        if type(diagram_count) is not int or not 1<=diagram_count<=3 or start+diagram_count>len(durations)-2:
            raise ValueError('Mechanism span must leave the payoff and final CTA intact')
        stop=start+diagram_count
    elif (durations[start] < target and start+1 < len(durations)-1
            and durations[start]+durations[start+1] > maximum):
        # Keep the long explanation intact instead of showing its diagram only
        # during the preceding two-second answer.
        start += 1; stop = start+1
    while (diagram_count is None and sum(durations[start:stop]) < target and stop < len(durations)-1
           and sum(durations[start:stop+1]) <= maximum):
        stop += 1
    result, cursor = [], 0.0
    for i, duration in enumerate(durations):
        if start < i < stop:
            continue
        if i == start:
            duration = sum(durations[start:stop])
        result.append({'start': cursor, 'end': cursor+duration,
                       'kind': 'diagram' if i == start else 'stock',
                       'sentence_start':i,'sentence_count':stop-start if i==start else 1})
        cursor += duration
    last_words = [w['word'].lower().strip('.,!?') for w in words if w['start']>=result[-1]['start']]
    if last_words and last_words[0] in ('follow','subscribe'):
        result[-1]['kind'] = 'callback'
    return result


def synthesize(meta, folder, config):
    import tts
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    voice, timing = folder/'voice.mp3', folder/'timings.json'
    tts.synthesize(meta['script'], str(voice), str(timing),
                   api_key=config.get('gemini_api_key', ''), engine=config['tts_engine'], cfg=config)
    return tts.tighten_long_pauses(str(voice), str(timing))


def diagram_frame(meta, progress):
    """Only explanation geometry is drawn; spoken text belongs to captions alone."""
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (1080, 1920), '#121a24')
    draw = ImageDraw.Draw(image)
    if meta.get('_callback') and meta.get('diagram_type') == 'barcode_lookup':
        # A new final-state composition, not a replay of the earlier animation.
        # The price remains at its resolved value throughout the spoken CTA.
        font = ImageFont.truetype(assemble._find_font(),60)
        price = ImageFont.truetype(assemble._find_font(),118)
        small = ImageFont.truetype(assemble._find_font(),28)
        ease = 1-(1-progress)**3
        product_y = int(345-35*ease)
        draw.text((150,240),'ILLUSTRATIVE PRICE',font=small,fill='#b8c4d2')
        draw.rounded_rectangle((150,product_y,890,product_y+235),radius=24,fill='#243142',outline='#f4c650',width=4)
        draw.text((520,product_y+30),'ITEM CODE',font=font,anchor='mt',fill='white')
        x=355
        for width in [5,2,7,3,2,6,3,5,2,4,7,2,3,5,2,6]:
            draw.rectangle((x,product_y+125,x+width*2,product_y+195),fill='white'); x+=width*2+12
        price_y=int(790-20*ease)
        draw.rounded_rectangle((150,price_y,890,price_y+280),radius=24,fill='#243142',outline='#f4c650',width=4)
        draw.text((520,price_y+26),'CURRENT PRICE',font=font,anchor='mt',fill='white')
        draw.text((520,price_y+102),'$3.00',font=price,anchor='mt',fill='#f4c650')
        top=product_y+250; bottom=price_y-25
        draw.line((520,top,520,bottom),fill='#f4c650',width=6)
        draw.polygon([(507,bottom-14),(533,bottom-14),(520,bottom+3)],fill='#f4c650')
        # A single lookup travels down the connection, then settles on the result.
        phase=max(0,min(1,(progress-.1)/.65))
        if 0<phase<1:
            y=top+(bottom-top)*phase
            draw.ellipse((509,y-11,531,y+11),fill='white')
        return image
    if meta.get('diagram_type') == 'barcode_lookup':
        font = ImageFont.truetype(assemble._find_font(), 60)
        detail = ImageFont.truetype(assemble._find_font(), 42)
        small = ImageFont.truetype(assemble._find_font(), 28)
        update = meta.get('_diagram_update_progress',.55)
        draw.text((150,240),'ILLUSTRATIVE PRICES',font=small,fill='#b8c4d2')
        for i, (top, label) in enumerate([(320, 'ITEM CODE'), (620, 'STORE RECORD'), (920, 'CURRENT PRICE')]):
            active = progress >= i*.18
            draw.rounded_rectangle((150, top, 890, top+175), radius=24, fill='#243142',
                                   outline='#f4c650' if active else '#465363', width=4)
            draw.text((520, top+42), label, font=font, anchor='mt', fill='white')
            if i == 0:
                x = 430
                for width in [5,2,7,3,2,6,3,5,2,4,7,2,3,5,2,6]:
                    draw.rectangle((x,top+120,x+width,top+155), fill='white'); x += width+7
            else:
                # The identifier stays fixed while the stored price and returned
                # result change. Values are explicitly illustrative, not evidence.
                changed = progress >= update+(0 if i==1 else .13)
                draw.text((520,top+112),'$3.00' if changed else '$4.00',font=detail,
                          anchor='mt',fill='#f4c650' if changed else '#b8c4d2')
            if i < 2:
                draw.line((520,top+186,520,top+277), fill='#f4c650', width=6)
                draw.polygon([(507,top+263),(533,top+263),(520,top+279)], fill='#f4c650')
                phase = max(0, min(1, (progress-i*.18-.08)/.12))
                if 0 < phase < 1:
                    y = top+188+phase*82
                    draw.ellipse((510,y-10,530,y+10), fill='white')
        return image
    from credible.storyboard import draw_storyboard, validate_storyboard
    plan = meta.get('storyboard')
    validate_storyboard(plan)
    # Show the mechanism and its changed state, with a readable final hold.
    transition = meta.get('_diagram_transition_progress',.38)
    state = plan[3] if meta.get('_callback') else plan[1] if progress < transition else plan[2]
    local = (progress if meta.get('_callback') else progress/transition if progress < transition
             else min(1,(progress-transition)/max(.01,(1-transition)*.8)))
    canvas = Image.new('RGB', (540,960), '#121a24')
    draw_storyboard(ImageDraw.Draw(canvas), state, local)
    image.paste(canvas.crop((20,200,500,690)).resize((960,980)), (30,220))
    if state['example']:
        small = ImageFont.truetype(assemble._find_font(), 30)
        draw.text((110, 160), 'ILLUSTRATIVE EXAMPLE', font=small, fill='#b8c4d2')
    if meta.get('_callback'):
        # Gentle continuous reframing even when the final-state objects settle.
        inset=round(10*progress)
        image=image.crop((inset,inset,1080-inset,1920-inset)).resize((1080,1920))
    return image


def render_diagram(meta, path, duration):
    command = [assemble._ffmpeg(), '-v','error','-y','-f','rawvideo','-pix_fmt','rgb24',
               '-s','1080x1920','-r','30','-i','pipe:0','-an','-c:v','libx264',
               '-preset','veryfast','-crf','19',str(path)]
    count = math.ceil(duration*30)+2
    with (Path(path).with_suffix('.log')).open('wb') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i in range(count):
                process.stdin.write(diagram_frame(meta, min(1,i/max(1,count-3))).tobytes())
        finally:
            process.stdin.close()
            code = process.wait()
        if code:
            raise RuntimeError('Diagram render failed; see local diagram log')


def caption_records(path):
    result = []
    def seconds(value):
        h,m,s = value.split(':'); return int(h)*3600+int(m)*60+float(s)
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith('Dialogue:'):
            fields = line.split(',',9)
            visible = re.sub(r'\{[^}]*\}', '', fields[9])
            if len(visible.split(r'\N')) > 2:
                raise ValueError('Caption overflow')
            result.append({'start':seconds(fields[1]), 'end':seconds(fields[2]),
                           'text':visible.replace(r'\N',' ')})
    return result


def contact_sheet(video, scenes, path):
    from PIL import Image, ImageDraw
    times = [s['start']+.2 for s in scenes] + [s['end']-.2 for s in scenes]
    sheet = Image.new('RGB',(270*len(scenes),1000),'#121a24')
    for i,t in enumerate(times):
        result = subprocess.run([assemble._ffmpeg(),'-v','error','-ss',str(max(0,t)),
            '-i',str(video),'-frames:v','1','-vf','scale=270:480','-f','image2pipe',
            '-vcodec','mjpeg','pipe:1'], capture_output=True, check=True)
        x,y=(i%len(scenes))*270,(i//len(scenes))*500
        sheet.paste(Image.open(io.BytesIO(result.stdout)),(x,y+20))
        ImageDraw.Draw(sheet).text((x+4,y+3),f'{t:.1f}s',fill='white')
    sheet.save(path)


def render(meta, folder, config, stock=None):
    import visuals
    folder = Path(folder)
    words = json.loads((folder/'timings.json').read_text(encoding='utf-8'))
    scenes = plan_scenes(words, meta['script'], config, meta.get('diagram_sentence_index',1),
                         meta.get('diagram_sentence_count'))
    sentence_durations = assemble.sentence_segments(words,meta['script'])
    needed = sum(s['kind']=='stock' for s in scenes)
    if stock is None:
        previous_cache = visuals.CACHE_FILE
        visuals.CACHE_FILE = str(config.get('clip_history_path', folder/'used_clips.json'))
        Path(visuals.CACHE_FILE).parent.mkdir(parents=True,exist_ok=True)
        try:
            paths = visuals.fetch_backgrounds(config.get('pexels_api_key',''), meta.get('broll_keywords',[]),
                str(folder), count=needed, pixabay_key=config.get('pixabay_api_key'),
                gemini_api_key=config.get('gemini_api_key'), visual_thesis=meta.get('visual_thesis',meta['script']),
                first_frame_description=meta.get('first_frame_description',''), topic=meta.get('title',''))
        finally:
            visuals.CACHE_FILE = previous_cache
        stock = []
        from footage_review import assess
        stock_scenes = [s for s in scenes if s['kind']=='stock']
        for path, scene in zip(paths,stock_scenes):
            record = json.loads(Path(path+'.source.json').read_text(encoding='utf-8'))
            spoken = ' '.join(w['word'] for w in words if scene['start'] <= w['start'] < scene['end'])
            record.update(assess(path,scene['end']-scene['start'],spoken,
                [s['assessment']['description'] for s in stock],config.get('gemini_api_key','')))
            stock.append({**record, 'path':path})
    if len(stock) != needed:
        raise ValueError('Every stock scene needs a distinct supplied source')
    paths, shots, assets = [], [], []
    stock_cursor = 0
    for scene in scenes:
        if scene['kind'] in ('diagram','callback'):
            path = folder/('callback.mp4' if scene['kind']=='callback' else 'mechanism.mp4')
            drawing = dict(meta)
            drawing['_callback'] = scene['kind']=='callback'
            if scene['kind']=='diagram' and scene['sentence_count']>1:
                drawing['_diagram_transition_progress'] = sentence_durations[scene['sentence_start']]/(scene['end']-scene['start'])
            changes = [w['start'] for w in words if w['word'].casefold().strip('.,!?')=='update'
                       and scene['start']<=w['start']<scene['end']]
            if len(changes)==1:
                drawing['_diagram_update_progress'] = (changes[0]-scene['start'])/(scene['end']-scene['start'])
            render_diagram(drawing,path,scene['end']-scene['start'])
            record = {'path':str(path),'source_id':'authored:'+scene['kind'],'license':'project-authored'}
        else:
            record = stock[stock_cursor]; stock_cursor += 1
        path = Path(record['path'])
        if not record.get('source_id') or not record.get('license'):
            raise ValueError('Asset source identity and license record required')
        paths.append(str(path))
        shot = {k:record[k] for k in ('source_id','source_start','crop_center') if k in record}
        shots.append(shot); scene.update(shot)
        assets.append({**record,'path':str(path.resolve()),'sha256':file_hash(path)})
    ass = folder/'captions.ass'
    captions.build_ass(str(folder/'timings.json'),str(ass),meta.get('emphasis_words',[]),accent='gold')
    music = Path(config['music_file'])
    if not music.is_absolute(): music = ROOT/music
    if not music.is_file(): raise ValueError('Approved licensed music bed is missing')
    out = folder/'short.mp4'
    assemble.assemble(paths,str(folder/'voice.mp3'),str(folder/'timings.json'),str(ass),str(out),str(music),
        music_volume=config.get('music_bed_gain',.14), seg_seconds=[s['end']-s['start'] for s in scenes],
        shot_plan=shots, hook_motion=True, editorial_effects=False, opening_hook_text=None,
        show_follow_cue=False, show_subscribe_cue=False,
        sound_cues=assemble.resolve_sound_cues(words,meta.get('sound_cues',[])))
    contact_sheet(out,scenes,folder/'contact-sheet.jpg')
    assets += [{'path':'voice.mp3','sha256':file_hash(folder/'voice.mp3'),'origin':'Gemini Orus'},
               {'path':str(music),'sha256':file_hash(music),'origin':'project music bed'},
               {'path':'captions.ass','sha256':file_hash(ass),'origin':'measured phrase captions'}]
    result = {'scenes':scenes,'duration':scenes[-1]['end'],'captions':caption_records(ass),'assets':assets}
    save(folder/'edit-plan.json', result)
    return result
