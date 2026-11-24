"""Дизайн-система тем (правило 60/30/10). Без сторонніх пакетів.

Кожна тема дизайн-системи — це РІВНО ТРИ кольори:
  • c60 — основний, ~60 % площі: тло сторінки;
  • c30 — другорядний, ~30 %: картки, блоки, форма бронювання;
  • c10 — акцент, ~10 %: ЛИШЕ те, що веде до бронювання — кнопка «Забронювати», ціни, вибрані дати.
Усе інше (текст, приглушений текст, лінії, поля форми, темний тон для підвалу й затемнення фото) не
вигадується вручну, а ОБЧИСЛЮЄТЬСЯ з цих трьох кольорів так, щоб контраст відповідав WCAG AA
(текст ≥ 4.5:1, межі полів і кнопок ≥ 3:1). Тест tests/test_design.py перевіряє кожну палітру.

CSS палітр і шрифтів (static/css/palettes.css) генерується звідси:
    python manage.py design-css
Тест перевіряє, що файл актуальний. Стилі компонентів, шкала відступів і анімації — static/css/design.css.
Нова тема = новий запис у PALETTES (3 кольори + пара шрифтів із кирилицею в static/fonts/).
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "static", "fonts")

# Діапазони Unicode наборів шрифтів (як у Google Fonts / Fontsource): браузер качає лише потрібний файл.
UNICODE_RANGES = {
    "cyrillic": "U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    "latin": ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, "
              "U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD"),
}
SUBSETS = ("cyrillic", "latin")

# Шрифти: тека в static/fonts/, назва для CSS, запасні системні шрифти.
FONTS = {
    "cormorant-garamond": ("Cormorant Garamond", "Georgia, 'Times New Roman', serif"),
    "playfair-display": ("Playfair Display", "Georgia, 'Times New Roman', serif"),
    "lora": ("Lora", "Georgia, 'Times New Roman', serif"),
    "unbounded": ("Unbounded", "'Arial Black', system-ui, sans-serif"),
    "prata": ("Prata", "Georgia, 'Times New Roman', serif"),
    "literata": ("Literata", "Georgia, 'Times New Roman', serif"),
    "forum": ("Forum", "Georgia, 'Times New Roman', serif"),
    "yeseva-one": ("Yeseva One", "Georgia, 'Times New Roman', serif"),
    "manrope": ("Manrope", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
    "inter": ("Inter", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
    "golos-text": ("Golos Text", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
    "onest": ("Onest", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
    "montserrat": ("Montserrat", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
    "commissioner": ("Commissioner", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
    "pt-sans": ("PT Sans", "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
}

# Форма: радіуси карток і кнопок — частина характеру теми.
SHAPES = {
    "soft": {"radius": "18px", "radius-sm": "12px", "radius-btn": "999px"},
    "round": {"radius": "28px", "radius-sm": "18px", "radius-btn": "999px"},
    "sharp": {"radius": "2px", "radius-sm": "2px", "radius-btn": "2px"},
    "calm": {"radius": "10px", "radius-sm": "8px", "radius-btn": "8px"},
}

# ── Палітри ──
# c60 / c30 / c10 — три кольори теми; head / body — шрифти (тека в static/fonts/) і накреслення;
# shape — форма; head_tracking — міжлітерний інтервал заголовків; label/mood — для анкети й README.
PALETTES = {
    "pine": {
        "label": "Смерека", "mood": "глибокий зелений, беж і мідь — ліс, дерево, вогонь у каміні",
        "c60": "#1d3127", "c30": "#efe5d3", "c10": "#d08a56",
        "head": ("cormorant-garamond", 600), "body": ("manrope", (400, 600)),
        "shape": "soft", "head_tracking": "-0.01em",
    },
    "graphite": {
        "label": "Графіт", "mood": "графіт, молочний і золото — стримано, по-міському дорого",
        "c60": "#1f2226", "c30": "#f3eee5", "c10": "#d4ab55",
        "head": ("playfair-display", 500), "body": ("inter", (400, 600)),
        "shape": "sharp", "head_tracking": "-0.01em",
    },
    "terracotta": {
        "label": "Теракота", "mood": "білий, камінь і теракота — світло, глина, південне сонце",
        "c60": "#fbf9f5", "c30": "#e9e3d9", "c10": "#a9482a",
        "head": ("lora", 600), "body": ("golos-text", (400, 600)),
        "shape": "soft", "head_tracking": "-0.015em",
    },
    "night": {
        "label": "Ніч", "mood": "нічне небо, пісок і лайм — сучасно, сміливо, для глемпінгу",
        "c60": "#0f141b", "c30": "#e6d8bf", "c10": "#c6e15b",
        "head": ("unbounded", 500), "body": ("onest", (400, 600)),
        "shape": "round", "head_tracking": "-0.03em",
    },
    "linen": {
        "label": "Льон", "mood": "льон, сланцево-зелений і бронза — тепла класика садиби",
        "c60": "#f5f0e7", "c30": "#2e3c36", "c10": "#965c18",
        "head": ("prata", 400), "body": ("montserrat", (400, 600)),
        "shape": "calm", "head_tracking": "0",
    },
    "lake": {
        "label": "Озеро", "mood": "туман над водою, глибока бірюза й корал — свіжо й спокійно",
        "c60": "#eef2f0", "c30": "#1f3b47", "c10": "#b04830",
        "head": ("literata", 600), "body": ("manrope", (400, 600)),
        "shape": "soft", "head_tracking": "-0.02em",
    },
    "birch": {
        "label": "Береза", "mood": "білий, шавлія й лісовий зелений — чисто, скандинавськи",
        "c60": "#fafaf7", "c30": "#dfe4dc", "c10": "#2c5e4b",
        "head": ("forum", 400), "body": ("commissioner", (400, 600)),
        "shape": "calm", "head_tracking": "0.01em",
    },
    "ember": {
        "label": "Жар", "mood": "вугілля, темне дерево й жар — баня, чан, вечір біля вогню",
        "c60": "#171310", "c30": "#2a221d", "c10": "#e8783f",
        "head": ("yeseva-one", 400), "body": ("pt-sans", (400, 700)),
        "shape": "soft", "head_tracking": "0",
    },
}

# ── Колір ──

INK_DARK = "#14120f"
INK_LIGHT = "#fbf8f3"
WHITE = "#ffffff"


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in rgb)


def mix(a, b, t):
    """Колір a, змішаний з b на частку t (0 — a, 1 — b), як color-mix(in srgb)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def luminance(hex_color):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_dark(hex_color):
    return luminance(hex_color) < 0.18


def ink(bg, tint):
    """Колір тексту для тла bg: темний або світлий (що контрастніший), злегка у відтінку теми."""
    dark, light = mix(INK_DARK, tint, 0.12), mix(INK_LIGHT, tint, 0.04)
    return dark if contrast(dark, bg) >= contrast(light, bg) else light


def soften(fg, bg, target):
    """Найм'якший відтінок fg у бік bg, який ще має контраст ≥ target з bg."""
    lo, hi = 0.0, 0.95
    if contrast(fg, bg) < target:
        return fg
    for _ in range(30):
        mid = (lo + hi) / 2
        if contrast(mix(fg, bg, mid), bg) >= target:
            lo = mid
        else:
            hi = mid
    return mix(fg, bg, lo)


def readable(color, bg, target, toward):
    """color, якщо він читається на bg (≥ target); інакше — найближчий до нього відтінок у бік toward."""
    if contrast(color, bg) >= target:
        return color
    for i in range(1, 101):
        c = mix(color, toward, i / 100)
        if contrast(c, bg) >= target:
            return c
    return toward


def blend(fg, bg, alpha):
    """fg з непрозорістю alpha поверх bg."""
    return mix(bg, fg, alpha)


def scrim_alpha(deep, target=4.5):
    """Найменша непрозорість затемнення deep, при якій білий текст читається навіть на білій ділянці фото."""
    for i in range(0, 101):
        a = i / 100
        if contrast(WHITE, blend(deep, WHITE, a)) >= target:
            return a
    return 1.0


def derive(p):
    """Усі кольори теми з трьох: ключі — назви CSS-змінних (без --)."""
    c60, c30, c10 = p["c60"], p["c30"], p["c10"]
    on60, on30 = ink(c60, c30), ink(c30, c60)
    on10 = ink(c10, c60)
    # темний тон: тло підвалу, затемнення фото, великий блок будинку
    if luminance(c60) < 0.06:
        deep = mix(c60, "#000000", 0.25)
    elif luminance(c30) < 0.06:
        deep = mix(c30, "#000000", 0.2)
    else:
        deep = mix(c10, "#0b0a09", 0.8)
    on_deep = mix(INK_LIGHT, c30, 0.04) if contrast(INK_LIGHT, deep) >= contrast(INK_DARK, deep) else INK_DARK
    field30 = mix(c30, WHITE, 0.6) if not is_dark(c30) else mix(c30, "#000000", 0.22)
    alpha = scrim_alpha(deep)
    return {
        "c60": c60, "c30": c30, "c10": c10,
        # текст на основному тлі (60)
        "on-60": on60, "muted-60": soften(on60, c60, 6.0), "faint-60": soften(on60, c60, 4.6),
        "line-60": mix(on60, c60, 0.86), "tint-60": mix(c60, on60, 0.035),
        # текст у картках і блоках (30)
        "on-30": on30, "muted-30": soften(on30, c30, 6.0), "faint-30": soften(on30, c30, 4.6),
        "line-30": mix(on30, c30, 0.84), "tint-30": mix(c30, on30, 0.06),
        "field-30": field30, "field-line-30": soften(on30, field30, 3.0),
        "scheme-30": "dark" if is_dark(c30) else "light",   # вигляд рідних полів і прапорців у картках
        # акцент: кнопка (c10 + on-10), ціни й важливе як текст — читабельний відтінок акценту на 60 і на 30
        "on-10": on10, "c10-hover": mix(c10, "#000000" if not is_dark(on10) else WHITE, 0.12),
        "accent-60": readable(c10, c60, 4.6, on60), "accent-30": readable(c10, c30, 4.6, on30),
        "accent-soft-30": mix(c30, c10, 0.2),
        # темний тон (підвал, затемнення банера) і текст на ньому
        "deep": deep, "on-deep": on_deep, "muted-deep": soften(on_deep, deep, 6.0),
        "accent-deep": readable(c10, deep, 4.6, on_deep),
        "scrim": f"{alpha:.2f}",
        # затемнення банера: у зоні тексту — scrim (білий текст читається навіть на білому небі), далі слабшає
        "scrim-color": _rgba(deep, alpha), "scrim-mid": _rgba(deep, alpha * 0.5), "scrim-clear": _rgba(deep, 0),
        # ціна поверх фото банера — найсвітліший можливий фон під текстом = біле небо під затемненням
        "accent-hero": readable(c10, blend(deep, WHITE, alpha), 4.5, WHITE),
    }


def _rgba(hex_color, alpha):
    r, g, b = _rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def checks(name):
    """Пари (опис, передній план, тло, мінімум) для перевірки контрасту палітри (WCAG AA)."""
    d = derive(PALETTES[name])
    pairs = [
        ("текст на тлі (60)", d["on-60"], d["c60"], 4.5),
        ("другорядний текст на тлі", d["muted-60"], d["c60"], 4.5),
        ("приглушений текст на тлі", d["faint-60"], d["c60"], 4.5),
        ("текст у картці (30)", d["on-30"], d["c30"], 4.5),
        ("другорядний текст у картці", d["muted-30"], d["c30"], 4.5),
        ("приглушений текст у картці", d["faint-30"], d["c30"], 4.5),
        ("текст у полі форми", d["on-30"], d["field-30"], 4.5),
        ("межа поля форми", d["field-line-30"], d["field-30"], 3.0),
        ("текст кнопки «Забронювати» (10)", d["on-10"], d["c10"], 4.5),
        ("текст кнопки при наведенні", d["on-10"], d["c10-hover"], 4.5),
        ("ціна на тлі", d["accent-60"], d["c60"], 4.5),
        ("ціна в картці", d["accent-30"], d["c30"], 4.5),
        ("вибрана дата в календарі", d["on-10"], d["c10"], 4.5),
        ("текст на темному тоні (підвал)", d["on-deep"], d["deep"], 4.5),
        ("приглушений текст у підвалі", d["muted-deep"], d["deep"], 4.5),
        ("ціна на темному тоні", d["accent-deep"], d["deep"], 4.5),
        ("кнопка помітна на тлі (межа)", d["c10"], d["c60"], 3.0),
        ("білий текст на банері (найсвітліше фото)", WHITE, blend(d["deep"], WHITE, float(d["scrim"])), 4.5),
        ("ціна на банері (найсвітліше фото)", d["accent-hero"], blend(d["deep"], WHITE, float(d["scrim"])), 4.5),
    ]
    return pairs


# ── CSS ──

def font_files(folder, weight):
    return {s: f"fonts/{folder}/{folder}-{s}-{weight}-normal.woff2" for s in SUBSETS}


def used_fonts():
    """{(тека, накреслення)} усіх тем."""
    out = set()
    for p in PALETTES.values():
        out.add((p["head"][0], p["head"][1]))
        for w in p["body"][1]:
            out.add((p["body"][0], w))
    return sorted(out)


def font_stack(folder):
    family, fallback = FONTS[folder]
    return f"'{family}', {fallback}"


def preload(name):
    """Шрифти, які варто попередньо завантажити (кирилиця заголовка й основного тексту) — для _base.html."""
    p = PALETTES[name]
    return [font_files(p["head"][0], p["head"][1])["cyrillic"],
            font_files(p["body"][0], p["body"][1][0])["cyrillic"]]


def css():
    out = ["/* Згенеровано з design.py — НЕ РЕДАГУЙТЕ вручну. Оновити: python manage.py design-css */", ""]
    out.append("/* ── Шрифти (локально, лише кирилиця й латиниця; браузер качає тільки потрібне) ── */")
    for folder, weight in used_fonts():
        family = FONTS[folder][0]
        for subset, path in font_files(folder, weight).items():
            out.append(f"@font-face {{ font-family: '{family}'; font-style: normal; font-weight: {weight}; "
                       f"font-display: swap; src: url('../{path}') format('woff2'); "
                       f"unicode-range: {UNICODE_RANGES[subset]}; }}")
    out.append("")
    for name, p in PALETTES.items():
        d = derive(p)
        shape = SHAPES[p["shape"]]
        head, body = p["head"], p["body"]
        out.append(f"/* {name} — «{p['label']}»: {p['mood']} */")
        lines = [f"--{k}: {v};" for k, v in d.items()]
        lines += [f"--{k}: {v};" for k, v in shape.items()]
        lines += [f"--font-head: {font_stack(head[0])};", f"--head-weight: {head[1]};",
                  f"--head-spacing: {p['head_tracking']};",
                  f"--font: {font_stack(body[0])};", f"--body-strong: {body[1][-1]};",
                  f"color-scheme: {'dark' if is_dark(p['c60']) else 'light'};"]
        out.append(f'html[data-theme="{name}"] {{')
        out += [f"  {line}" for line in lines]
        out.append("}")
        out.append("")
    return "\n".join(out)


CSS_PATH = os.path.join(BASE_DIR, "static", "css", "palettes.css")


def write_css(path=CSS_PATH):
    with open(path, "w", encoding="utf-8") as f:
        f.write(css())
    return path
