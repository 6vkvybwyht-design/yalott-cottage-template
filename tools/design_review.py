#!/usr/bin/env python3
"""Перевірка якості дизайну: скріншоти 375 і 1440 px кожної теми + Lighthouse (мобільний) → звіт для порівняння.

    python tools/design_review.py                         усі теми дизайн-системи на config/site.yaml
    python tools/design_review.py --themes pine,lake      лише ці теми
    python tools/design_review.py --config config/examples/ramshill.yaml --as-is --out /tmp/ramshill
                                                          сайт як є (його власна тема) — «до/після»
    python tools/design_review.py --no-lighthouse         без Lighthouse (швидко)

Потрібні: node + playwright (як для tests/test_number_inputs.py) і, для Lighthouse, npx (пакет lighthouse
завантажиться сам) та Chromium. Сайт запускається локально на тимчасовій базі з демо-даними; демо-режим
(demo.enabled) для знімків вимикається — видно сайт так, як після оплати.

Результат у --out (типово docs/design/): README.md і report.html (порівняння тем), перший екран кожної теми
(ТЕМА-375.jpg, ТЕМА-1440.jpg), повні сторінки в full/ (у git не потрапляють), summary.json.
Поріг: продуктивність Lighthouse на мобільному ≥ 85 (--min-performance), медіана 3 прогонів (--lh-runs).
Відповіді стискаються gzip, як у Caddy на сервері (інакше Lighthouse міряє не те, що бачать гості).
"""

import argparse
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# --site-dir: код і фото іншої копії шаблону (напр. сайт клієнта «до» оновлення) — має стояти першим у sys.path
_site = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--site-dir=")), None)
SITE_DIR = os.path.abspath(_site) if _site else ROOT
sys.path.insert(0, ROOT)
if SITE_DIR != ROOT:
    sys.path.insert(0, SITE_DIR)
CHROME_CANDIDATES = ("/opt/pw-browsers/chromium-1243/chrome-linux64/chrome", "/opt/pw-browsers/chromium/chrome-linux64/chrome")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def prepare_config(src, theme, folder):
    """Копія конфігу з іншою темою і без демо-режиму. Фото лишаються там, де були (static/)."""
    raw = open(src, encoding="utf-8").read()
    if theme:
        raw = re.sub(r"(?m)^(  theme:)\s*\S+", rf"\1 {theme}", raw, count=1)
        raw = re.sub(r'(?m)^(  (?:primary|accent)_color:).*$', r'\1 ""', raw)
    raw = re.sub(r"(?ms)^(demo:\n(?:  .*\n|\s*\n)*?)  enabled: true", r"\1  enabled: false", raw, count=1)
    path = os.path.join(folder, os.path.basename(src))    # та сама назва файлу → те саме місце фото
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    return path


class Gzip:
    """Стиснення відповідей, як у Caddy на сервері (encode zstd gzip): без нього Lighthouse міряє не те,
    що бачать гості, — локальний сервер Flask нічого не стискає."""

    TYPES = ("text/", "application/javascript", "application/json", "image/svg+xml")

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        import gzip
        if "gzip" not in environ.get("HTTP_ACCEPT_ENCODING", ""):
            return self.app(environ, start_response)
        captured = {}

        def capture(status, headers, exc_info=None):
            captured["status"], captured["headers"] = status, headers
            return lambda data: None

        body = b"".join(self.app(environ, capture))
        headers = captured["headers"]
        ctype = next((v for k, v in headers if k.lower() == "content-type"), "")
        if len(body) > 512 and ctype.startswith(self.TYPES):
            body = gzip.compress(body, 6)
            headers = [(k, v) for k, v in headers if k.lower() not in ("content-length", "content-encoding")]
            headers += [("Content-Encoding", "gzip"), ("Content-Length", str(len(body))), ("Vary", "Accept-Encoding")]
        start_response(captured["status"], headers)
        return [body]


def serve(config, folder):
    os.environ.update({"YALOTT_NO_APP": "1", "SECRET_KEY": "review" * 11, "INSTANCE_PATH": folder,
                       "SESSION_COOKIE_SECURE": "0", "ADMIN_PASSWORD": "review-password", "NOTIFY_SYNC": "1"})
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DATABASE_PATH", "SITE_CONFIG"):
        os.environ[k] = ""
    import app as app_module
    from werkzeug.serving import make_server
    application = app_module.create_app({"SITE_CONFIG": config, "DATABASE": os.path.join(folder, "review.db"),
                                         "DEMO_DATA": True})
    port = free_port()
    server = make_server("127.0.0.1", port, Gzip(application), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}/", application.extensions["site"]


def shots(url, prefix):
    r = subprocess.run(["node", os.path.join(ROOT, "tools", "shots.js"), url, prefix], capture_output=True,
                       text=True, cwd=ROOT, timeout=300)
    if r.returncode != 0:
        raise SystemExit(f"Скріншоти не вдалися:\n{r.stderr[-2000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def lighthouse(url, folder, runs=3):
    """Медіана кількох прогонів (за продуктивністю): один прогін Lighthouse «стрибає» на ±10 балів."""
    results = []
    for _ in range(runs * 2):
        r = lighthouse_once(url, folder)
        if "error" not in r:
            results.append(r)
        if len(results) == runs:
            break
    if not results:
        return r
    results.sort(key=lambda x: x.get("performance", 0))
    best = dict(results[len(results) // 2])
    best["runs"] = [x.get("performance") for x in results]
    return best


def lighthouse_once(url, folder):
    chrome = next((c for c in CHROME_CANDIDATES if os.path.exists(c)), None)
    out = os.path.join(folder, "lh.json")
    cmd = ["npx", "--yes", "lighthouse", url, "--quiet", "--output=json", f"--output-path={out}",
           "--only-categories=performance,accessibility,best-practices,seo", "--form-factor=mobile",
           "--chrome-flags=--headless=new --no-sandbox --disable-dev-shm-usage"]
    env = dict(os.environ, CHROME_PATH=chrome) if chrome else None
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    if r.returncode != 0 or not os.path.exists(out):
        return {"error": (r.stderr or r.stdout)[-400:]}
    data = json.load(open(out, encoding="utf-8"))
    scores = {k: round((v.get("score") or 0) * 100) for k, v in data["categories"].items()}
    audits = data["audits"]
    for key in ("largest-contentful-paint", "cumulative-layout-shift", "total-blocking-time", "first-contentful-paint"):
        scores[key] = audits.get(key, {}).get("displayValue", "")
    return scores


def swatch(p):
    return "".join(f'<span class="sw" style="flex:{share};background:{p[c]}" title="{c}: {p[c]}"></span>'
                   for c, share in (("c60", 6), ("c30", 3), ("c10", 1)))


def write_report(out, rows, title, min_perf):
    import design
    md = [f"# {title}", "", "Згенеровано `python tools/design_review.py`. Перший екран на телефоні (375 px) і на "
          "широкому екрані (1440 px); повні сторінки — у `full/` (не в git) і в report.html.", "",
          "| Тема | 60 / 30 / 10 | Шрифти | Lighthouse (моб.): продуктивність · доступність · SEO | 375 px | 1440 px |",
          "|---|---|---|---|---|---|"]
    cards = []
    for r in rows:
        name, lh = r["name"], r.get("lighthouse") or {}
        p = design.PALETTES.get(r["theme"])
        colors = f'`{p["c60"]}` `{p["c30"]}` `{p["c10"]}`' if p else "стара тема"
        fonts = f'{design.FONTS[p["head"][0]][0]} + {design.FONTS[p["body"][0]][0]}' if p else ""
        perf = lh.get("performance")
        lh_txt = (f'{perf} · {lh.get("accessibility")} · {lh.get("seo")}' if perf is not None else "—")
        md.append(f'| **{r["label"]}** (`{r["theme"]}`) | {colors} | {fonts} | {lh_txt} | '
                  f'<img src="{name}-375.jpg" width="160"> | <img src="{name}-1440.jpg" width="420"> |')
        issues = []
        for w, info in r["shots"].items():
            if info["errors"]:
                issues.append(f"{w}px: помилки консолі — {html.escape('; '.join(info['errors'])[:300])}")
            if info["overflow"] > 0:
                issues.append(f"{w}px: горизонтальна прокрутка {info['overflow']} px")
        if perf is not None and perf < min_perf:
            issues.append(f"продуктивність {perf} < {min_perf}")
        lh_cells = "".join(f"<span><b>{lh.get(k, '—')}</b>{label}</span>" for k, label in
                           (("performance", "продуктивність"), ("accessibility", "доступність"),
                            ("best-practices", "практики"), ("seo", "SEO")))
        metrics = " · ".join(f"{k.split('-')[0].upper()} {lh[k]}" for k in
                             ("first-contentful-paint", "largest-contentful-paint", "total-blocking-time",
                              "cumulative-layout-shift") if lh.get(k))
        cards.append(f'''<section class="theme" id="{name}">
  <header><div><h2>{html.escape(r["label"])} <code>{r["theme"]}</code></h2><p>{html.escape(r.get("mood", ""))}</p>
  <p class="fonts">{html.escape(fonts)}</p></div>
  {f'<div class="bar">{swatch(p)}</div>' if p else ''}
  <div class="lh">{lh_cells}</div></header>
  <p class="metrics">{html.escape(metrics)}</p>
  {''.join(f'<p class="issue">⚠ {i}</p>' for i in issues) or '<p class="okline">✓ без помилок консолі (CSP) і горизонтальної прокрутки</p>'}
  <div class="pair"><figure class="m"><img src="{name}-375.jpg" alt="" loading="lazy"><figcaption>375 px — перший екран</figcaption></figure>
  <figure class="d"><img src="{name}-1440.jpg" alt="" loading="lazy"><figcaption>1440 px — перший екран</figcaption></figure></div>
  <details><summary>Повна сторінка</summary><div class="pair"><figure class="m"><img src="full/{name}-375-full.jpg" alt="" loading="lazy"></figure>
  <figure class="d"><img src="full/{name}-1440-full.jpg" alt="" loading="lazy"></figure></div></details>
</section>''')
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    page = f'''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:#f4f3f0;color:#1b1b1a}} main{{max-width:1400px;margin:0 auto;padding:24px 16px}}
.theme{{background:#fff;border-radius:14px;padding:20px;margin:0 0 24px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
header{{display:flex;flex-wrap:wrap;gap:16px 32px;align-items:center;justify-content:space-between}} h2{{margin:0;font-size:22px}}
header p{{margin:2px 0;color:#555}} .fonts{{font-size:13px}} .bar{{display:flex;width:220px;height:28px;border-radius:6px;overflow:hidden;box-shadow:inset 0 0 0 1px rgba(0,0,0,.1)}}
.lh{{display:flex;gap:14px}} .lh span{{display:grid;text-align:center;font-size:12px;color:#555}} .lh b{{font-size:22px;color:#1b1b1a}}
.metrics{{font-size:13px;color:#555}} .issue{{color:#a4371b}} .okline{{color:#2b6b3f}}
.pair{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,3.4fr);gap:16px;align-items:start}} figure{{margin:0}} img{{width:100%;border-radius:8px;border:1px solid #e5e3de}}
figcaption{{font-size:12px;color:#666;margin-top:4px}} details{{margin-top:12px}} summary{{cursor:pointer;color:#444}}
@media (max-width:700px){{.pair{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>{html.escape(title)}</h1>
<p>Порівняння тем. Lighthouse — мобільний профіль (поріг продуктивності {min_perf}). Перший екран і повна сторінка на 375 і 1440 px.</p>
{"".join(cards)}</main></body></html>'''
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def main(argv=None):
    import design
    import site_config
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(SITE_DIR, "config", "site.yaml"))
    ap.add_argument("--themes", help="через кому (типово — усі теми дизайн-системи)")
    ap.add_argument("--as-is", action="store_true", help="не міняти тему: знімати сайт як є")
    ap.add_argument("--name", help="назва для файлів при --as-is (типово — назва конфігу)")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "design"))
    ap.add_argument("--title", default="Теми дизайн-системи — порівняння")
    ap.add_argument("--no-lighthouse", action="store_true")
    ap.add_argument("--site-dir", help="інша копія шаблону (код і фото), напр. сайт клієнта; формат --site-dir=ТЕКА")
    ap.add_argument("--min-performance", type=int, default=85)
    ap.add_argument("--lh-runs", type=int, default=3, help="прогонів Lighthouse на тему (береться медіана)")
    args = ap.parse_args(argv)

    os.makedirs(os.path.join(args.out, "full"), exist_ok=True)
    config = os.path.abspath(args.config)
    themes = [None] if args.as_is else (args.themes.split(",") if args.themes else list(design.PALETTES))
    rows, failed = [], []
    for theme in themes:
        if theme and theme not in site_config.THEMES:
            raise SystemExit(f"Немає теми «{theme}»")
        folder = tempfile.mkdtemp(prefix="design-review-")
        try:
            cfg = prepare_config(config, theme, folder)
            server, url, site = serve(cfg, folder)
            real = site.brand["theme"]
            name = theme or args.name or os.path.splitext(os.path.basename(config))[0]
            p = design.PALETTES.get(real)
            label = p["label"] if p else f"{site.brand['name']} ({real})"
            print(f"• {label} ({real}): {url}", flush=True)
            row = {"name": name, "theme": real, "label": label, "mood": p["mood"] if p else "",
                   "shots": shots(url, os.path.join(args.out, name))}
            for w in ("375", "1440"):
                shutil.move(os.path.join(args.out, f"{name}-{w}-full.jpg"), os.path.join(args.out, "full", f"{name}-{w}-full.jpg"))
            if not args.no_lighthouse:
                row["lighthouse"] = lighthouse(url, folder, args.lh_runs)
                print(f"    Lighthouse: {row['lighthouse']}", flush=True)
                perf = row["lighthouse"].get("performance")
                if perf is None or perf < args.min_performance:
                    failed.append(f"{name}: продуктивність {perf}")
            for w, info in row["shots"].items():
                if info["errors"] or info["overflow"] > 0:
                    failed.append(f"{name} {w}px: {info}")
            rows.append(row)
            server.shutdown()
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    write_report(args.out, rows, args.title, args.min_performance)
    print(f"\nЗвіт: {os.path.relpath(os.path.join(args.out, 'report.html'), ROOT)}")
    if failed:
        print("Проблеми:\n  " + "\n  ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
