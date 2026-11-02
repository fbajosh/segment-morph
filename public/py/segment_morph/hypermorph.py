"""v0.4 shared-vertex 4D-coupled morph.

Every animated junction lives in a common four-dimensional space. A fixed
camera projects all vertices; the same continuous XW rotation acts on every
vertex at each time. Source and destination image coordinates are constrained
exactly by 4D lifting and inverse rotation at the endpoints.

The topology change is still based on v0.3's source-covering folded graph;
remaining hinges are explicitly reported. This is not a rigid 4D rotation of
one graph into a topologically different graph.
"""
from __future__ import annotations
import math
from pathlib import Path
from functools import lru_cache
import networkx as nx
from .unfold import create_unfold_project, _positions

DEFAULT_HYPER_MOTION = dict(duration=3.8, easing='linear', stagger=.75,
                            rotation_deg=45., depth_strength=.72, hinge_release=.5,
                            unfold_start=0., unfold_end=1.)


def rotate_xw(v, angle):
    x,y,z,w=v
    c,s=math.cos(angle),math.sin(angle)
    return (x*c-w*s,y,z,x*s+w*c)


def project4(v, d4=4., d3=5., view_x=-18., view_y=28.):
    x,y,z,w=v
    f4=d4/(d4-w)
    x,y,z=x*f4,y*f4,z*f4
    vy=math.radians(view_y);vx=math.radians(view_x)
    cy,sy=math.cos(vy),math.sin(vy)
    x,z=x*cy+z*sy,-x*sy+z*cy
    cx,sx=math.cos(vx),math.sin(vx)
    y,z=y*cx-z*sx,y*sx+z*cx
    f3=d3/(d3-z)
    return (x*f3,y*f3)


def inverse_projection(xy, z_camera, w, view_x=-18., view_y=28.):
    """Lift arbitrary image point to world 4D at chosen camera depth and w."""
    x_screen,y_screen=xy
    f3=5./(5.-z_camera)
    x,y,z=x_screen/f3,y_screen/f3,z_camera
    vx=math.radians(view_x);vy=math.radians(view_y)
    cx,sx=math.cos(vx),math.sin(vx)
    y,z=y*cx+z*sx,-y*sx+z*cx
    cy,sy=math.cos(vy),math.sin(vy)
    x,z=x*cy-z*sy,x*sy+z*cy
    f4=4./(4.-w)
    return (x/f4,y/f4,z/f4,w)


def _lerp(a,b,t):return tuple(x+(y-x)*t for x,y in zip(a,b))


def _hypercube_axes(g):
    """Label Q4 vertices and align its W bit with the inner/outer radial split."""
    n=len(g['vertices']); ids={v['id']:i for i,v in enumerate(g['vertices'])}
    graph=nx.Graph();graph.add_nodes_from(range(n))
    graph.add_edges_from((ids[e['source']],ids[e['target']]) for e in g['edges'])
    cube=nx.hypercube_graph(4)
    if n==16 and nx.is_isomorphic(graph,cube):
        cx=sum(v['x'] for v in g['vertices'])/n
        cy=sum(v['y'] for v in g['vertices'])/n
        r=[math.hypot(v['x']-cx,v['y']-cy) for v in g['vertices']]
        best=None
        for mapping in nx.isomorphism.GraphMatcher(graph,cube).isomorphisms_iter():
            # W=bit3: choose the coordinate separating cube shells best.
            sign=[2*mapping[i][3]-1 for i in range(n)]
            score=abs(sum(r[i]*sign[i] for i in range(n)))
            # Z=bit2: favor vertical structure for camera depth.
            zsign=[2*mapping[i][2]-1 for i in range(n)]
            score+=.001*abs(sum(g['vertices'][i]['y']*zsign[i] for i in range(n)))
            if best is None or score>best[0]:best=score,mapping
        mapping=best[1]
        signs=[(2*mapping[i][2]-1,2*mapping[i][3]-1) for i in range(n)]
        return signs,True,[tuple(2*x-1 for x in mapping[i]) for i in range(n)]
    # Non-hypercube targets: deterministic radial/vertical 4D latent layers.
    cx=sum(v['x'] for v in g['vertices'])/max(1,n)
    cy=sum(v['y'] for v in g['vertices'])/max(1,n)
    radii=[math.hypot(v['x']-cx,v['y']-cy) for v in g['vertices']]
    median=sorted(radii)[n//2] if n else 0
    signs=[(1 if v['y']>cy else -1,1 if radii[i]>median else -1)
           for i,v in enumerate(g['vertices'])]
    return signs,False,None


def create_hyper_project(source_svg,target_svg,mode='coverage',width=900,height=640,padding=30,tolerance=.5,seed=17):
    p=create_unfold_project(source_svg,target_svg,mode,width,height,padding,tolerance,seed)
    signs,hypercube,canonical=_hypercube_axes(p['target_graph'])
    p['schema_version']=4;p['engine']='4d-coupled'
    p['motion']=dict(DEFAULT_HYPER_MOTION)
    p['latent']={'axes':signs,'hypercube':hypercube,'canonical':canonical,
                 'camera':{'view_x':-18.,'view_y':28.,'d4':4.,'d3':5.}}
    # For a non-corresponding target edge, keep its extra endpoint attached to
    # a genuine shared target junction mapped to the original source neighbor.
    # It releases later, avoiding loose free tips during the early deformation.
    z=p['plan']['target_to_source'];tp=p['target_graph']['vertices']
    for h in p['plan']['hinges']:
        candidates=[j for j,source_i in enumerate(z) if source_i==h['source_neighbor']]
        tip=tp[h['tip_vertex']]
        anchor=min(candidates,key=lambda j:((tp[j]['x']-tip['x'])**2+(tp[j]['y']-tip['y'])**2,j))
        h['release_anchor']=tp[anchor]['id']
    p['plan']['description']='Shared graph lifted into 4D; global XW rotation and temporarily attached hinge tips' 
    p['frames']=sample_hyper_frames(p)
    p['reference_frames']=reference_frames(p) if hypercube else []
    return p


def _build_lifts(p,m):
    tg=p['target_graph'];sg=p['source_graph'];pl=p['plan']
    sxy=[[v['x'],v['y']] for v in sg['vertices']]
    txy=[[v['x'],v['y']] for v in tg['vertices']]
    signs=p['latent']['axes'];strength=float(m['depth_strength'])
    angle=math.radians(float(m['rotation_deg']))
    vp=p['viewport'];center=(vp['width']/2,vp['height']/2)
    # Normalize against the longer dimension, keeping the XW perspective
    # denominator away from its singularity for extreme aspect ratios.
    scale=max(vp['width'],vp['height'])*.45
    to_norm=lambda xy:((xy[0]-center[0])/scale,(center[1]-xy[1])/scale)
    lifts={}
    for j,v in enumerate(tg['vertices']):
        z,w=signs[j]
        depth=.40*strength*z; fourth=.85*strength*w
        start=sxy[pl['target_to_source'][j]];end=txy[j]
        old=inverse_projection(to_norm(start),depth,fourth)
        new=rotate_xw(inverse_projection(to_norm(end),depth,fourth),-angle)
        lifts[v['id']]=(old,new,pl['unfold_ranks'][j])
    for h in pl['hinges']:
        k=h['edge_index'];v=tg['vertices'][h['tip_vertex']];z,w=signs[h['tip_vertex']]
        depth=.40*strength*z;fourth=.85*strength*w
        old=inverse_projection(to_norm(sxy[h['source_neighbor']]),depth,fourth)
        new=rotate_xw(inverse_projection(to_norm(txy[h['tip_vertex']]),depth,fourth),-angle)
        lifts['tip:'+tg['edges'][k]['id']]=(old,new,pl['unfold_ranks'][h['tip_vertex']])
    return lifts,center,scale,angle


def evaluate_hyper(p,t,motion=None):
    m={**DEFAULT_HYPER_MOTION,**p.get('motion',{}),**(motion or {})}
    if not (math.isfinite(t) and 0<=t<=1):raise ValueError('Frame time must be 0..1')
    strength=float(m['depth_strength']); rotation=float(m['rotation_deg']);stagger=float(m['stagger'])
    if not (0<=strength<=1 and 0<=rotation<=90 and 0<=stagger<=.9):raise ValueError('Invalid 4D controls')
    a=float(m['unfold_start']);b=float(m['unfold_end'])
    if not (0<=a<b<=1):raise ValueError('Invalid movement window')
    q=max(0.,min(1.,(t-a)/(b-a)))
    if m['easing']=='smooth':q=q*q*(3-2*q)
    elif m['easing']=='cubic-in':q=q**3
    elif m['easing']=='cubic-out':q=1-(1-q)**3
    elif m['easing']!='linear':raise ValueError('Unsupported easing')
    lifts,center,scale,angle=_build_lifts(p,m)
    vertices={}
    for id,(start,end,rank) in lifts.items():
        delay=rank*stagger*.68
        local=max(0,min(1,(q-delay)/(1-delay)))
        world=_lerp(start,end,local)
        xy=project4(rotate_xw(world,angle*q))
        vertices[id]=[center[0]+scale*xy[0],center[1]-scale*xy[1]]
    # Hard endpoint snaps remove floating-point accumulation (not visible movement).
    # Initially share the neighboring graph vertex exactly. Release the extra
    # tip smoothly later while its opposite end remains on the target core.
    release=float(m.get('hinge_release',.5))
    if not 0<=release<=.9:raise ValueError('Hinge release must be 0..0.9')
    for h in p['plan']['hinges']:
        name='tip:'+tp_edge_id(p,h['edge_index'])
        anchor=vertices[h['release_anchor']]
        if q<=release:share=0.
        else:
            share=(q-release)/(1-release)
            share=share*share*(3-2*share)
        independent=vertices[name]
        vertices[name]=[anchor[0]+(independent[0]-anchor[0])*share,
                        anchor[1]+(independent[1]-anchor[1])*share]
    if q==0:
        sp=p['source_graph']['vertices'];tp=p['target_graph']['vertices'];z=p['plan']['target_to_source']
        for j,v in enumerate(tp):vertices[v['id']]=[sp[z[j]]['x'],sp[z[j]]['y']]
        for h in p['plan']['hinges']:
            vertices['tip:'+tp_edge_id(p,h['edge_index'])]=[sp[h['source_neighbor']]['x'],sp[h['source_neighbor']]['y']]
    if q==1:
        tp=p['target_graph']['vertices']
        for j,v in enumerate(tp):vertices[v['id']]=[v['x'],v['y']]
        for h in p['plan']['hinges']:
            v=tp[h['tip_vertex']]
            vertices['tip:'+tp_edge_id(p,h['edge_index'])]=[v['x'],v['y']]
    edges=[];tg=p['target_graph'];sg=p['source_graph'];hinges={h['edge_index']:h for h in p['plan']['hinges']}
    for k,e in enumerate(tg['edges']):
        h=hinges.get(k)
        a_id=tg['vertices'][h['root_vertex']]['id'] if h else e['source']
        b_id='tip:'+e['id'] if h else e['target']
        edges.append({'id':'m:'+e['id'],'source':a_id,'target':b_id,
                      'a':vertices[a_id],'b':vertices[b_id],
                      'hinge':bool(h),'stroke':e['stroke'],
                      'stroke_width':sg['edges'][0]['stroke_width']*(1-q)+e['stroke_width']*q,
                      'stroke_linecap':e['stroke_linecap'],'stroke_opacity':1})
    coords=list(vertices.values())
    xmin=min(a[0] for a in coords);xmax=max(a[0] for a in coords)
    ymin=min(a[1] for a in coords);ymax=max(a[1] for a in coords)
    return {'t':t,'vertices':vertices,'edges':edges,
            'metrics':{'bounding_area':(xmax-xmin)*(ymax-ymin),
                       'width':xmax-xmin,'height':ymax-ymin,
                       'hinges':len(hinges),'hypercube':bool(p['latent']['hypercube'])}}


def tp_edge_id(p,k):return p['target_graph']['edges'][k]['id']


def sample_hyper_frames(p,count=121,motion=None):
    if not 2<=count<=401:raise ValueError('Frame count must be between 2 and 401')
    m={**p['motion'],**(motion or {}),'easing':'linear','unfold_start':0,'unfold_end':1}
    frames=[]
    for i in range(count):
        f=evaluate_hyper(p,i/(count-1),m)
        frames.append({'vertices':f['vertices'],'metrics':f['metrics']})
    return frames


def reference_frames(p,count=121):
    """Original reference: true rigid hypercube rotating XW from 0 to 45°.

    Fixed 3D view, fixed scale, no per-frame normalization.
    """
    canonical=p['latent']['canonical']
    if canonical is None:return []
    vp=p['viewport'];cx=vp['width']/2;cy=vp['height']/2
    scale=min(vp['width'],vp['height'])*.275
    frames=[]
    for i in range(count):
        angle=math.radians(45*i/(count-1))
        vv={}
        for j,v in enumerate(p['target_graph']['vertices']):
            px,py=project4(rotate_xw(canonical[j],angle))
            vv[v['id']]=[cx+px*scale,cy-py*scale]
        frames.append({'vertices':vv})
    return frames
