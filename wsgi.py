"""Точка входу для продакшн-сервера (gunicorn тощо). Для PythonAnywhere див. pythonanywhere_wsgi.py."""
from app import app  # noqa: F401
