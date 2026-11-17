"""ОБОВ'ЯЗКОВЕ ПРАВИЛО (CLAUDE.md): числові поля й гроші.

  • Будь-яке <input type="number"> — step="1" або step="any". Ніколи step="50", "100", "500".
  • Грошове поле (ціна, доплата, сума) — рівно step="1" min="0" і атрибут data-money.

Чому: браузер відраховує крок від min. З min="1" step="50" валідні лише 1, 51, 101 … 4451, 4501 —
і форма відмовляється зберігати ціну 4500. Так уже двічі ламалось у клієнтів.

Перевірка у три шари:
  1. вихідники — усі шаблони (templates/**/*.html) і скрипти (static/**/*.js), включно з HTML,
     який JS будує рядками; заборонено і step через JS (el.step = …, setAttribute('step', …));
  2. готові сторінки всіх конфігів (config/site.yaml і config/examples/*.yaml) після рендеру Jinja;
  3. живий DOM адмінки в браузері: кожне грошове поле має прийняти 4500 і 20000
     (пропускається, якщо немає node + playwright).
"""

import glob
import json
import os
import re
import shutil
import subprocess
import threading

import pytest

from conftest import CONFIGS, ROOT

ALLOWED_STEPS = {"1", "any"}
MONEY_STEP, MONEY_MIN = "1", "0"
# Схоже на гроші за назвою поля чи підписом — тоді обов'язковий data-money.
MONEY_HINT = re.compile(r"price|cost|amount|fee|sum\b|ціна|ціни|грн|сума|доплат|вартість", re.I)


# ---------- розбір розмітки ----------

def strip_comments(text, filename):
    """Прибирає коментарі, щоб пояснення на кшталт «не ставте step="50"» не спрацьовували як порушення."""
    text = re.sub(r"\{#.*?#\}", " ", text, flags=re.S)           # Jinja
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)          # HTML
    if filename.endswith(".js"):
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        text = re.sub(r"(?m)^\s*//.*$", " ", text)               # лише рядки-коментарі: «https://» у рядках лишається
    return text


def input_tags(text):
    """Усі теги <input …> разом з атрибутами. Працює і для HTML, і для JS-рядків, що будують HTML."""
    return [m.group(0) for m in re.finditer(r"<input\b[^>]*>", text, flags=re.I)]


def attr(tag, name):
    """Буквальне значення атрибута або None. Значення, склеєне з JS-змінної ("' + min + '"), — не буквальне."""
    m = re.search(rf"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", tag, flags=re.I)
    if not m:
        return None
    value = next(v for v in m.groups() if v is not None)
    return "<динамічне>" if "+" in value or "{{" in value or "${" in value else value


def has_flag(tag, name):
    return re.search(rf"(?<![\w-]){name}(?![\w-])", tag) is not None


def is_number(tag):
    return (attr(tag, "type") or "").lower() == "number"


def check_markup(text, where):
    """Порушення в одному файлі / сторінці: список рядків «де: що не так»."""
    problems = []
    for tag in input_tags(text):
        if not is_number(tag):
            continue
        short = re.sub(r"\s+", " ", tag)[:140]
        step, minimum = attr(tag, "step"), attr(tag, "min")
        money = has_flag(tag, "data-money")
        looks_like_money = MONEY_HINT.search(f"{attr(tag, 'name') or ''} {attr(tag, 'aria-label') or ''}")
        if step is None:
            problems.append(f"{where}: числове поле без step — додайте step=\"1\": {short}")
        elif step not in ALLOWED_STEPS:
            problems.append(f"{where}: step=\"{step}\" — дозволено лише \"1\" або \"any\": {short}")
        if looks_like_money and not money:
            problems.append(f"{where}: схоже на грошове поле, але без data-money "
                            f"(гроші — лише step=\"1\" min=\"0\" data-money): {short}")
        if money:
            if step != MONEY_STEP:
                problems.append(f"{where}: грошове поле з step=\"{step}\" — має бути step=\"1\": {short}")
            if minimum != MONEY_MIN:
                problems.append(f"{where}: грошове поле з min=\"{minimum}\" — має бути min=\"0\" "
                                f"(з min=\"1\" браузер рахує крок від 1 і не приймає 4500): {short}")
    return problems


def check_script(text, where):
    """step, виставлений із JS: el.step = '50', setAttribute('step', 50), $(…).attr('step', …), {step: 50}."""
    problems = []
    patterns = (r"\.step\s*=\s*([^;,\n)]+)",
                r"setAttribute\(\s*['\"]step['\"]\s*,\s*([^)]+)\)",
                r"\.attr\(\s*['\"]step['\"]\s*,\s*([^)]+)\)",
                r"[{,]\s*['\"]?step['\"]?\s*:\s*([^,}\n]+)")
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            value = m.group(1).strip().strip("'\"")
            if value not in ALLOWED_STEPS:
                problems.append(f"{where}: step задається зі скрипта значенням {m.group(1).strip()} — "
                                f"дозволено лише '1' або 'any'")
    return problems


def source_files():
    files = glob.glob(os.path.join(ROOT, "templates", "**", "*.html"), recursive=True)
    files += glob.glob(os.path.join(ROOT, "static", "**", "*.html"), recursive=True)
    files += glob.glob(os.path.join(ROOT, "static", "**", "*.js"), recursive=True)
    files += glob.glob(os.path.join(ROOT, "*.py"))               # на випадок HTML, зібраного в Python
    return sorted(f for f in files if "/media/" not in f)


# ---------- 1. вихідники ----------

def test_all_sources_follow_number_rule():
    problems, numbers = [], 0
    for path in source_files():
        rel = os.path.relpath(path, ROOT)
        text = strip_comments(open(path, encoding="utf-8").read(), path)
        numbers += sum(is_number(t) for t in input_tags(text))
        problems += check_markup(text, rel)
        if path.endswith((".js", ".html")):
            problems += check_script(text, rel)
    assert numbers >= 4, "не знайдено числових полів — перевірка зламалась, а не код"
    assert not problems, "Порушено правило числових полів (CLAUDE.md):\n" + "\n".join(problems)


def test_money_fields_are_marked():
    """Усі грошові поля адмінки справді позначені data-money (інакше правило min="0" нічого б не перевіряло)."""
    js = strip_comments(open(os.path.join(ROOT, "static", "js", "admin.js"), encoding="utf-8").read(), ".js")
    money = [t for t in input_tags(js) if has_flag(t, "data-money")]
    assert money and all(attr(t, "min") == "0" and attr(t, "step") == "1" for t in money)
    # усі місця, де адмінка будує грошові поля, ідуть через moneyInput/money
    for name in ("price", "extraGuestPrice", "tp", "gp"):
        assert re.search(rf"money(?:Input|Field)\('{name}'", js), f"поле {name} будується не через money()"


# ---------- 2. готові сторінки ----------

def test_rendered_pages_follow_number_rule(make_site):
    problems = []
    for name in CONFIGS:
        s = make_site(name)
        s.login()
        urls = ["/", "/admin/", "/admin/login", "/немає-такої"] + [f"/{o['slug']}" for o in s.cfg.objects]
        for url in urls:
            html = s.client.get(url).get_data(as_text=True)
            problems += check_markup(html, f"{name}{url}")
    assert not problems, "\n".join(problems)


# ---------- перевірка самої перевірки ----------

@pytest.mark.parametrize("bad, reason", [
    ('<input name="price" type="number" min="1" step="50" data-money>', 'step="50"'),
    ('<input name="price" type="number" min="1" step="1" data-money>', 'min="1"'),
    ('<input name="price" type="number" step="1" data-money>', 'min="None"'),
    ('<input name="tp" type="number" min="0" step="any" data-money>', 'step="any"'),
    ('<input type="number" name="guests" min="1">', "без step"),
    ('<input type="number" name="nights" step="2">', 'step="2"'),
    ('<input name="price" type="number" min="0" step="1">', "без data-money"),
    ('<input aria-label="Ціна, грн" type=number min=0 step=1>', "без data-money"),
    ("'<input name=\"' + n + '\" type=\"number\" min=\"0\" step=\"' + s + '\" data-money>'", "динамічне"),
])
def test_checker_catches_violations(bad, reason):
    problems = check_markup(bad, "зразок")
    assert problems and any(reason in p for p in problems), problems


@pytest.mark.parametrize("bad", ["el.step = 50;", "input.setAttribute('step', '100')", "$(i).attr('step', 50)",
                                 "{type: 'number', step: 50}"])
def test_checker_catches_step_from_script(bad):
    assert check_script(bad, "зразок")


@pytest.mark.parametrize("good", [
    '<input name="price" type="number" inputmode="numeric" min="0" step="1" data-money value="4500">',
    '<input name="guests" type="number" min="1" max="6" step="1">',
    '<input name="lat" type="number" step="any">',
    '<input name="price" type="text">',
    "'<input name=\"' + name + '\" type=\"number\" min=\"0\" step=\"1\" data-money value=\"' + v + '\"' + a + '>'",
])
def test_checker_accepts_valid(good):
    assert check_markup(good, "зразок") == []


def test_comments_do_not_count():
    js = '// з min="1" step="50" браузер не приймає 4500\n/* step="50" */\nvar a = "https://example.com";'
    assert check_markup(strip_comments(js, "a.js"), "a.js") == [] and "https://" in strip_comments(js, "a.js")


# ---------- 3. живий DOM адмінки в браузері ----------

BROWSER_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[2];
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = []; p.on('pageerror', e => errors.push(e.message));
  await p.goto(base + '/admin/login');
  await p.fill('input[name=username]', 'admin'); await p.fill('input[name=password]', 'demo2026');
  await p.click('button.btn'); await p.waitForSelector('#priceObjs form', { state: 'attached' });
  await p.click('[data-tab-btn=prices]'); await p.waitForSelector('#priceObjs form');
  for (const sel of ['[data-tier-add]', '[data-gtier-add]']) for (const btn of await p.$$(sel)) await btn.click();
  const fields = await p.$$eval('input[type=number]', els => els.map(e => {
    const out = { name: e.name, step: e.getAttribute('step'), min: e.getAttribute('min'),
      money: e.hasAttribute('data-money'), label: e.getAttribute('aria-label') ||
        (e.closest('label') ? e.closest('label').textContent.trim() : '') , accepts: {} };
    if (out.money) for (const v of ['4500', '20000', '12345', '0']) {
      const old = e.value, was = e.disabled; e.disabled = false; e.value = v;
      out.accepts[v] = e.checkValidity(); e.value = old; e.disabled = was;
    }
    return out;
  }));
  console.log(JSON.stringify({ fields, errors }));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def _node_with_playwright():
    node = shutil.which("node")
    if not node:
        return None
    ok = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, cwd=ROOT).returncode == 0
    return node if ok else None


def test_admin_dom_in_browser(make_site, tmp_path):
    node = _node_with_playwright()
    if not node:
        pytest.skip("немає node + playwright — перевірка в браузері пропущена (вихідники перевірено вище)")
    from werkzeug.serving import make_server

    s = make_site("blackhouse")                     # тут є і доплата, і ціни послуги за кількістю гостей
    server = make_server("127.0.0.1", 0, s.app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        script = tmp_path / "dom.js"
        script.write_text(BROWSER_SCRIPT, encoding="utf-8")
        run = subprocess.run([node, str(script), f"http://127.0.0.1:{server.server_port}"],
                             capture_output=True, text=True, timeout=90, cwd=ROOT)
    finally:
        server.shutdown()
    assert run.returncode == 0, run.stderr[-2000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["errors"] == []
    fields = result["fields"]
    money = [f for f in fields if f["money"]]
    # ціна й доплата обох котеджів, ціна чану, рядки цін чану, знижка за тривалість, сезони
    assert len(money) >= 8 and {"price", "extraGuestPrice", "tp", "gp"} <= {f["name"] for f in money}
    problems = []
    for f in fields:
        where = f"{f['name']} ({f['label'][:40]})"
        if f["step"] not in ALLOWED_STEPS:
            problems.append(f"{where}: step={f['step']!r}")
        if MONEY_HINT.search(f"{f['name']} {f['label']}") and not f["money"]:
            problems.append(f"{where}: грошове поле без data-money")
        if f["money"]:
            if (f["step"], f["min"]) != (MONEY_STEP, MONEY_MIN):
                problems.append(f"{where}: step={f['step']!r} min={f['min']!r}, а треба step='1' min='0'")
            rejected = [v for v, ok in f["accepts"].items() if not ok]
            if rejected:
                problems.append(f"{where}: браузер не приймає {', '.join(rejected)}")
    assert not problems, "\n".join(problems)
