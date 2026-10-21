def make_icon(kind, colour, size=20, stroke=1.9):
    if not PIL_OK:
        return None
    key = (kind, colour, size, stroke)
    hit = _ICON_CACHE.get(key)
    if hit is not None:
        return hit
    scale = 4
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        _draw_icon(draw, kind, S, _rgb(colour),
                   max(1, int(round(stroke * scale))))
    except Exception:
        pass
    img = img.resize((size, size), RESAMPLE_LANCZOS)
    icon = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = icon
    return icon
