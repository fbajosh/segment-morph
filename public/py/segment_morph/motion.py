"""Pure frame evaluator. No canvas state or dependence on playback history."""
from __future__ import annotations
from math import atan2,cos,sin,pi,hypot
from dataclasses import dataclass, asdict
from .geometry import Segment

@dataclass(frozen=True)
class Window:
    start: float = 0.
    end: float = 1.
    easing: str = "smooth"  # linear, smooth, cubic-in, cubic-out

    def as_dict(self):return asdict(self)

DEFAULT_MOTION={"duration":2.5,
    "translation":Window().as_dict(),"rotation":Window().as_dict(),
    "length":Window().as_dict()}


def ease(x:float,method:str)->float:
    x=max(0.,min(1.,x))
    if method=="linear":return x
    if method=="smooth":return x*x*(3-2*x)
    if method=="cubic-in":return x**3
    if method=="cubic-out":return 1-(1-x)**3
    raise ValueError("Unknown easing: "+method)


def progress(t:float,window:dict)->float:
    a=float(window.get("start",0)); b=float(window.get("end",1))
    if not 0<=a<b<=1:raise ValueError("Timing window requires 0 <= start < end <= 1")
    return ease((t-a)/(b-a),window.get("easing","smooth"))


def _lerp(a,b,t):return a+(b-a)*t


def _hex(s):
    names={"black":"#000000","white":"#ffffff","purple":"#800080"}
    s=names.get(s.lower(),s)
    if s.startswith("#"):
        value=s[1:]
        if len(value)==3:value="".join(c*2 for c in value)
        if len(value)==6:
            try:return tuple(int(value[i:i+2],16) for i in (0,2,4))
            except ValueError:pass
    return None


def _color(a,b,t):
    A=_hex(a);B=_hex(b)
    if A is None or B is None:return a if t<1 else b
    return "#"+"".join(f"{round(_lerp(v,w,t)):02x}" for v,w in zip(A,B))


def evaluate_frame(source:tuple[Segment,...]|list[Segment],
                   target:tuple[Segment,...]|list[Segment],
                   mapping:list[dict],t:float,motion:dict|None=None)->list[dict]:
    """Produce endpoint-exact lines for t in [0,1]."""
    if not 0<=t<=1:raise ValueError("Frame progress must be between 0 and 1")
    motion={**DEFAULT_MOTION,**(motion or {})}
    pc=progress(t,motion["translation"])
    pa=progress(t,motion["rotation"])
    pl=progress(t,motion["length"])
    bysource={s.id:s for s in source};bytarget={s.id:s for s in target}
    result=[]
    for m in mapping:
        s=bysource[m["source_id"]];dest=bytarget[m["target_id"]]
        t0,t1=(dest.b,dest.a) if m["reverse_target"] else (dest.a,dest.b)
        if t==0: a,b=s.a,s.b
        elif t==1: a,b=t0,t1
        else:
            ca=((s.a[0]+s.b[0])/2,(s.a[1]+s.b[1])/2)
            cb=((t0[0]+t1[0])/2,(t0[1]+t1[1])/2)
            center=(_lerp(ca[0],cb[0],pc),_lerp(ca[1],cb[1],pc))
            sa=atan2(s.b[1]-s.a[1],s.b[0]-s.a[0]);
            ea=atan2(t1[1]-t0[1],t1[0]-t0[0]);
            angle=sa+(((ea-sa+pi)%(2*pi))-pi)*pa
            length=_lerp(hypot(s.b[0]-s.a[0],s.b[1]-s.a[1]),
                         hypot(t1[0]-t0[0],t1[1]-t0[1]),pl)
            vx=cos(angle)*length/2;vy=sin(angle)*length/2
            a=(center[0]-vx,center[1]-vy);b=(center[0]+vx,center[1]+vy)
        result.append({"id":m["instance"],"source_id":s.id,"target_id":dest.id,
                       "a":list(a),"b":list(b),
                       "stroke":_color(s.stroke,dest.stroke,t),
                       "stroke_width":_lerp(s.stroke_width,dest.stroke_width,pc),
                       "stroke_linecap":s.stroke_linecap if t<1 else dest.stroke_linecap,
                       "stroke_opacity":_lerp(s.stroke_opacity,dest.stroke_opacity,pc)})
    return result
