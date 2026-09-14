"""Nine authored visual explanations. Each state changes what the viewer learns."""
from copy import deepcopy
import math


def shape(kind, x, y, w, h, color='accent', **kw):
    return dict(type=kind, box=[x,y,w,h], color=color, **kw)


def label(text, x, y, w=360, size=22, color='ink', h=64):
    return shape('text',x,y,w,h,color,text=text,size=size)


def scene(heading, purpose, objects, example=False):
    return dict(heading=heading,purpose=purpose,objects=deepcopy(objects),example=example)


def barcode(x,y,w=150,h=85,variant=0):
    return [shape('rect',x+i*w/30,y,max(1,w/70),h,'ink')
            for i in range(30) if (i+variant)%4 != 1]


def board(key):
    frames=[]
    for i in range(4):
        if key == 'gps':
            objects=[shape('rect',65,300,95,240,'panel'),shape('rect',335,300,95,240,'panel'),
                     shape('rect',195,270,100,345,'dark'),
                     shape('ellipse',236,565,18,18,'accent'), label('YOU',215,614,100,18)]
            if i == 0:
                objects += [shape('ellipse',210,390,20,20,'warm',move=[55,45]),
                            label('Map estimate',70,218,290,23,'warm')]
            else:
                objects += [shape('arrow',235,240,5,310,'accent')]
                if i >= 2:
                    objects += [shape('line',240,245,94,155,'warm'),
                                shape('line',334,400,1,1,'warm',end=[245,570]),
                                label('Reflected route',67,218,310,22,'warm')]
                if i == 3:
                    objects += [shape('ellipse',196,525,98,98,'warm',filled=False)]
            heads=['You stayed put.','A signal needs a route.','A wall adds a detour.','The estimate can shift.']
        elif key == 'bluetooth':
            objects=[label('RADIO CHANNELS',70,227,340,23)]
            for n in range(6):
                objects += [shape('rect',65+n*62,360,35,190,'red' if n==2 and i>=1 else 'panel')]
            path=([0,1,2,3,4,5] if i<2 else [0,1,3,4,5])
            for n,lane in enumerate(path):
                objects += [shape('ellipse',72+lane*62,425,20,20,'accent',
                            reveal=n/len(path),until=(n+1)/len(path))]
            if i>=1: objects += [label('Interference',125,575,300,22,'warm')]
            if i==3: objects += [shape('arrow',80,630,325,1,'accent')]
            heads=['Your audio keeps playing.','One channel gets noisy.','That channel is skipped.','The sequence adapts.']
        elif key == 'dns':
            objects=[shape('rect',55,225,385,72,'paper'),label('example.org',75,243,330,26,'dark')]
            if i>=1: objects += [shape('arrow',239,309,1,47),shape('rect',125,365,240,90,'panel'),label('DNS resolver',148,385,200,24)]
            if i>=2: objects += [shape('arrow',239,466,1,43),shape('rect',85,520,320,82,'dark'),label('Internet address',104,543,280,23)]
            if i==0: objects += [shape('ellipse',207,413,70,70,'warm',filled=False),label('Where does it connect?',70,556,350,23)]
            if i==3: objects += [shape('rect',104,617,279,52,'accent'),label('Browser can connect',114,627,265,20,'dark',h=28)]
            heads=['A name in the address bar.','Find its internet address.','The resolver gets an answer.','Now contact the website.']
        elif key == 'roundabout':
            orbit=[[250+94*math.cos(math.radians(145-n*10))-14,
                    418+94*math.sin(math.radians(145-n*10))-10] for n in range(37)]
            objects=[shape('ellipse',132,300,236,236,'muted'),shape('ellipse',183,351,134,134,'dark'),
                     shape('rect',55,490,135,42,'muted'),shape('rect',68,499,32,22,'warm'),
                     shape('rect',orbit[0][0],orbit[0][1],28,20,'accent',motion_path=orbit)]
            if i>=1: objects += [shape('arrow',80,580,58,1,'warm'),label('Curved approach',70,225,330,23)]
            if i>=2: objects += [label('YIELD',51,435,120,22,'warm'),shape('line',110,482,40,1,'warm')]
            if i==3:
                objects[3]['motion_path']=[[68,499],[104,499],[133,489],[157,461]]
                objects[3]['motion_start']=.55
                objects += [label('Wait for a gap',96,615,320,23)]
            heads=['Why the bend?','The approach slows traffic.','Traffic inside goes first.','Enter after the gap opens.']
        elif key == 'baggage':
            objects=[]
            for x in (64,284):
                objects += [shape('rect',x,345,148,195,'panel'),shape('rect',x+46,310,52,34,'muted',filled=False)]
            if i==0: objects += [label('Same-looking suitcases',67,235,360,24)]
            else:
                objects += barcode(82,397,108,70)+barcode(301,397,108,70,variant=1)
                objects += [label('BAG A',82,484,120,20),label('BAG B',302,484,120,20)]
            if i>=2: objects += [shape('rect',100,571,285,90,'paper'),label('Your bag ID receipt',121,596,244,21,'dark')]
            if i==3: objects += [shape('line',99,674,285,1,'warm')]
            heads=['They look almost identical.','The tag identifies the bag.','You get an ID label too.','Keep your matching label.']
        elif key == 'screening':
            objects=[shape('rect',95,365,300,195,'panel'),shape('rect',198,323,90,42,'muted',filled=False)]
            if i==0 or i==3:
                objects += [shape('rect',147,399,196,123,'paper'),label('Inspection\nnotice',162,422,166,24,'dark')]
            if i==1:
                objects += [shape('rect',72,290,348,300,'muted',filled=False),shape('line',77,310,335,1,'accent',move=[0,240])]
            if i==2:
                objects += [shape('rect',95,265,300,83,'muted',filled=False),label('Physical check',106,605,300,24)]
            if i==3: objects += [shape('arrow',345,540,60,75,'warm')]
            heads=['A note inside your suitcase.','TSA screens checked bags.','Some bags are opened.','The note records the check.']
        elif key == 'unit':
            objects=[shape('rect',77,323,123,145,'warm'),shape('rect',268,260,163,208,'accent'),
                     label('100 g',85,403,103,22,'dark'),label('200 g',297,403,120,22,'dark'),
                     label('$2',101,488,100,30,'warm'),label('$3',314,488,100,30,'accent')]
            if i==1: objects += [label('Compare equal weights',61,575,360,24)]
            if i>=2: objects += [label('$2 / 100 g',55,583,185,24,'warm'),label('$1.50 / 100 g',260,583,199,24,'accent')]
            if i==2: objects += [shape('line',72,549,136,1,'warm')]
            if i==3: objects += [shape('rect',260,567,199,80,'accent',filled=False)]
            heads=['Which pack is better value?','Use the same unit.','The small pack costs less...','...but more per 100 grams.']
        elif key == 'barcode':
            objects=barcode(67,300,170,126)
            objects += [label('SAME ITEM CODE',58,447,200,18)]
            if i==0:
                objects += [shape('rect',290,307,137,116,'warm'),label('$3',315,340,100,32,'dark')]
            else:
                objects += [shape('arrow',250,365,32,1),shape('rect',295,302,142,170,'panel'),label('Store\ndatabase',309,321,124,21)]
                objects += [label('$2' if i==1 else '$3',322,414,96,28,'accent')]
            if i>=2: objects += [shape('line',66,315,170,1,'warm',move=[0,103])]
            if i==3: objects += [label('Update the price record',64,574,366,24)]
            heads=['New price. Same stripes.','Scan an item identifier.','Look up the current price.','The price lives elsewhere.']
        elif key == 'payment':
            objects=[shape('rect',65,325,150,90,'warm',move=[94,20]),shape('rect',309,301,120,190,'panel'),
                     shape('rect',329,325,80,75,'accent',filled=False),label('EMV tap',91,227,300,26)]
            if i>=1: objects += [shape('rect',78,558,345,82,'dark'),label('CODE A' if i<2 else 'CODE B',150,581,246,28,'accent')]
            if i>=1:
                objects += [shape('ellipse',115+n*49,650,12,12,'accent')
                            for n in ([0,2,4] if i==1 else [1,3,5])]
            if i==0: objects += [shape('arrow',250,366,36,1,'accent')]
            if i==2: objects += [label('Next transaction',98,491,320,23)]
            if i==3: objects += [label('One layer of protection',69,491,385,23)]
            heads=['Two identical-looking taps.','One transaction, one code.','Tap again. A fresh code.','Useful, with limits.']
        else:
            raise ValueError('No authored storyboard for this mechanism')
        frames.append(scene(heads[i], heads[i], objects, key in ('unit','barcode','payment')))
    return frames
