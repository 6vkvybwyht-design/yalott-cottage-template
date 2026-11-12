"""Сповіщення власнику в Telegram про нові бронювання.

Кожне сповіщення спершу записується в таблицю notifications (черга), потім надсилається.
Токен і chat id беруться з файлу .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID), а не з коду.
Якщо їх не задано — сповіщення позначається як «skipped», сайт працює далі.
"""

import html
import json
import logging
import os
import threading
import urllib.error
import urllib.request

import pricing as P
import site_content
from database import connect

log = logging.getLogger(__name__)


def _settings():
    return (os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def is_configured():
    token, chat_id = _settings()
    return bool(token and chat_id)


def _date(iso):
    return ".".join(reversed(iso.split("-")))


OBJECT_EMOJI = {1: "🌿", 2: "🏡", 3: "🔺"}


def booking_message(b):
    q, e = b["price"], html.escape
    lines = [
        f"🌲 <b>Нове бронювання · {e(site_content.SITE['name'])}</b>",
        "",
        f"{OBJECT_EMOJI.get(b['objectId'], '🏠')} <b>{e(b['objectName'])}</b>",
        f"👤 {e(b['name'])}",
        f"📞 {e(b['phone'])}",
        f"📅 {_date(b['checkIn'])} → {_date(b['checkOut'])} ({b['nights']} діб)",
        f"👥 Гостей: {b['guests']}",
    ]
    if b.get("extras"):
        lines.append("♨️ " + ", ".join(b["extras"]))
    lines.append("")
    for l in q.get("lines", []):
        label = f" ({l['label']})" if l.get("label") else ""
        lines.append(f"• {l['count']} × {P.format_uah(l['price'])}{label} = {P.format_uah(l['sum'])}")
    for x in q.get("extras", []):
        lines.append(f"• {x['name']} = {P.format_uah(x['price'])}")
    if b.get("onRequest"):
        missing = ", ".join(_date(d) for d in q.get("missingNights", []))
        lines += ["💰 <b>Ціна за домовленістю</b>", f"Доби без ціни: {missing}",
                  "Узгодьте вартість і передоплату з гостем."]
    else:
        lines += [f"💰 <b>Разом: {P.format_uah(b['total'])}</b>",
                  f"💳 Передоплата {q.get('prepaymentPercent', P.CONFIG['prepaymentPercent'])}%: "
                  f"<b>{P.format_uah(b['prepayment'])}</b>"]
    if b["comment"]:
        lines += ["", f"💬 {e(b['comment'])}"]
    lines += ["", f"Код: {b['id']}",
              "Підтвердьте в адмінці та надішліть гостю реквізити для передоплати."]
    return "\n".join(lines)


def queue(db, booking):
    message = booking_message(booking)
    cur = db.execute("INSERT INTO notifications (booking_code, message) VALUES (?, ?)", (booking["id"], message))
    return cur.lastrowid


def send_message(text):
    """Надсилає повідомлення одразу. Повертає (ok, помилка)."""
    token, chat_id = _settings()
    if not token or not chat_id:
        return False, "Не задано TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID у файлі .env"
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=8).read()
        return True, ""
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("description", "")
        except Exception:
            detail = ""
        return False, f"Telegram {exc.code}: {detail or exc.reason}"
    except Exception as exc:  # мережа, таймаут тощо
        return False, f"Немає зв'язку з Telegram: {exc}"


def send_async(db_path, notification_id):
    """На PythonAnywhere потоки у вебзастосунках не працюють, тому там (або з NOTIFY_SYNC=1)
    надсилаємо одразу — це додає до секунди до відповіді. Локально — у фоновому потоці."""
    if os.environ.get("PYTHONANYWHERE_DOMAIN") or os.environ.get("NOTIFY_SYNC") == "1":
        _send(db_path, notification_id)
    else:
        threading.Thread(target=_send, args=(db_path, notification_id), daemon=True).start()


def _send(db_path, notification_id):
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        if not is_configured():
            log.info("Telegram не налаштовано, сповіщення:\n%s", row["message"])
            conn.execute("UPDATE notifications SET status = 'skipped', error = ? WHERE id = ?",
                         ("Telegram не налаштовано", notification_id))
            return
        ok, error = send_message(row["message"])
        if ok:
            conn.execute("UPDATE notifications SET status = 'sent', sent_at = datetime('now') WHERE id = ?",
                         (notification_id,))
        else:
            log.warning("Не вдалося надіслати сповіщення в Telegram: %s", error)
            conn.execute("UPDATE notifications SET status = 'failed', error = ? WHERE id = ?",
                         (error[:500], notification_id))
    finally:
        conn.close()
