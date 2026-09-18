"""Data-only motion drawings: the plan is the image, never an unused prompt.

Coordinates use a 540x960 canvas. Narration, headings and captions have their
own safe areas. Models can compose geometry, but cannot execute code or fetch
assets. A storyboard is an illustrative explanation, not measured footage.
"""
import math
from PIL import Image, ImageDraw
from .core import digest

COLORS = {'ink': '#ffffff', 'muted': '#b8c4d2', 'accent': '#f4c650',
          'warm': '#ffb787', 'red': '#e48282', 'panel': '#243142',
          'dark': '#121a24', 'paper': '#e4e4d4'}

SCHEMA = '''storyboard: four objects matching the four beats. Each contains
heading (<=28 characters), purpose (what the drawing explains), example (boolean),
objects (3-40). Each object has type rect/ellipse/line/arrow/text, box [x,y,w,h],
color ink/muted/accent/warm/red/panel/dark/paper. All boxes stay inside x=38..460,
y=210..680. Rect/ellipse: filled boolean (default true). Text: text, size 16..32;
put each short label in its OWN empty box, no text overlap. A single line
needs height >= size+6; two lines need >=2*(size+6). Labels cannot move. The renderer fits label heights and pins labels locally.
Give labels generous width and short text. Motion endpoints must ALSO stay
inside the safe area, including the full width and height of each object. Line/arrow box is
start x,y plus signed delta w,h to end; horizontal and vertical lines are allowed. Optional move [dx,dy], reveal 0..0.7,
until 0.3..1 control movement/visibility relative to that narration beat.
Rectangles and ellipses may use rotate (degrees, -45..45) about their centre.
Scaling and opacity are not supported.
Use actual objects, paths or comparisons, not four generic text boxes. Draw the
recognizable subject in scene one. Change the geometry/state meaningfully in
each next scene. Label illustrative values with example=true. Never render
photorealistic people or invented screenshots. Never invent measured data.
The fourth state is the resolved mechanism, used under the spoken follow request.
Keep it inside the same story. Never draw a subscribe/follow request or channel-name
text: the narration captions already carry the CTA. Use meaningful object motion.
'''


def rotated_points(obj):
    """The same rotated geometry is used for drawing and bounds validation."""
    x,y,w,h=obj['box'];angle=math.radians(obj.get('rotate',0))
    cx,cy=x+w/2,y+h/2
    if obj['type']=='ellipse':
        points=[(cx+w/2*math.cos(i*math.pi/32),cy+h/2*math.sin(i*math.pi/32)) for i in range(64)]
    else:
        points=[(x,y),(x+w,y),(x+w,y+h),(x,y+h)]
    return [(cx+(a-cx)*math.cos(angle)-(b-cy)*math.sin(angle),
             cy+(a-cx)*math.sin(angle)+(b-cy)*math.cos(angle)) for a,b in points]


def layout_storyboard(plan):
    """Fit and pin labels locally; never rewrite claims or silently drop geometry."""
    import copy
    from .media import font, wrap
    output = copy.deepcopy(plan)
    if not isinstance(output, list):
        raise ValueError('Four executable storyboard scenes required')
    draw = ImageDraw.Draw(Image.new('RGB', (540, 960)))
    changes = []
    for scene_index, scene in enumerate(output):
        occupied = []
        geometry = [o for o in scene.get('objects',[]) if o.get('type') != 'text']
        if geometry:
            first=min(o.get('reveal',0) for o in geometry)
            last=max(o.get('until',1) for o in geometry)
            if not 0 <= first < last <= 1:
                raise ValueError('Invalid scene visibility interval')
            if first != 0 or last != 1:
                for i,obj in enumerate(scene['objects']):
                    before=copy.deepcopy(obj)
                    for key,default in (('reveal',0),('until',1)):
                        obj[key]=max(0,min(1,(obj.get(key,default)-first)/(last-first)))
                    changes.append({'scene':scene_index,'object':i,'before':before,'after':copy.deepcopy(obj)})
        for object_index, obj in enumerate(scene.get('objects', [])):
            if obj.get('type') != 'text':
                continue
            box = obj.get('box')
            if not isinstance(box,list) or len(box)!=4 or not all(
                    isinstance(v,(int,float)) and math.isfinite(v) for v in box):
                raise ValueError('Invalid drawing coordinates')
            x,y,w,h = box
            if not (38 <= x < 460 and 210 <= y < 680 and w > 0):
                raise ValueError('Drawing outside safe area')
            size = obj.get('size',22)
            if not isinstance(size,int) or not 16 <= size <= 32:
                raise ValueError('Illegible drawing label size')
            before = copy.deepcopy(obj)
            fitted = None
            # Keep the label near its authored anchor, in at most two lines.
            # Expand its reserved height before reducing readable type size.
            for candidate_size in range(size,15,-1):
                try: lines=wrap(draw,obj.get('text',''),font(candidate_size),min(w,460-x))
                except ValueError: continue
                if not lines or len(lines)>2: continue
                height=len(lines)*(candidate_size+6)
                for delta in [0]+[v for step in range(4,65,4) for v in (step,-step)]:
                    top=y+delta
                    if top<210 or top+height>680: continue
                    candidate=[x,top,min(w,460-x),height]
                    if any(x<a+c and x+candidate[2]>a and top<b+d and top+height>b
                           for a,b,c,d in occupied): continue
                    fitted=(candidate,candidate_size);break
                if fitted:break
            if not fitted:
                raise ValueError('Drawing label cannot fit safely; shorten label or redesign scene')
            obj['box'],obj['size']=fitted
            obj.pop('move',None);obj.pop('motion_path',None);obj.pop('rotate',None)
            occupied.append(obj['box'])
            if before != obj:
                changes.append({'scene':scene_index,'object':object_index,
                                'before':before,'after':copy.deepcopy(obj)})
    return output, changes


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
            rotation=obj.get('rotate',0)
            if (not isinstance(rotation,(int,float)) or not math.isfinite(rotation) or
                    abs(rotation)>45 or (rotation and kind not in ('rect','ellipse'))):
                raise ValueError('Unsupported drawing rotation')
            is_path = kind in ('line','arrow')
            if (not is_path and (w <= 0 or h <= 0)) or (is_path and w == 0 and h == 0 and obj.get('end', [x,y]) == [x,y]):
                raise ValueError('Empty drawing')
            if kind in ('line','arrow'):
                end = obj.get('end')
                if end is not None and (not isinstance(end,list) or len(end)!=2 or
                    not all(isinstance(v,(int,float)) and math.isfinite(v) for v in end) or
                    not 38 <= end[0] <= 460 or not 210 <= end[1] <= 680):
                    raise ValueError('Invalid path endpoint')
            for dx, dy in ([0, 0], move):
                ex, ey = obj.get('end', [x+w, y+h]) if is_path else (x+w, y+h)
                if not (38 <= min(x,ex)+dx <= max(x,ex)+dx <= 460 and
                        210 <= min(y,ey)+dy <= max(y,ey)+dy <= 680):
                    raise ValueError('Drawing outside safe area')
            if rotation:
                for dx,dy in ([0,0],move):
                    if any(not (38 <= px+dx <= 460 and 210 <= py+dy <= 680) for px,py in rotated_points(obj)):
                        raise ValueError('Rotated drawing outside safe area')
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
    for obj in sorted(scene['objects'], key=lambda obj: obj['type']=='text'):
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
        if obj.get('rotate',0) and kind in ('rect','ellipse'):
            points=rotated_points({**obj,'box':[x,y,w,h]})
            draw.polygon(points,fill=color if obj.get('filled',True) else None,outline=color,width=3)
        elif kind == 'rect':
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
            if obj['color'] in ('dark','panel'): color=COLORS['ink']
            draw.rounded_rectangle((x,y,x+w,y+h),radius=4,fill=COLORS['dark'])
            for n, line in enumerate(wrap(draw, obj['text'], font(size), w)):
                draw.text((x,y+n*(size+6)), line, font=font(size), fill=color)


def visual_signature(episode):
    return digest([[o for o in s['objects'] if o['type'] != 'text']
                   for s in episode.get('storyboard', [])])
