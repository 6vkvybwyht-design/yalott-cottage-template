"""WSGI-файл для PythonAnywhere.

Скопіюйте його у файл, який PythonAnywhere показує на вкладці Web (WSGI configuration file).
У Bash-консолі PythonAnywhere, з папки проєкту:

    cp pythonanywhere_wsgi.py /var/www/$(whoami)_pythonanywhere_com_wsgi.py

Шлях до проєкту береться зі змінної оточення PROJECT_DIR, а якщо її немає — з рядка нижче.
Якщо склонували репозиторій в іншу папку — змініть лише цей рядок у СКОПІЙОВАНОМУ файлі.
Секрети (SECRET_KEY, ADMIN_PASSWORD, TELEGRAM_BOT_TOKEN…) — у файлі .env у папці проєкту, не тут.
"""
import os
import sys

PROJECT_DIR = os.environ.get("PROJECT_DIR") or os.path.expanduser("~/site")

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Під час імпорту сайт читає .env і config/site.yaml і сам створює базу в instance/, якщо її ще немає.
from app import app as application  # noqa: E402,F401
