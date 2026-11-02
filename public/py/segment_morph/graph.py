"""Embedded graph extraction and structural diagnostics.

Shared SVG endpoints become shared vertices within a user-defined stage-space
Tolerance. Interior segment crossings are *never* converted to junctions.
"""
from __future__ import annotations
from collections import Counter, deque
from dataclasses import dataclass, asdict
from math import hypot
from typing import Any
from .geometry import Drawing

Point = tuple[float, float]

@dataclass(frozen=True)
class Vertex:
    id: str
    x: float
    y: float

    @property
    def point(self) -> Point:
        return self.x, self.y

@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    stroke: str = '#111111'
    stroke_width: float = 2.
    stroke_linecap: str = 'butt'
    stroke_opacity: float = 1.
    source_element: str = ''

@dataclass(frozen=True)
class Graph:
    vertices: tuple[Vertex, ...]
    edges: tuple[Edge, ...]
    tolerance: float = 0.5

    def as_dict(self) -> dict[str, Any]:
        return {'vertices': [asdict(v) for v in self.vertices],
                'edges': [asdict(e) for e in self.edges],
                'tolerance': self.tolerance,
                'stats': stats(self)}


def build_graph(drawing: Drawing, tolerance: float = 0.5) -> Graph:
    """Extract a graph from a normalized Drawing, joining only endpoints.

    Vertex IDs are deterministic for a given ordered source SVG. Tolerance
    is in normalized viewport units. Geometry is not silently resnapped.
    """
    if not 0 <= tolerance <= 20:
        raise ValueError('Join tolerance must be in [0, 20] stage units')
    vertices: list[Vertex] = []
    edges: list[Edge] = []
    def identify(pt: Point) -> str:
        for vertex in vertices:
            if hypot(pt[0]-vertex.x, pt[1]-vertex.y) <= tolerance:
                return vertex.id
        v = Vertex(f'v-{len(vertices)+1:03d}', *pt)
        vertices.append(v)
        return v.id
    for seg in drawing.segments:
        a = identify(seg.a)
        b = identify(seg.b)
        if a == b:
            raise ValueError(f'Joining tolerance collapses {seg.id} into a self-loop; reduce tolerance')
        edges.append(Edge(seg.id,a,b,seg.stroke,seg.stroke_width,seg.stroke_linecap,
                          seg.stroke_opacity,seg.source_element))
    graph = Graph(tuple(vertices),tuple(edges),tolerance)
    validate_graph(graph)
    return graph


def validate_graph(g: Graph) -> None:
    ids = [v.id for v in g.vertices]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('Graph must contain uniquely identified vertices')
    present = set(ids)
    eid = set()
    for e in g.edges:
        if e.id in eid or e.source not in present or e.target not in present:
            raise ValueError(f'Duplicate edge ID or unknown endpoint for {e.id}')
        if e.source == e.target:
            raise ValueError(f'Self-loop not supported: {e.id}')
        eid.add(e.id)


def adjacency(g: Graph) -> dict[str, list[tuple[str,str]]]:
    adj = {v.id: [] for v in g.vertices}
    for e in g.edges:
        adj[e.source].append((e.target,e.id))
        adj[e.target].append((e.source,e.id))
    return adj


def components(g: Graph) -> list[list[str]]:
    adj=adjacency(g); seen=set(); out=[]
    for v in g.vertices:
        if v.id in seen: continue
        comp=[];stack=[v.id];seen.add(v.id)
        while stack:
            node=stack.pop();comp.append(node)
            for neighbor,_ in adj[node]:
                if neighbor not in seen:
                    seen.add(neighbor);stack.append(neighbor)
        out.append(comp)
    return out


def _proper_intersection(a:Point,b:Point,c:Point,d:Point) -> bool:
    # Only count proper interior transverse intersections. Coincident and
    # collinear overlaps are not automatically graph-connected.
    def cross(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    ab1,ab2=cross(a,b,c),cross(a,b,d)
    cd1,cd2=cross(c,d,a),cross(c,d,b)
    return (ab1*ab2 < -1e-10) and (cd1*cd2 < -1e-10)


def stats(g: Graph) -> dict[str, Any]:
    adj=adjacency(g)
    degrees=Counter({k:len(v) for k,v in adj.items()})
    coords={v.id:v.point for v in g.vertices}
    crossings=0
    for i,e in enumerate(g.edges):
        for f in g.edges[i+1:]:
            if set((e.source,e.target)) & set((f.source,f.target)):continue
            if _proper_intersection(coords[e.source],coords[e.target],coords[f.source],coords[f.target]):
                crossings += 1
    return {'vertex_count':len(g.vertices),'edge_count':len(g.edges),
            'component_count':len(components(g)),
            'open_endpoints':sum(d==1 for d in degrees.values()),
            'junctions':sum(d>=3 for d in degrees.values()),
            'crossings':crossings,
            'degree_histogram':{str(d):count for d,count in sorted(Counter(degrees.values()).items())}}


def spanning_forest(g: Graph, roots: list[str] | None = None) -> dict[str,dict]:
    """BFS parents; tree edges provide connected branch-by-branch unfolding."""
    adj=adjacency(g);rootlist=roots or [v.id for v in g.vertices]
    found={}
    for root in rootlist:
        if root in found:continue
        found[root]={'parent':None,'depth':0,'edge':None,'root':root}
        q=deque([root])
        while q:
            v=q.popleft()
            for neighbor,eid in adj[v]:
                if neighbor not in found:
                    found[neighbor]={'parent':v,'depth':found[v]['depth']+1,'edge':eid,'root':root}
                    q.append(neighbor)
    return found


def choose_anchor(g: Graph, preferred: Point | None = None) -> str:
    """Choose a central, high-degree root (optionally near a preferred point)."""
    positions={v.id:v.point for v in g.vertices};adj=adjacency(g)
    cx=sum(v.x for v in g.vertices)/len(g.vertices)
    cy=sum(v.y for v in g.vertices)/len(g.vertices)
    px,py=preferred or (cx,cy)
    # Favor high degree, graph-central vertices, and spatial proximity.
    best=None
    for v in g.vertices:
        q=deque([v.id]);dist={v.id:0}
        while q:
            node=q.popleft()
            for nbr,_ in adj[node]:
                if nbr not in dist:dist[nbr]=dist[node]+1;q.append(nbr)
        score=(len(g.vertices)-len(dist))*1000+sum(dist.values()) + .02*hypot(v.x-px,v.y-py) - .8*len(adj[v.id])
        if best is None or score < best[0]:best=(score,v.id)
    return best[1]
