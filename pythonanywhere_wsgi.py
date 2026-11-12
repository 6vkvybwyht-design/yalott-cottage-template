"""WSGI-файл для PythonAnywhere.

Скопіюйте його в файл, який PythonAnywhere показує на вкладці Web, командою в Bash-консолі:

    cp ~/forsethouse-demo/pythonanywhere_wsgi.py /var/www/$(whoami)_pythonanywhere_com_wsgi.py

Логін вписувати не треба: шлях до проєкту визначається автоматично.
Секрети (SECRET_KEY, ADMIN_PASSWORD, TELEGRAM_BOT_TOKEN тощо) зберігайте у файлі
~/forsethouse-demo/.env, а не тут — сайт прочитає їх сам.
"""
import os
import sys

# Папка, куди склоновано репозиторій. Якщо назвали її інакше — змініть тут.
PROJECT_DIR = os.path.expanduser("~/forsethouse-demo")

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Під час імпорту сайт читає .env і сам створює базу instance/forsethouse.db, якщо її ще немає.
from app import app as application  # noqa: E402,F401
