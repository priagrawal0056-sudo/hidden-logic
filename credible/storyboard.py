"""Data-only motion drawings: the plan is the image, never an unused prompt.

Coordinates use a 540x960 canvas. Narration, headings and captions have their
own safe areas. Models can compose geometry, but cannot execute code or fetch
assets. A storyboard is an illustrative explanation, not measured footage.
"""
import math
from PIL import Image, ImageDraw
from .core import digest

COLORS = {'ink': '#edf3ef', 'muted': '#9caea8', 'accent': '#8ce0ba',
          'warm': '#ffb787', 'red': '#e48282', 'panel': '#253b36',
          'dark': '#142923', 'paper': '#e4e4d4'}

SCHEMA = '''storyboard: four objects matching the four beats. Each contains
heading (<=28 characters), purpose (what the drawing explains), example (boolean),
objects (3-40). Each object has type rect/ellipse/line/arrow/text, box [x,y,w,h],
color ink/muted/accent/warm/red/panel/dark/paper. All boxes stay inside x=38..460,
y=210..680. Rect/ellipse: filled boolean (default true). Text: text, size 16..32;
put each short label in its OWN empty box, no text overlap. Line/arrow box is
start x,y plus positive delta w,h to end. Optional move [dx,dy], reveal 0..0.7,
until 0.3..1 control movement/visibility relative to that narration beat.
Use actual objects, paths or comparisons, not four generic text boxes. Draw the
recognizable subject in scene one. Change the geometry/state meaningfully in
each next scene. Label illustrative values with example=true. Never render
photorealistic people or invented screenshots. Never invent measured data.
The fourth state is the resolved mechanism, used under the spoken follow request.
Keep it inside the same story. Never draw a subscribe/follow request or channel-name
text: the narration captions already carry the CTA. Use meaningful object motion.
'''


def validate_storyboard(plan):
    from .media import font, wrap
    if not isinstance(plan, list) or len(plan) != 4:
        raise ValueError('Four executable storyboard scenes required')
    draw = ImageDraw.Draw(Image.new('RGB', (540, 960)))
    shapes = []
    for scene in plan:
        if not isinstance(scene.get('example'), bool) or not scene.get('purpose'):
            raise ValueError('Storyboard needs purpose and explicit example status')
        if not scene.get('heading') or len(scene['heading']) > 28:
            raise ValueError('Storyboard heading overflow')
        objects = scene.get('objects', [])
        if not 3 <= len(objects) <= 80:
            raise ValueError('Storyboard object count invalid')
        text_boxes = []
        geometry = []
        for obj in objects:
            kind = obj.get('type')
            if kind not in ('rect', 'ellipse', 'line', 'arrow', 'text') or obj.get('color') not in COLORS:
                raise ValueError('Unsupported drawing primitive')
            box, move = obj.get('box'), obj.get('move', [0, 0])
            if not isinstance(box, list) or len(box) != 4 or len(move) != 2:
                raise ValueError('Invalid drawing coordinates')
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box + move):
                raise ValueError('Invalid drawing coordinates')
            x, y, w, h = box
            if w <= 0 or h <= 0:
                raise ValueError('Empty drawing')
            if kind in ('line','arrow'):
                end = obj.get('end')
                if end is not None and (not isinstance(end,list) or len(end)!=2 or
                    not all(isinstance(v,(int,float)) and math.isfinite(v) for v in end) or
                    not 38 <= end[0] <= 460 or not 210 <= end[1] <= 680):
                    raise ValueError('Invalid path endpoint')
            for dx, dy in ([0, 0], move):
                if x+dx < 38 or y+dy < 210 or x+w+dx > 460 or y+h+dy > 680:
                    raise ValueError('Drawing outside safe area')
            path = obj.get('motion_path', [])
            if path:
                if not isinstance(path,list) or not 2 <= len(path) <= 60:
                    raise ValueError('Invalid motion path')
                for point in path:
                    if not isinstance(point,list) or len(point)!=2 or not all(
                            isinstance(v,(int,float)) and math.isfinite(v) for v in point):
                        raise ValueError('Invalid motion path')
                    if not (38 <= point[0] <= 460-w and 210 <= point[1] <= 680-h):
                        raise ValueError('Motion path outside safe area')
            if not 0 <= obj.get('motion_start',0) < 1:
                raise ValueError('Invalid motion start')
            if not 0 <= obj.get('reveal', 0) < obj.get('until', 1) <= 1:
                raise ValueError('Invalid object timing')
            if kind == 'text':
                size = obj.get('size', 22)
                if not isinstance(size, int) or not 16 <= size <= 32:
                    raise ValueError('Illegible drawing label size')
                lines = wrap(draw, obj.get('text', ''), font(size), w)
                if not lines or len(lines)*(size+6) > h:
                    raise ValueError('Drawing label overflow')
                if move != [0, 0] or path:
                    raise ValueError('Labels must stay anchored to their objects')
                for a, b, c, d in text_boxes:
                    if x < a+c and x+w > a and y < b+d and y+h > b:
                        raise ValueError('Overlapping drawing labels')
                text_boxes.append(box)
            else:
                geometry.append(obj)
        if len(geometry) < 2:
            raise ValueError('Text-only storyboard is not a demonstration')
        shapes.append(digest(geometry))
    if len(set(shapes)) < 3:
        raise ValueError('Visual sameness: need at least three distinct diagram states')
    return True


def draw_storyboard(draw, scene, progress):
    from .media import font, wrap, arrow
    for obj in scene['objects']:
        if not obj.get('reveal', 0) <= progress <= obj.get('until', 1):
            continue
        t = min(1, max(0, (progress-obj.get('reveal', 0)) / .65))
        t = t*t*(3-2*t)
        x, y, w, h = obj['box']
        dx, dy = obj.get('move', [0, 0]); x += dx*t; y += dy*t
        path = obj.get('motion_path')
        if path:
            start=obj.get('motion_start',0)
            q=max(0,min(1,(progress-start)/(1-start)))*(len(path)-1)
            n=min(len(path)-2,int(q)); fraction=q-n
            x=path[n][0]+(path[n+1][0]-path[n][0])*fraction
            y=path[n][1]+(path[n+1][1]-path[n][1])*fraction
        color, kind = COLORS[obj['color']], obj['type']
        if kind == 'rect':
            draw.rounded_rectangle((x,y,x+w,y+h), radius=min(14,w/4,h/4),
                fill=color if obj.get('filled', True) else None,
                outline=color, width=3)
        elif kind == 'ellipse':
            draw.ellipse((x,y,x+w,y+h), fill=color if obj.get('filled', True) else None,
                         outline=color, width=3)
        elif kind == 'line':
            end=obj.get('end',[x+w,y+h])
            draw.line((x,y,*end), fill=color, width=4)
        elif kind == 'arrow':
            arrow(draw, (x,y), tuple(obj.get('end',[x+w,y+h])), color, 4)
        else:
            size = obj.get('size', 22)
            for n, line in enumerate(wrap(draw, obj['text'], font(size), w)):
                draw.text((x,y+n*(size+6)), line, font=font(size), fill=color)


def visual_signature(episode):
    return digest([[o for o in s['objects'] if o['type'] != 'text']
                   for s in episode.get('storyboard', [])])
