"""Gemini writer contract; independent content and renderer checks still apply."""
from .storyboard import COLORS


def obj(properties, required=None):
    return {'type':'object','properties':properties,
            'required':list(properties) if required is None else required,
            'additionalProperties':False}


def array(item, minimum, maximum):
    return {'type':'array','items':item,'minItems':minimum,'maxItems':maximum}


TEXT={'type':'string'}
NUMBER={'type':'number'}
PRIMITIVE=obj({
    'type':{'type':'string','enum':['rect','ellipse','line','arrow','text']},
    'box':array(NUMBER,4,4),
    'color':{'type':'string','enum':list(COLORS)},
    'filled':{'type':'boolean'},
    'text':TEXT,
    'size':{'type':'integer','minimum':16,'maximum':32},
    'move':array(NUMBER,2,2),
    'reveal':{'type':'number','minimum':0,'maximum':0.7},
    'until':{'type':'number','minimum':0.3,'maximum':1},
}, ['type','box','color'])
SCENE=obj({'heading':TEXT,'purpose':TEXT,'example':{'type':'boolean'},
           'objects':array(PRIMITIVE,3,40)})
DRAFT_SCHEMA=obj({
    **{k:TEXT for k in ('title','claim','claim_id','subject','pillar','topic_id','category','first_comment')},
    'format':{'type':'string','enum':['demonstration','comparison','process']},
    'beats':array(TEXT,4,4),'labels':array(TEXT,4,4),
    'scene_kind':{'type':'string','enum':['storyboard']},
    'evidence':array(obj({'claim':TEXT,'passage_id':TEXT,'scope':TEXT}),1,12),
    'needs_corroboration':{'type':'boolean'},
    'storyboard':array(SCENE,4,4),
    'broll_keywords':array(TEXT,3,6),
    'sound_cues':array(obj({'phrase':TEXT,'kind':{'type':'string','enum':['scan','chime']}}),0,2),
})
