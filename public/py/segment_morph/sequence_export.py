"""Export time-sampled, discrete SVG animation at a user-selected frame rate.

The project retains 61 (or a configurable number of) planning samples per
transition; the export FPS is independent of that internal sampling density.
Per-leg linear resampling produces uniform temporal spacing (up to a final
fractional interval) and exact destination geometry at every hold boundary.

No samples are added during a still hold, so the output does not grow with
hold duration.
"""
from __future__ import annotations
from html import escape
from math import ceil, isfinite

DEFAULT_EXPORT_FPS = 60
MIN_EXPORT_FPS = 12
MAX_EXPORT_FPS = 120


def resolve_export_fps(project: dict, override=None) -> int:
    """Read v0.8 settings; v0.6/v0.7 projects default to 60 FPS."""
    requested = (override if override is not None else
                 (project.get('export') or {}).get('fps', DEFAULT_EXPORT_FPS))
    if isinstance(requested, bool) or not isinstance(requested, (int, float)):
        raise ValueError('Export FPS must be an integer from 12 through 120')
    if not isfinite(requested) or int(requested) != requested or not MIN_EXPORT_FPS <= requested <= MAX_EXPORT_FPS:
        raise ValueError('Export FPS must be an integer from 12 through 120')
    return int(requested)


def interpolate_frame(frames: list, t: float):
    """Interpolate the existing baked geometry at normalized t in [0, 1]."""
    if t <= 0:
        return frames[0]
    if t >= 1:
        return frames[-1]
    x = t * (len(frames) - 1)
    i = min(int(x), len(frames) - 2)
    w = x - i
    a, b = frames[i], frames[i+1]
    if len(a) != len(b):
        raise ValueError('Frame geometry cannot change edge count within one transition')
    return [[v * (1-w) + q*w for v,q in zip(a[k], b[k])] for k in range(len(a))]


def export_sequence_svg(project: dict, decimals=2, fps=None) -> str:
    if project.get('engine') != 'three-svg-sequence':
        raise ValueError('Expected a Segment Morph Studio sequence project')
    rate = resolve_export_fps(project, fps)
    legs = project.get('legs', [])
    if not legs or len(legs) != len(project['order']):
        raise ValueError('Missing baked sequence frames')
    duration = sum(float(leg['duration']) + float(leg.get('hold', 0)) for leg in legs)
    if duration <= 0 or not isfinite(duration):
        raise ValueError('Invalid total duration')

    paths, times, colors, widths = [], [], [], []
    clock = 0.0

    def add_frame(frame, sec, color, width):
        path = ''.join(
            f'M{a:.{decimals}f},{b:.{decimals}f}L{c:.{decimals}f},{d:.{decimals}f}'
            for a,b,c,d in frame
        )
        paths.append(path)
        times.append(sec / duration)
        colors.append(color)
        widths.append(width)

    for leg in legs:
        frames = leg['frames']
        if len(frames) < 2:
            raise ValueError('Not enough frame samples')
        move = float(leg['duration'])
        hold = float(leg.get('hold', 0))
        if not isfinite(move) or move <= 0 or not isfinite(hold) or hold < 0:
            raise ValueError('Invalid transition or hold duration')
        # At time k/fps, interpolation is evaluated against the saved planning
        # samples. A trailing partial interval is permitted for durations that
        # aren't integer multiples of 1/fps. The precise end is added at the
        # start of a hold (or by the next leg's first frame).
        for k in range(ceil(move * rate)):
            sec = k / rate
            u = min(1.0, sec / move)
            add_frame(interpolate_frame(frames, u), clock + sec,
                      leg['stroke_from'] if u < .5 else leg['stroke_to'],
                      leg['width_from'] if u < .5 else leg['width_to'])
        clock += move
        if hold > 0:
            add_frame(frames[-1], clock, leg['stroke_to'], leg['width_to'])
        clock += hold

    # keyTimes 1.0 closes the cycle; its geometry equals the first visual pose.
    paths.append(paths[0]); times.append(1.0)
    colors.append(colors[0]); widths.append(widths[0])
    path_values = ';'.join(paths)
    color_values = ';'.join(escape(c, quote=True) for c in colors)
    width_values = ';'.join(f'{float(w):.3f}' for w in widths)
    time_values = ';'.join(f'{t:.10f}' for t in times)
    v = project['viewport']
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {v["width"]} {v["height"]}" '
            f'width="{v["width"]}" height="{v["height"]}" fill="none" role="img" '
            f'aria-label="Looping morph across three uploaded SVG images" data-export-fps="{rate}">\n'
            f'<path d="{paths[0]}" stroke="{escape(colors[0],quote=True)}" stroke-width="{widths[0]:.3f}" '
            'stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">\n'
            f'<animate attributeName="d" dur="{duration:.4f}s" calcMode="discrete" '
            f'repeatCount="indefinite" keyTimes="{time_values}" values="{path_values}"/>\n'
            f'<animate attributeName="stroke" dur="{duration:.4f}s" calcMode="discrete" '
            f'repeatCount="indefinite" keyTimes="{time_values}" values="{color_values}"/>\n'
            f'<animate attributeName="stroke-width" dur="{duration:.4f}s" calcMode="discrete" '
            f'repeatCount="indefinite" keyTimes="{time_values}" values="{width_values}"/>\n'
            '</path></svg>\n')
