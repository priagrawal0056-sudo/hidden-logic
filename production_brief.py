"""One authoring contract shared by Gemini's first draft and the measured editor."""
import re

RULES = '''APPROVED PRODUCTION FORMAT — write for the actual editor on your FIRST draft.
Return beats (four strings), storyboard (four states), and broll_keywords (three strings).
If also returning script, it MUST equal the four beats joined with spaces.
Beat 1: one natural, concrete hook sentence about a recognizable object or situation.
Beat 2: one useful answer sentence. Keep hook and answer combined within 10 spoken words.
Use plain, short words here; introduce technical names in beat 3 after the useful answer.
Beat 3: one to three complete sentences demonstrating the mechanism, ideally 16-24 words.
This ENTIRE beat is the explanatory animation, usually 5-8 seconds. Do not put essential
diagram actions outside this beat. Show a change, comparison or process, not decorative labels.
Beat 4: a complete payoff that connects to the hook, THEN a separate final sentence beginning
"Follow Hidden Logic" (at most 11 words). No generic shelf/outro cut after the story.
The follow sentence plays over a newly animated resolved state of the same mechanism.
Return exactly three specific stock searches, in order: hook object, answer/context from
a different angle or action, then payoff object. These must be distinct source videos.
Vary the visible action, not just the wording: three honey-stirring searches still repeat
the same shot. Do not promise a tiny feature in the hook unless ordinary stock can show it.
Search for common visible objects and actions a stock camera can record: freezer door,
freezer groceries, refrigerator handle. Do not search for invisible mechanisms or specialist
internal parts such as pressure equalization or relief valves; the drawing explains those.
Keep the same real-world subject; do not broaden the last shot to generic lifestyle footage.
Storyboard states 2 and 3 show the mechanism's before/process and after/result; state 4 is
the resolved visual callback with meaningful movement. Use readable shapes, short labels
and negative space. The editor supplies navy/gold styling and one phrase-caption layer.
Never draw caption sentences, channel names or follow/subscribe text into the diagram.
Invented illustrative values must be marked example=true; do not present them as measurements.
Narration: connected, observant and conversational, with varied sentence lengths. No ominous
motives, canned AI phrases, fake personal experience, exaggerated certainty or directions.
Use 48-58 words INCLUDING the CTA; shorten the writing, never accelerate the voice.
Sound cues: zero to two scan/chime sounds on unique exact phrases in the mechanism or payoff.
Title: make one concrete promise answered by the script, no unsupported universal claims.
This is a production format example, NOT factual evidence to reuse:
hook: Same barcode, on sale? / answer: The code identifies the item. /
mechanism: The store's database supplies the price. Update that price, and the same packet scans for less. /
payoff: Same barcode, new price. Follow Hidden Logic for more everyday explanations.
Use the supplied sources for the actual episode's claims, scope and exceptions.
'''


def sentences(text):
    """Match the editor's whitespace-delimited sentence endings, not decimal dots."""
    chunks, current = [], []
    for token in text.split():
        current.append(token)
        if re.search(r'''[.!?]["'’”)]*$''', token):
            chunks.append(' '.join(current)); current=[]
    if current: chunks.append(' '.join(current))
    return chunks


def validate(data):
    beats=data.get('beats')
    if not isinstance(beats,list) or len(beats)!=4 or any(not isinstance(b,str) or not b.strip() for b in beats):
        raise ValueError('Production brief requires four complete narration beats')
    groups=[sentences(beat) for beat in beats]
    if any(not re.search(r'''[.!?]["'’”)]*$''',beat.strip()) for beat in beats):
        raise ValueError('Each production beat must finish its sentence')
    if len(groups[0])!=1 or len(groups[1])!=1 or not 1<=len(groups[2])<=3:
        raise ValueError('Use one hook, one answer and one to three mechanism sentences')
    if len(groups[3])<2 or not re.match(r'^Follow Hidden Logic\b',groups[3][-1],re.I):
        raise ValueError('Payoff must finish before a separate final Follow Hidden Logic sentence')
    if len(groups[3][-1].split())>11:
        raise ValueError('Keep the final spoken CTA short')
    script=' '.join(beats)
    if not data.get('authored'):
        # Live twelve-word openings exceeded six seconds even after a retake.
        # Shorten the draft before paying for narration; still measure the audio.
        if len((beats[0]+' '+beats[1]).split())>10:
            raise ValueError('Opening exceeds ten-word drafting ceiling; shorten hook and answer using plain words')
        if not 12<=len(beats[2].split())<=28:
            raise ValueError('Mechanism narration must fit a readable short demonstration')
        if len(groups[3])!=2:
            raise ValueError('One payoff sentence followed by one short CTA sentence required')
    if len(data.get('sound_cues',[]))>2:
        raise ValueError('Use at most two meaningful sound cues')
    if data.get('script') and re.sub(r'\s+',' ',data['script']).strip()!=script:
        raise ValueError('Script and production beats differ; refuse stale visual alignment')
    queries=data.get('broll_keywords')
    if (not isinstance(queries,list) or len(queries)!=3 or
        any(not isinstance(q,str) or not q.strip() for q in queries) or
        len({q.strip().casefold() for q in queries})!=3):
        raise ValueError('Three distinct stock queries required: hook, answer, payoff')
    for cue in data.get('sound_cues',[]):
        phrase=cue.get('phrase','')
        if not isinstance(phrase,str) or not phrase.strip() or cue.get('kind') not in ('scan','chime'):
            raise ValueError('Invalid payoff sound cue')
        meaningful=' '.join(beats[2:])
        if script.lower().count(phrase.lower())!=1 or phrase.lower() not in meaningful.lower():
            raise ValueError('Sound cue must match one exact mechanism/payoff phrase')
    return True


def media_metadata(data):
    validate(data)
    return {**data,'script':' '.join(data['beats']),
            'diagram_sentence_index':2,
            'diagram_sentence_count':len(sentences(data['beats'][2]))}


def usable_sound_cues(beats, cues):
    """Optional effects must never stop a supported, otherwise valid episode."""
    if not isinstance(beats,list) or any(not isinstance(b,str) for b in beats):
        return [], ['Invalid beats; narration validation required']
    script=' '.join(beats).casefold(); meaningful=' '.join(beats[2:]).casefold()
    kept=[]; removed=[]
    for cue in cues if isinstance(cues,list) else []:
        phrase=cue.get('phrase','') if isinstance(cue,dict) else ''
        if (not isinstance(phrase,str) or not phrase.strip() or
                cue.get('kind') not in ('scan','chime') or
                script.count(phrase.casefold())!=1 or phrase.casefold() not in meaningful or
                any(c['phrase'].casefold()==phrase.casefold() for c in kept) or len(kept)>=2):
            removed.append('Optional sound cue omitted: no unique mechanism/payoff anchor')
        else:kept.append(cue)
    return kept,removed
