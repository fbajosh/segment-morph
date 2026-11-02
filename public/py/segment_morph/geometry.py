"""Safe SVG straight-segment extraction and normalization.

Scope: SVG line/polyline/polygon/path (M/L/H/V/Z), inherited stroke styles,
affine transforms and viewBoxes. Nonlinear SVG geometry is rejected rather than
quietly lost. Does not implement full SVG presentation/CSS cascading.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import cos, sin, radians, hypot
import hashlib
import re
from typing import Any
from xml.etree import ElementTree as ET

_TOKEN = re.compile(r"[MmLlHhVvZzCcSsQqTtAa]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")
_BAD = re.compile(r"<\s*(?:!DOCTYPE|!ENTITY|script|foreignObject|image|use)\b", re.I)
_ATTR_UNSAFE = re.compile(r"(?:url\s*\(|javascript:|data:)", re.I)
_TRANS = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")
_SUPPORTED_TAGS = {"svg", "g", "line", "polyline", "polygon", "path", "title", "desc", "defs", "metadata"}
_STROKE_DEFAULT = {"stroke": "#111111", "stroke_width": 2.0, "stroke_linecap": "butt", "stroke_opacity": 1.0}
_MAX_BYTES = 2_000_000
_MAX_SEGMENTS = 2000


class SVGError(ValueError):
    pass


@dataclass(frozen=True)
class Segment:
    id: str
    a: tuple[float, float]
    b: tuple[float, float]
    source_element: str
    stroke: str
    stroke_width: float
    stroke_linecap: str
    stroke_opacity: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Drawing:
    segments: tuple[Segment, ...]
    viewbox: tuple[float, float, float, float]
    svg_hash: str
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"segments": [s.as_dict() for s in self.segments],
                "viewbox": list(self.viewbox), "svg_hash": self.svg_hash,
                "warnings": list(self.warnings), "count": len(self.segments)}


# SVG affine matrix [a,b,c,d,e,f], mapping x'=ax+cy+e; y'=bx+dy+f.
IDENTITY = (1., 0., 0., 1., 0., 0.)


def compose(m: tuple, n: tuple) -> tuple:
    a,b,c,d,e,f = m
    A,B,C,D,E,F = n
    return (a*A+c*B, b*A+d*B, a*C+c*D, b*C+d*D, a*E+c*F+e, b*E+d*F+f)


def apply(m: tuple, p: tuple) -> tuple[float,float]:
    x,y = p
    return (m[0]*x+m[2]*y+m[4], m[1]*x+m[3]*y+m[5])


def transform_matrix(expression: str | None) -> tuple:
    if not expression:
        return IDENTITY
    current = IDENTITY
    pos = 0
    for mat in _TRANS.finditer(expression):
        if expression[pos:mat.start()].strip(" ,\t\n"):
            raise SVGError(f"Invalid SVG transform syntax: {expression!r}")
        name = mat.group(1)
        args = [float(v) for v in _NUM.findall(mat.group(2))]
        if name == "matrix" and len(args) == 6:
            n = tuple(args)
        elif name == "translate" and len(args) in (1, 2):
            n = (1., 0., 0., 1., args[0], args[1] if len(args) == 2 else 0.)
        elif name == "scale" and len(args) in (1, 2):
            n = (args[0], 0., 0., args[1] if len(args) == 2 else args[0], 0., 0.)
        elif name == "rotate" and len(args) in (1, 3):
            angle = radians(args[0]); c=cos(angle); s=sin(angle)
            n = (c,s,-s,c,0.,0.)
            if len(args) == 3:
                cx,cy = args[1:]
                n = compose(compose((1.,0.,0.,1.,cx,cy), n), (1.,0.,0.,1.,-cx,-cy))
        elif name == "skewX" and len(args) == 1:
            from math import tan
            n = (1.,0.,tan(radians(args[0])),1.,0.,0.)
        elif name == "skewY" and len(args) == 1:
            from math import tan
            n = (1.,tan(radians(args[0])),0.,1.,0.,0.)
        else:
            raise SVGError(f"Unsupported SVG transform: {name}({mat.group(2)})")
        current = compose(current,n)
        pos = mat.end()
    if expression[pos:].strip(" ,\t\n"):
        raise SVGError(f"Invalid SVG transform syntax: {expression!r}")
    return current


def _number(s: str, default: float | None = None) -> float:
    if s is None:
        if default is None:
            raise SVGError("Missing coordinate attribute")
        return default
    if not re.fullmatch(r"\s*[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?\s*", str(s)):
        raise SVGError(f"Expected unitless number, found {s!r}")
    return float(s)


def parse_path(d: str) -> list[tuple[tuple[float,float],tuple[float,float]]]:
    # Reject any unparsed character, including comma-separated malformed commands.
    tokens = _TOKEN.findall(d)
    leftovers = _TOKEN.sub("", d)
    if leftovers.strip(" ,\t\n\r"):
        raise SVGError(f"Unsupported or invalid path syntax: {leftovers.strip()[:50]}")
    out=[]; i=0; command=None; current=(0.,0.); sub_start=(0.,0.)
    def add(a,b):
        if hypot(b[0]-a[0], b[1]-a[1]) > 1e-10:
            out.append((a,b))
    def number(index):
        if index >= len(tokens) or re.fullmatch(r"[A-Za-z]", tokens[index]):
            raise SVGError("Path command has missing numeric arguments")
        return float(tokens[index])
    while i < len(tokens):
        if tokens[i].isalpha():
            command=tokens[i]; i+=1
        if command is None:
            raise SVGError("Path must begin with a move command")
        if command in "CcSsQqTtAa":
            raise SVGError(f"Unsupported curved path command {command}: use straight-line geometry")
        if command in "Zz":
            add(current,sub_start); current=sub_start; command=None
            continue
        cmd=command.upper()
        if cmd not in "MLHV":
            raise SVGError(f"Unsupported path command {command}")
        rel=command.islower()
        if cmd in "ML":
            x=number(i); y=number(i+1); i+=2
            dest=(x+current[0], y+current[1]) if rel else (x,y)
            if cmd=="M":
                current=dest; sub_start=dest
                command = "l" if rel else "L"
            else:
                add(current,dest); current=dest
        else:
            val=number(i); i+=1
            if cmd=="H": dest=(current[0]+val if rel else val,current[1])
            else: dest=(current[0],current[1]+val if rel else val)
            add(current,dest); current=dest
    return out


def _points(raw: str) -> list[tuple[float,float]]:
    nums = _NUM.findall(raw)
    if _NUM.sub("",raw).strip(" ,\t\n\r") or len(nums)%2:
        raise SVGError("Invalid polyline/polygon point list")
    return [(float(nums[i]),float(nums[i+1])) for i in range(0,len(nums),2)]


def _stroke(el: Any, inherited: dict[str,Any]) -> dict[str,Any]:
    out=dict(inherited)
    inline={}
    for pair in el.get("style", "").split(";"):
        if ":" in pair:
            key,value=pair.split(":",1);inline[key.strip()]=value.strip()
    for xml_key,key in (("stroke","stroke"),("stroke-width","stroke_width"),("stroke-linecap","stroke_linecap"),("stroke-opacity","stroke_opacity")):
        v = inline.get(xml_key,el.get(xml_key))
        if v is not None:
            out[key]=_number(v) if key in ("stroke_width","stroke_opacity") else v
    return out


def parse_svg(svg: str) -> Drawing:
    if len(svg.encode("utf-8")) > _MAX_BYTES:
        raise SVGError(f"SVG exceeds {_MAX_BYTES:,} byte limit")
    if _BAD.search(svg):
        raise SVGError("SVG contains a prohibited element or entity declaration")
    try:
        root=ET.fromstring(svg)
    except ET.ParseError as e:
        raise SVGError(f"Invalid SVG XML: {e}") from e
    if root.tag.rsplit("}",1)[-1] != "svg":
        raise SVGError("Input must have an <svg> root")
    for el in root.iter():
        for k,v in el.attrib.items():
            if k.lower().startswith("on") or "href" in k.lower() or _ATTR_UNSAFE.search(v):
                raise SVGError("SVG contains an unsafe event handler, reference, or URL")
    box = root.get("viewBox")
    if box:
        vals = [float(x) for x in _NUM.findall(box)]
        if len(vals)!=4 or vals[2]<=0 or vals[3]<=0:
            raise SVGError("Invalid SVG viewBox")
        vb=tuple(vals)
    else:
        vb=(0.,0.,_number(root.get("width")),_number(root.get("height")))
        if vb[2]<=0 or vb[3]<=0: raise SVGError("SVG width/height must be positive")
    segments=[]; warnings=[]
    def visit(el, cumulative, inherited):
        name=el.tag.rsplit("}",1)[-1]
        if name not in _SUPPORTED_TAGS:
            raise SVGError(f"Unsupported SVG element <{name}>; remove or convert it to paths")
        if name in ("title","desc","metadata", "defs"):
            return
        if el.get("display")=="none" or el.get("visibility")=="hidden":
            return
        matrix=compose(cumulative, transform_matrix(el.get("transform")))
        st=_stroke(el,inherited)
        coords=[]
        if name=="path":
            coords=parse_path(el.get("d", ""))
        elif name=="line":
            coords=[((_number(el.get("x1"),0),_number(el.get("y1"),0)),
                     (_number(el.get("x2"),0),_number(el.get("y2"),0)))]
        elif name in ("polyline","polygon"):
            points=_points(el.get("points",""))
            coords=list(zip(points,points[1:]))
            if name=="polygon" and len(points)>2:coords.append((points[-1],points[0]))
        if coords and st["stroke"] == "none":
            warnings.append(f"Ignored invisible/no-stroke element {el.get('id',name)}")
            coords=[]
        if coords:
            for a,b in coords:
                A=apply(matrix,a); B=apply(matrix,b)
                if hypot(A[0]-B[0],A[1]-B[1])<1e-8:
                    warnings.append(f"Skipped zero-length segment on {el.get('id',name)}")
                    continue
                if len(segments)>=_MAX_SEGMENTS:raise SVGError("SVG has too many segments")
                scale=max(hypot(matrix[0],matrix[1]),hypot(matrix[2],matrix[3]))
                segments.append(Segment(f"seg-{len(segments)+1:03d}",A,B,
                    el.get("id", f"{name}-{len(segments)+1}"),st["stroke"],
                    st["stroke_width"]*scale,st["stroke_linecap"],st["stroke_opacity"]))
        for child in el:
            visit(child,matrix,st)
    visit(root,IDENTITY,_STROKE_DEFAULT)
    if not segments:
        raise SVGError("No straight visible line segments were found")
    return Drawing(tuple(segments),vb,hashlib.sha256(svg.encode()).hexdigest(),tuple(warnings))


def normalize(drawing: Drawing, width: float=900, height: float=640, padding: float=30) -> Drawing:
    """Place each SVG's own viewBox inside the same viewport, preserving aspect ratio."""
    if min(width,height)<=0 or padding<0 or 2*padding>=min(width,height):
        raise ValueError("Invalid viewport or padding")
    x,y,w,h=drawing.viewbox
    scale=min((width-2*padding)/w,(height-2*padding)/h)
    dx=(width-w*scale)/2-x*scale
    dy=(height-h*scale)/2-y*scale
    segments=[]
    for s in drawing.segments:
        segments.append(Segment(s.id,(s.a[0]*scale+dx,s.a[1]*scale+dy),
            (s.b[0]*scale+dx,s.b[1]*scale+dy),s.source_element,s.stroke,
            s.stroke_width*scale,s.stroke_linecap,s.stroke_opacity))
    return Drawing(tuple(segments),(0.,0.,width,height),drawing.svg_hash,drawing.warnings)
