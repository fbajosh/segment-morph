"""Three imported SVG states in an editable, automatically closed loop.

Every adjacent ordered pair receives a pair-specific articulated morph.
No target image is synthesized: A, B, and C are the uploaded artworks.
The last state always morphs into the first. Independently directed legs
advance an XW rotation; reverse routes are NOT mere reversed frame lists.
"""
from __future__ import annotations

import re
import math
import networkx as nx
from .geometry import parse_svg, normalize
from .graph import build_graph, components
from .hypermorph import (create_hyper_project, evaluate_hyper, _hypercube_axes,
                         inverse_projection, project4, rotate_xw)

LETTERS = ('A','B','C')
DEFAULT_MOTION = {'easing':'linear', 'rotation_step_deg':55.,
                  'depth_strength':.72, 'stagger':.72, 'hinge_release':.45,
                  'return_twist_deg':34.}


def validate(images, order, durations, motion, frames_per_leg, holds=None):
    if set(images)!=set(LETTERS) or not all(isinstance(images[k],str) and re.search(r'<svg(?:\s|>)',images[k],flags=re.I) for k in LETTERS):
        raise ValueError('Upload three SVG line drawings, one each for A, B, and C')
    if not 2 <= len(order) <= 12 or not all(k in LETTERS for k in order):
        raise ValueError('The loop order must contain 2 to 12 steps using A, B, or C')
    if len(durations)!=len(order) or any(not math.isfinite(float(d)) or not .25<=float(d)<=15 for d in durations):
        raise ValueError('Provide a 0.25–15 second duration for every step, including the closing leg')
    if holds is not None and (len(holds)!=len(order) or any(not math.isfinite(float(h)) or not 0<=float(h)<=15 for h in holds)):
        raise ValueError('Provide a 0–15 second hold after every transition')
    if not 5<=frames_per_leg<=151:raise ValueError('Frames per leg must be 5–151')
    if motion['easing'] not in ('linear','smooth','smoother'):raise ValueError('Unknown easing')
    for k,low,high in (('rotation_step_deg',0,90),('depth_strength',0,1),
                       ('stagger',0,.9),('hinge_release',0,.9),('return_twist_deg',0,75)):
        v=float(motion[k])
        if not math.isfinite(v) or not low<=v<=high:raise ValueError(f'{k} must be {low}–{high}')


def _ease(u,mode):
    if mode=='linear':return u
    if mode=='smooth':return u*u*(3-2*u)
    return u*u*u*(u*(6*u-15)+10)


def _graph(svg,width,height,padding,tolerance):
    geom=normalize(parse_svg(svg),width,height,padding)
    graph=build_graph(geom,tolerance)
    if len(components(graph))!=1:raise ValueError('Each drawing must be a single connected SVG wireframe')
    if not graph.edges:raise ValueError('The SVG has no straight-line segments')
    return graph.as_dict(), geom.as_dict()


def _nx_graph(g):
    ids={v['id']:i for i,v in enumerate(g['vertices'])}
    n=nx.Graph();n.add_nodes_from(range(len(ids)))
    n.add_edges_from((ids[e['source']],ids[e['target']]) for e in g['edges'])
    return n


def _iso_mapping(g1,g2):
    """Choose minimal-displacement graph isomorphism; none if topology differs."""
    g=nx.isomorphism.GraphMatcher(_nx_graph(g1),_nx_graph(g2))
    if not g.is_isomorphic():return None
    a=g1['vertices'];b=g2['vertices'];best=None
    for i,mapping in enumerate(g.isomorphisms_iter()):
        score=sum((a[j]['x']-b[k]['x'])**2+(a[j]['y']-b[k]['y'])**2 for j,k in mapping.items())
        if best is None or score<best[0]:best=(score,dict(mapping))
        if i>=4095:break
    return best[1]


def _plan_pair(ga,gb,sa,sb,config):
    if ga['vertices'] and gb['vertices'] and len(ga['edges'])==len(gb['edges']):
        match=_iso_mapping(ga,gb)
        if match is not None:return {'kind':'isomorphic','mapping':match,'hinges':0}
    # Reuse folded-graph planner with the lower edge-count drawing as source.
    # Swapping direction lets the same mechanism contract as well as unfold.
    n1=len(ga['edges']);n2=len(gb['edges'])
    if n1<=n2:src,tgt,forward=sa,sb,True
    else:src,tgt,forward=sb,sa,False
    project=create_hyper_project(src,tgt,config['mode'],config['width'],config['height'],
                                 config['padding'],config['tolerance'],config['seed'])
    return {'kind':'fold','project':project,'base_forward':forward,
            'hinges':len(project['plan']['hinges'])}


def _lift_to_screen(pt,z,w,angle,center,scale):
    xy=((pt[0]-center[0])/scale,(center[1]-pt[1])/scale)
    world=inverse_projection(xy,z,w)
    q=project4(rotate_xw(world,angle))
    return [center[0]+scale*q[0],center[1]-scale*q[1]]


def _iso_frame(ga,gb,mapping,u,motion,phase,width,height):
    """Connected graph deformation with one coherent forward XW rotation."""
    t=_ease(u,motion['easing']);start=ga['vertices'];end=gb['vertices']
    center=(width/2,height/2);scale=max(width,height)*.45
    signs,_,_=_hypercube_axes(gb)
    r=math.radians(motion['rotation_step_deg'])
    # Every phase rotates forward. An additional gentle positive sweep ensures
    # repeated route geometries need not be literal reversals.
    angle=r*t+math.radians(motion['return_twist_deg'])*math.sin(math.pi*t)*(phase%2)
    ids={v['id']:j for j,v in enumerate(start)}
    depth=motion['depth_strength']
    coords=[]
    for i,v in enumerate(start):
        j=mapping[i];to=end[j]
        z,w=signs[j];z*=.4*depth;w*=.85*depth
        # Lift both endpoints so their projection is exact at u=0 and u=1.
        x0=((v['x']-center[0])/scale,(center[1]-v['y'])/scale)
        x1=((to['x']-center[0])/scale,(center[1]-to['y'])/scale)
        p0=inverse_projection(x0,z,w)
        p1=rotate_xw(inverse_projection(x1,z,w),-r)
        # Stagger is a joint-timing preference, not per-edge detachment.
        rank=(i+phase)%max(1,len(start)-1)/max(1,len(start)-1)
        delay=rank*motion['stagger']*.15
        local=max(0.,min(1.,(t-delay)/(1-delay)))
        world=tuple(x+(y-x)*local for x,y in zip(p0,p1))
        q=project4(rotate_xw(world,angle))
        coords.append([center[0]+scale*q[0],center[1]-scale*q[1]])
    if u==0:coords=[[v['x'],v['y']] for v in start]
    if u==1:coords=[[end[mapping[i]]['x'],end[mapping[i]]['y']] for i in range(len(start))]
    return [[*coords[ids[e['source']]],*coords[ids[e['target']]]] for e in ga['edges']]


def _fold_frame(plan,u,motion,phase,width,height):
    forward=plan['base_forward'];p=plan['project']
    # Reversed graph topology is handled by running a separate directed
    # evaluation, with a forward-only 4D counter-sweep instead of a replay.
    q=u if forward else 1-u
    v=evaluate_hyper(p,q,{'rotation_deg':motion['rotation_step_deg'],
             'depth_strength':motion['depth_strength'],'stagger':motion['stagger'],
             'hinge_release':motion['hinge_release'],
             'easing':motion['easing'] if motion['easing']!='smoother' else 'smooth'})
    positions=v['vertices']
    if not forward and 0<u<1:
        center=(width/2,height/2);scale=max(width,height)*.45
        angle=math.radians(motion['return_twist_deg'])*math.sin(math.pi*u)
        # Nonzero forward-XW deformation. All edges use shared coordinates.
        positions={key:_lift_to_screen(pos,0.,.15*motion['depth_strength'],angle,center,scale)
                   for key,pos in positions.items()}
    return [[*positions[e['source']],*positions[e['target']]] for e in v['edges']]


def _frame_leg(plan,ga,gb,u,motion,phase,width,height):
    if plan['kind']=='hold':return [[v['x'],v['y'],w['x'],w['y']] for v,w in []]
    if plan['kind']=='isomorphic':return _iso_frame(ga,gb,plan['mapping'],u,motion,phase,width,height)
    return _fold_frame(plan,u,motion,phase,width,height)


def _sample(images, graphs, order, durations, holds, motion, plans, count,width,height):
    legs=[]
    for i,a in enumerate(order):
        b=order[(i+1)%len(order)]
        ga,gb=graphs[a],graphs[b]
        if a==b:
            idx={v['id']:v for v in ga['vertices']}
            static=[[idx[e['source']]['x'],idx[e['source']]['y'],idx[e['target']]['x'],idx[e['target']]['y']] for e in ga['edges']]
            lines=[static for _ in range(count)];kind='hold';hinges=0
        else:
            key=tuple(sorted((a,b)))
            plan=plans[key]
            if a!=key[0]:
                # A graph-isomorphic pair requires a directed correspondence.
                if plan['kind']=='isomorphic':
                    inverse={v:k for k,v in plan['mapping'].items()}
                    directed={**plan,'mapping':inverse}
                else:directed={**plan,'base_forward':not plan['base_forward']}
            else:directed=plan
            lines=[_frame_leg(directed,ga,gb,k/(count-1),motion,i,width,height) for k in range(count)]
            kind=plan['kind'];hinges=plan['hinges']
        edge_a=ga['edges'][0];edge_b=gb['edges'][0]
        legs.append({'from':a,'to':b,'kind':kind,'hinges':hinges,
                     'duration':float(durations[i]),'hold':float(holds[i]),'frames':lines,
                     'stroke_from':edge_a['stroke'],'stroke_to':edge_b['stroke'],
                     'width_from':edge_a['stroke_width'],'width_to':edge_b['stroke_width']})
    return legs


def create_sequence_project(images:dict, order=None, durations=None, motion=None,
                            mode='coverage',width=900,height=640,padding=30,tolerance=.5,
                            seed=17,frames_per_leg=61,holds=None):
    order=list(order or ['A','B','A','C'])
    durations=list(durations) if durations is not None else [2.4]*len(order)
    holds=list(holds) if holds is not None else [.75]*len(order)
    motion={**DEFAULT_MOTION,**(motion or {})}
    validate(images,order,durations,motion,frames_per_leg,holds)
    graphs={}; geoms={}
    for k in LETTERS:graphs[k],geoms[k]=_graph(images[k],width,height,padding,tolerance)
    config=dict(mode=mode,width=width,height=height,padding=padding,tolerance=tolerance,seed=seed)
    cache={}
    for i,a in enumerate(order):
        b=order[(i+1)%len(order)]
        if a==b:continue
        key=tuple(sorted((a,b)))
        if key not in cache:cache[key]=_plan_pair(graphs[key[0]],graphs[key[1]],images[key[0]],images[key[1]],config)
    legs=_sample(images,graphs,order,durations,holds,motion,cache,frames_per_leg,width,height)
    return {'schema_version':8,'engine':'three-svg-sequence','images':images,
            'order':order,'durations':durations,'holds':holds,'motion':motion,'legs':legs,
            'viewport':{'width':width,'height':height},'graphs':graphs,
            'geometry':geoms,'planning':config,'frames_per_leg':frames_per_leg,
            'export':{'fps':60},'auto_loop':True,'closing_leg':f'{order[-1]} → {order[0]}'}


def rebake_sequence_project(project,order=None,durations=None,motion=None,holds=None):
    return create_sequence_project(project['images'],order or project['order'],
                durations if durations is not None else project['durations'], motion if motion is not None else project['motion'],
                **project['planning'], frames_per_leg=project['frames_per_leg'],
                holds=holds if holds is not None else project.get('holds', [0.]*len(project['order'])))
