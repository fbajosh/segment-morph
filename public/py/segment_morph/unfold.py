"""V0.3 articulated graph unfolding.

Fold a destination graph onto an existing source drawing. Target edges at t=0
are overlays of actual source edges, not zero-length growth or a global hub.
A spanning destination core shares vertex coordinates throughout. Extra edges
unfold as attached hinged branches and merge into destination junctions by t=1.

This is a constrained heuristic, not an arbitrary optimal graph-edit solver.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from math import hypot, log, isfinite
from pathlib import Path
import random

from .geometry import parse_svg, normalize
from .graph import Graph, build_graph, components
from .motion import ease

DEFAULT_MOTION = {
    'duration': 3.8, 'easing': 'smooth', 'rigidity': 0.72,
    'unfold_start': 0.0, 'unfold_end': 1.0,
    'stagger': 0.38,
}
MODES = {'coverage', 'spatial', 'structure'}


def _positions(g):
    return [(v.x, v.y) for v in g.vertices]


def _links(g):
    ids = {v.id: i for i, v in enumerate(g.vertices)}
    return [(ids[e.source], ids[e.target]) for e in g.edges]


def _components(n, edges):
    p = list(range(n))
    def root(x):
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x
    for a, b in edges:
        ra, rb = root(a), root(b)
        if ra != rb: p[ra] = rb
    return len({root(i) for i in range(n)})


def _search_mapping(source: Graph, target: Graph, mode='coverage', seed=0):
    if mode not in MODES: raise ValueError(f'Unknown unfolding mode: {mode}')
    sxy = _positions(source); txy = _positions(target)
    se = _links(source); te = _links(target)
    sn, tn = len(sxy), len(txy)
    idx = {frozenset((a, b)): k for k, (a, b) in enumerate(se)}
    slens = [hypot(sxy[a][0]-sxy[b][0], sxy[a][1]-sxy[b][1]) for a,b in se]
    tlens = [hypot(txy[a][0]-txy[b][0], txy[a][1]-txy[b][1]) for a,b in te]
    proximity = [[hypot(x[0]-y[0], x[1]-y[1]) for x in sxy] for y in txy]
    # Endpoint geometry (complete source coverage) is a prerequisite, not a
    # soft visual preference. Coverage receives the dominant coefficient.
    geo_w = {'coverage':.028, 'spatial':.11, 'structure':.014}[mode]
    inv_w = {'coverage':15, 'spatial':14, 'structure':23}[mode]
    length_w = {'coverage':1.1, 'spatial':1., 'structure':4.}[mode]

    def details(mapping):
        hits = [0]*len(se)
        valid=[]; invalid=[]; mismatch=0
        for k,(a,b) in enumerate(te):
            u,v = mapping[a],mapping[b]
            index=idx.get(frozenset((u,v))) if u!=v else None
            if index is None:invalid.append(k)
            else:
                valid.append((a,b));hits[index]+=1
                mismatch += abs(log(max(.001,tlens[k])/max(.001,slens[index])))
        miss=sum(c==0 for c in hits)
        comp=_components(tn,valid)
        unused=sn-len(set(mapping))
        spatial=sum(proximity[j][mapping[j]] for j in range(tn))/tn
        duplicates=sum(max(0,c-2)**2 for c in Counter(mapping).values())
        # Strongly favor full geometric coverage, then maintaining the target
        # spanning graph and keeping the number of hinged edges low.
        score = miss*95 + max(0,comp-1)*120 + len(invalid)*inv_w + unused*23 \
                + spatial*geo_w + mismatch*length_w + duplicates*3
        return score, hits, valid, invalid, spatial, comp

    rng=random.Random(seed)
    best=None
    for restart in range(19):
        if restart==0:
            z=[min(range(sn),key=lambda i:(proximity[j][i],i)) for j in range(tn)]
        elif restart<4 or best is None:
            z=[rng.randrange(sn) for _ in range(tn)]
        else:
            z=best[1].copy()
            for _ in range(3+restart%5):z[rng.randrange(tn)]=rng.randrange(sn)
        current=details(z)[0]
        for iteration in range(13000):
            j=rng.randrange(tn); old=z[j]
            if iteration%9==0:
                k=rng.randrange(tn);z[j],z[k]=z[k],z[j]
            else:
                k=-1;z[j]=rng.randrange(sn)
            score=details(z)[0]
            temp=23 * (0.008/23)**(iteration/13000)
            accept=score<=current or rng.random()<__import__('math').exp(max(-80,(current-score)/temp))
            if accept:current=score
            else:
                if k<0:z[j]=old
                else:z[j],z[k]=z[k],z[j]
            if best is None or current<best[0]:best=(current,z.copy())
        if best and details(best[1])[1] and sum(x==0 for x in details(best[1])[1])==0 and restart>=10:
            break
    score,z=best
    _,hits,valid,invalid,spatial,comp=details(z)
    return z, {'objective':round(score,4), 'covered_edges':sum(x>0 for x in hits),
               'source_edge_count':len(se), 'hinge_edges':len(invalid),
               'core_components':comp, 'mean_vertex_displacement':round(spatial,2),
               'source_coverage':len(se)-sum(x==0 for x in hits),
               'source_hit_counts':hits}


def create_unfold_project(source_svg: str,target_svg: str, mode='coverage',
                          width=900,height=640,padding=30,tolerance=.5,seed=17):
    if mode not in MODES:raise ValueError('Unsupported fold-matching mode')
    src=normalize(parse_svg(source_svg),width,height,padding)
    dst=normalize(parse_svg(target_svg),width,height,padding)
    sg=build_graph(src,tolerance);tg=build_graph(dst,tolerance)
    if len(components(sg))!=1 or len(components(tg))!=1:
        raise ValueError('v0.3 unfolding currently requires connected source and target graphs')
    if len(tg.edges)<len(sg.edges):
        raise ValueError('v0.3 unfolding needs at least as many destination edges as source edges. Contraction needs a future planner.')
    z,diagnostics=_search_mapping(sg,tg,mode,seed)
    if diagnostics['covered_edges']!=len(sg.edges):
        raise ValueError(f'Could not cover every source edge with target strokes ({diagnostics["covered_edges"]}/{len(sg.edges)}). Try another strategy or seed. No disappearing source rods were inserted.')
    if diagnostics['core_components']!=1:
        raise ValueError('Folded target core did not remain connected. Try a different strategy.')
    sxy=_positions(sg);txy=_positions(tg)
    se=_links(sg);te=_links(tg)
    adjacency={i:set() for i in range(len(sxy))}
    for a,b in se: adjacency[a].add(b);adjacency[b].add(a)
    s_links={frozenset((a,b)) for a,b in se}
    hinges=[]
    for k,(a,b) in enumerate(te):
        sa,sb=z[a],z[b]
        if sa!=sb and frozenset((sa,sb)) in s_links:continue
        options=[]
        for u,v in ((a,b),(b,a)):
            root=z[u]
            for neighbor in adjacency[root]:
                # Orient an existing line as a hinged duplicate. Both ends
                # initially lie on real source graph vertices.
                distance=hypot(sxy[neighbor][0]-txy[v][0],sxy[neighbor][1]-txy[v][1])
                ideal=hypot(txy[u][0]-txy[v][0],txy[u][1]-txy[v][1])
                old=hypot(sxy[root][0]-sxy[neighbor][0],sxy[root][1]-sxy[neighbor][1])
                options.append((distance*.8+abs(ideal-old)*.45,u,v,neighbor))
        _,u,v,neighbor=min(options)
        hinges.append({'edge_index':k,'root_vertex':u,'tip_vertex':v,'source_neighbor':neighbor})
    # Breadth-first structural order for progressive, connected unfolding.
    from collections import deque
    graph_adjacency=[set() for _ in range(len(txy))]
    for a,b in te:graph_adjacency[a].add(b);graph_adjacency[b].add(a)
    first=min(range(len(txy)),key=lambda j:hypot(sxy[z[j]][0]-txy[j][0],sxy[z[j]][1]-txy[j][1]))
    depths={first:0};q=deque([first])
    while q:
        u=q.popleft()
        for v in sorted(graph_adjacency[u]):
            if v not in depths:depths[v]=depths[u]+1;q.append(v)
    maxdepth=max(depths.values()) or 1
    order=[depths[j]/maxdepth for j in range(len(txy))]
    # Preserve stroke styling globally. Individual target edges remain shared
    # through their four-degree target graph vertices where not hinged.
    return {'schema_version':3, 'engine':'articulated-unfold',
            'viewport':{'width':width,'height':height,'padding':padding},
            'source':src.as_dict(),'target':dst.as_dict(),
            'source_graph':sg.as_dict(),'target_graph':tg.as_dict(),
            'plan':{'mode':mode,'seed':seed,'target_to_source':z,'hinges':hinges,'unfold_ranks':order,
                    'diagnostics':diagnostics,
                    'description':'Destination graph folded onto original edges, then articulated into its target shape'},
            'motion':dict(DEFAULT_MOTION),
            'assets':{'source_svg':source_svg,'target_svg':target_svg}}


def _blend(a,b,t):return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t]


def evaluate_unfold(project:dict,t:float,motion:dict|None=None):
    if not (isfinite(t) and 0<=t<=1):raise ValueError('Frame progress must be [0,1]')
    m={**DEFAULT_MOTION, **(project.get('motion',{}) if motion is None else motion)}
    a,b=float(m['unfold_start']),float(m['unfold_end'])
    if not 0<=a<b<=1:raise ValueError('Invalid unfold window')
    rigidity=float(m['rigidity'])
    if not 0<=rigidity<=1:raise ValueError('Rigidity must be [0,1]')
    stagger=float(m.get('stagger',0))
    if not 0<=stagger<=.8:raise ValueError('Stagger must be in [0,0.8]')
    easing=m['easing'];q=ease((t-a)/(b-a),easing)
    sg=project['source_graph'];tg=project['target_graph'];pl=project['plan']
    sp=[[v['x'],v['y']] for v in sg['vertices']]
    tp=[[v['x'],v['y']] for v in tg['vertices']]
    links=pl['target_to_source']; hinges={h['edge_index']:h for h in pl['hinges']}
    start=[sp[i] for i in links]
    ranks=pl.get('unfold_ranks',[0]*len(start))
    progress=[max(0.,min(1.,(q-rank*stagger*.8)/(1-rank*stagger*.8))) for rank in ranks]
    p=[_blend(old,new,progress[j]) for j,(old,new) in enumerate(zip(start,tp))]
    # Each hinge is a second endpoint separate from the named target vertex
    # until completion; its other endpoint remains on the connected core.
    tips={k:_blend(sp[h['source_neighbor']],tp[h['tip_vertex']],progress[h['tip_vertex']])
          for k,h in hinges.items()}
    edges=tg['edges']; vidx={v['id']:i for i,v in enumerate(tg['vertices'])}
    indexed=[(vidx[e['source']],vidx[e['target']]) for e in edges]
    original_lengths=[];ending_lengths=[]
    for i,(u,v) in enumerate(indexed):
        if i in hinges:
            h=hinges[i];old_a=start[h['root_vertex']];old_b=sp[h['source_neighbor']]
        else:old_a,old_b=start[u],start[v]
        original_lengths.append(hypot(old_a[0]-old_b[0],old_a[1]-old_b[1]))
        ending_lengths.append(hypot(tp[u][0]-tp[v][0],tp[u][1]-tp[v][1]))
    # Projected position-based rod constraints (deterministic iterations).
    # Endpoints are exact by construction; the positional tether limits
    # distortion of the global silhouette, preserving most edge lengths.
    if 0<q<1 and rigidity>0:
        stiffness = rigidity*.9 * min(1,q*14,(1-q)*14)
        for iteration in range(36):
            for k,(u,v) in enumerate(indexed):
                h=hinges.get(k)
                ra=h['root_vertex'] if h else u
                x=p[ra];y=tips[k] if h else p[v]
                dx=y[0]-x[0];dy=y[1]-x[1]
                dist=hypot(dx,dy)
                rest=original_lengths[k]*(1-q)+ending_lengths[k]*q
                if dist<1e-8:
                    # Deterministic preferred direction for coincident nodes.
                    dx=tp[v][0]-tp[u][0];dy=tp[v][1]-tp[u][1]
                    dist=hypot(dx,dy)
                    if dist<1e-8:continue
                corr=(dist-rest)/dist * stiffness * .5
                # source/target vertices shared exactly by all core edges.
                x[0]+=dx*corr;x[1]+=dy*corr
                y[0]-=dx*corr;y[1]-=dy*corr
            # Tether to interpolated vertex correspondence to prevent
            # folding the whole object into a low-energy but tiny blob.
            tether=.16 + .22*(1-rigidity)
            for j in range(len(p)):
                preferred=_blend(start[j],tp[j],progress[j])
                p[j][0]+=(preferred[0]-p[j][0])*tether
                p[j][1]+=(preferred[1]-p[j][1])*tether
            for k,h in hinges.items():
                preferred=_blend(sp[h['source_neighbor']],tp[h['tip_vertex']],progress[h['tip_vertex']])
                tips[k][0]+=(preferred[0]-tips[k][0])*tether
                tips[k][1]+=(preferred[1]-tips[k][1])*tether
    if q==0 or t==0:
        # Every starting edge is an exact source edge overlay.
        pass
    if q==1 or t==1:
        p=[list(x) for x in tp]
        tips={k:list(tp[h['tip_vertex']]) for k,h in hinges.items()}
    vmap={v['id']:p[j] for j,v in enumerate(tg['vertices'])}
    segments=[]; ratios=[]
    src_style=sg['edges'][0]; dest_edges=tg['edges']
    for k,(u,v) in enumerate(indexed):
        h=hinges.get(k)
        pu=p[h['root_vertex']] if h else p[u]
        pv=tips[k] if h else p[v]
        ed=dest_edges[k]
        start_length=original_lengths[k]
        length=hypot(pu[0]-pv[0],pu[1]-pv[1])
        ratios.append(length/max(.001,start_length))
        segments.append({'id':'u:'+ed['id'],'source':ed['source'] if not h else tg['vertices'][h['root_vertex']]['id'],
                         'target':ed['target'] if not h else 'tip:'+ed['id'],
                         'a':list(pu),'b':list(pv),
                         'stroke':src_style['stroke'] if q<.5 else ed['stroke'],
                         'stroke_width':src_style['stroke_width']*(1-q)+ed['stroke_width']*q,
                         'stroke_linecap':src_style['stroke_linecap'] if t==0 else ed['stroke_linecap'], 'stroke_opacity':1,
                         'hinge':bool(h)})
        if h:vmap['tip:'+ed['id']]=list(pv)
    # Diagnostic stage extent, including hinges. Midpoint cannot collapse
    # into a hub because all target vertices retain independent positions.
    all_xy=[*p,*tips.values()]
    area=((max(x[0] for x in all_xy)-min(x[0] for x in all_xy)) *
          (max(x[1] for x in all_xy)-min(x[1] for x in all_xy)))
    return {'t':t,'vertices':vmap,'edges':segments,'visible_count':len(segments),
            'source_visible':0,'target_visible':len(segments),
            'metrics':{'bounding_area':area,'min_length_ratio':min(ratios),
                       'mean_length_ratio':sum(ratios)/len(ratios),
                       'hinges':len(hinges),'core_components':pl['diagnostics']['core_components']}}


def sample_frames(project:dict,count:int=161,rigidity:float|None=None) -> list[dict]:
    """Deterministic baked timeline; browser interpolation shares graph endpoints."""
    if not 2<=count<=401:raise ValueError('Frame count must be between 2 and 401')
    m={**DEFAULT_MOTION,**project.get('motion',{}),'rigidity':project['motion']['rigidity'] if rigidity is None else rigidity,
       'easing':'linear','unfold_start':0,'unfold_end':1}
    frames=[]
    for i in range(count):
        frame=evaluate_unfold(project,i/(count-1),m)
        # Save one coordinate per shared target vertex, and optional hinged tips;
        # the edges themselves are assembled client-side using their references.
        frames.append({'vertices':frame['vertices'],'metrics':frame['metrics']})
    return frames


def project_with_frames(*args,**kwargs):
    project=create_unfold_project(*args,**kwargs)
    project['frames']=sample_frames(project)
    return project
