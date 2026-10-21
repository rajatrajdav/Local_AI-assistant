# ==========================================================================
# ICON DRAWING — small vector icons rendered with PIL (no external assets)
# ==========================================================================
_ICON_CACHE = {}


def _draw_icon(draw, kind, S, colour, stroke):
    """Draw a kind-of icon onto a PIL ImageDraw canvas of size SxS."""
    cx = cy = S / 2.0
    def line(pts, width=None):
        w = width if width is not None else stroke
        draw.line(pts, fill=colour, width=int(w))
    def box(x0, y0, x1, y1, radius=0, fill=False):
        if radius:
            r = radius
            draw.rounded_rectangle([x0, y0, x1, y1], radius=r,
                                   fill=colour if fill else None,
                                   outline=None if fill else colour,
                                   width=int(stroke))
        else:
            if fill:
                draw.rectangle([x0, y0, x1, y1], fill=colour)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=colour,
                               width=int(stroke))
    def circ(x, y, r, fill=False):
        if fill:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)
        else:
            draw.ellipse([x - r, y - r, x + r, y + r], outline=colour,
                         width=int(stroke))
    def arc(x, y, r, start, end):
        draw.arc([x - r, y - r, x + r, y + r], start=start, end=end,
                 fill=colour, width=int(stroke))
    def pts(*pairs):
        return [(cx + dx * S / 100.0, cy + dy * S / 100.0) for dx, dy in pairs]

    if kind == "core":
        circ(cx, cy, S * 0.36); circ(cx, cy, S * 0.23); circ(cx, cy, S * 0.11, fill=True)
        for i in range(8):
            ang = math.radians(i * 45)
            line([(cx + S * 0.27 * math.cos(ang), cy + S * 0.27 * math.sin(ang)),
                  (cx + S * 0.34 * math.cos(ang), cy + S * 0.34 * math.sin(ang))])
    elif kind == "mic":
        box(S * 0.36, S * 0.10, S * 0.64, S * 0.56, radius=S * 0.14)
        arc(cx, S * 0.44, S * 0.27, 6, 174)
        line([(cx, S * 0.71), (cx, S * 0.86)])
        line([(S * 0.35, S * 0.86), (S * 0.65, S * 0.86)])
    elif kind == "stop":
        box(S * 0.27, S * 0.27, S * 0.73, S * 0.73, radius=S * 0.07, fill=True)
    elif kind == "send":
        draw.polygon(pts((10, 50), (90, 12), (58, 90), (46, 58)), fill=colour)
    elif kind == "speaker":
        draw.polygon(pts((16, 38), (34, 38), (56, 18), (56, 82), (34, 62), (16, 62)),
                     fill=colour)
        arc(cx, S * 0.50, S * 0.20, 300, 60)
    elif kind == "mute":
        draw.polygon(pts((14, 38), (32, 38), (54, 18), (54, 82), (32, 62), (14, 62)),
                     fill=colour)
        line([(S * 0.68, S * 0.38), (S * 0.90, S * 0.62)])
        line([(S * 0.90, S * 0.38), (S * 0.68, S * 0.62)])
    elif kind == "broadcast":
        circ(cx, S * 0.66, S * 0.07, fill=True)
        arc(cx, S * 0.66, S * 0.24, 195, 345)
        arc(cx, S * 0.66, S * 0.40, 205, 335)
    elif kind == "export":
        line([(S * 0.50, S * 0.74), (S * 0.50, S * 0.16)])
        line([(S * 0.33, S * 0.33), (S * 0.50, S * 0.16), (S * 0.67, S * 0.33)])
        line([(S * 0.20, S * 0.58), (S * 0.20, S * 0.86),
              (S * 0.80, S * 0.86), (S * 0.80, S * 0.58)])
    elif kind == "refresh":
        arc(cx, cy, S * 0.33, 34, 326)
        draw.polygon(pts((82, 30), (66, 30), (78, 46)), fill=colour)
    elif kind == "trash":
        line([(S * 0.20, S * 0.28), (S * 0.80, S * 0.28)])
        line([(S * 0.39, S * 0.28), (S * 0.39, S * 0.14),
              (S * 0.61, S * 0.14), (S * 0.61, S * 0.28)])
        line([(S * 0.29, S * 0.28), (S * 0.36, S * 0.88),
              (S * 0.64, S * 0.88), (S * 0.71, S * 0.28)])
        line([(S * 0.43, S * 0.40), (S * 0.46, S * 0.76)])
        line([(S * 0.57, S * 0.40), (S * 0.54, S * 0.76)])
    elif kind == "chip":
        box(S * 0.26, S * 0.26, S * 0.74, S * 0.74, radius=S * 0.06)
        box(S * 0.41, S * 0.41, S * 0.59, S * 0.59, radius=S * 0.03)
        for c in (0.34, 0.50, 0.66):
            line([(S * c, S * 0.12), (S * c, S * 0.26)])
            line([(S * c, S * 0.74), (S * c, S * 0.88)])
            line([(S * 0.12, S * c), (S * 0.26, S * c)])
            line([(S * 0.74, S * c), (S * 0.88, S * c)])
    elif kind == "eye":
        draw.polygon(pts((10, 50), (32, 30), (68, 30), (90, 50),
                         (68, 70), (32, 70)), outline=colour)
        circ(cx, cy, S * 0.09)
    elif kind == "terminal":
        box(S * 0.08, S * 0.16, S * 0.92, S * 0.84, radius=S * 0.08)
        line([(S * 0.24, S * 0.34), (S * 0.40, S * 0.50), (S * 0.24, S * 0.66)])
        line([(S * 0.50, S * 0.66), (S * 0.74, S * 0.66)])
    elif kind == "close":
        line([(S * 0.26, S * 0.26), (S * 0.74, S * 0.74)])
        line([(S * 0.74, S * 0.26), (S * 0.26, S * 0.74)])
    elif kind == "power":
        arc(cx, cy, S * 0.30, 300, 60)
        line([(cx, S * 0.14), (cx, S * 0.52)])
    elif kind == "folder":
        box(S * 0.08, S * 0.26, S * 0.92, S * 0.86, radius=S * 0.09)
        line([(S * 0.08, S * 0.26), (S * 0.08, S * 0.18),
              (S * 0.36, S * 0.18), (S * 0.46, S * 0.26)])
    elif kind == "gauge":
        arc(cx, S * 0.62, S * 0.33, 160, 380)
        line([(cx, S * 0.62), (S * 0.74, S * 0.36)])
        circ(cx, S * 0.62, S * 0.03, fill=True)
    elif kind == "info":
        circ(cx, cy, S * 0.37); circ(cx, S * 0.32, S * 0.036, fill=True)
        line([(cx, S * 0.44), (cx, S * 0.70)])
    elif kind == "pulse":
        line([(S * 0.08, S * 0.58), (S * 0.28, S * 0.58),
              (S * 0.38, S * 0.24), (S * 0.50, S * 0.80),
              (S * 0.62, S * 0.38), (S * 0.72, S * 0.58),
              (S * 0.92, S * 0.58)])
    elif kind == "unknown":
        circ(cx, cy, S * 0.30)
