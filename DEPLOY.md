# Деплой

Спершу — PythonAnywhere (основний варіант), нижче — що змінити для VPS.

У коді немає захардкоджених шляхів: усе, що залежить від сервера, задається змінними оточення
(файл `.env` у папці проєкту). Повний список — у `.env.example`.

Перед деплоєм на своєму комп'ютері:

```bash
python manage.py check
```

і закомітьте `config/site.yaml` та `static/media/`. Файл `.env` у git не потрапляє — на сервері його
створюєте окремо.

---

## PythonAnywhere

Нижче `USER` — ваш логін на PythonAnywhere, `REPO` — адреса репозиторію клієнта.
Проєкт кладемо в папку `~/site`.

### 1. Код

Вкладка **Consoles → Bash**:

```bash
git clone REPO ~/site
```

Для приватного репозиторію використайте адресу з токеном доступу або deploy-ключ.

```bash
cd ~/site
```

```bash
python3.12 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

### 2. Секрети

```bash
cp .env.example .env
```

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Відкрийте `.env` (вкладка **Files** або `nano .env`) і заповніть:

| Змінна | Значення |
|---|---|
| `SECRET_KEY` | рядок з команди вище |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | логін і пароль адмінки (пароль від 8 символів) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | бот від @BotFather і chat id власника |
| `DEMO_DATA` | `1` — поки показуєте клієнту, `0` — для робочого сайту |
| `SESSION_COOKIE_SECURE` | `1` |

### 3. База й перевірка

```bash
.venv/bin/python manage.py seed
```

```bash
.venv/bin/python manage.py check
```

### 4. Вебзастосунок

Вкладка **Web → Add a new web app → Manual configuration → Python 3.12**. Далі на тій самій вкладці:

- **Source code:** `/home/USER/site`
- **Working directory:** `/home/USER/site`
- **Virtualenv:** `/home/USER/site/.venv`
- **Static files:** URL `/static/` → Directory `/home/USER/site/static`
- **Force HTTPS:** увімкнути

WSGI-файл — скопіюйте готовий (у Bash-консолі):

```bash
cp ~/site/pythonanywhere_wsgi.py /var/www/$(whoami)_pythonanywhere_com_wsgi.py
```

Якщо проєкт лежить не в `~/site`, змініть у скопійованому файлі один рядок `PROJECT_DIR`.

Натисніть **Reload**. Сайт: `https://USER.pythonanywhere.com`, адмінка: `/admin`.

### 5. Перевірка після запуску

1. Відкрийте головну й сторінку кожного об'єкта.
2. Увійдіть в адмінку, натисніть **«Надіслати тестове сповіщення»** — у Telegram має прийти повідомлення.
3. Зробіть тестову заявку з сайту — сповіщення прийде власнику; скасуйте її в адмінці.
4. Перед запуском для гостей: `DEMO_DATA=0` у `.env` і

```bash
.venv/bin/python manage.py seed --clear-demo
```

### Оновлення сайту

```bash
cd ~/site && git pull
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python manage.py seed
```

Потім **Web → Reload**. `seed` тут лише доливає нове з конфігу (новий об'єкт чи сезон) —
ціни, змінені власником в адмінці, не чіпає.

### Резервна копія

Усі бронювання — в одному файлі `~/site/instance/site.db`. Завантажте його через вкладку **Files**
або скопіюйте:

```bash
cp ~/site/instance/site.db ~/backup-$(date +%F).db
```

### Власний домен

Платний тариф PythonAnywhere: **Web → Add a new web app** з вашим доменом, далі ті самі налаштування,
а в DNS — CNAME-запис, який покаже PythonAnywhere. WSGI-файл матиме іншу назву
(`/var/www/www_example_com_wsgi.py`) — скопіюйте `pythonanywhere_wsgi.py` у нього.

### Особливості безкоштовного тарифу

- Вихідні з'єднання дозволені лише до «білого списку» сайтів; `api.telegram.org` у ньому є.
- Фонові потоки у вебзастосунках не працюють, тому сповіщення надсилається одразу в запиті
  (сайт сам це визначає за змінною `PYTHONANYWHERE_DOMAIN`).
- Раз на кілька місяців треба натиснути **Run until 3 months from today** на вкладці Web.

---

## VPS (Ubuntu / Debian)

Код той самий. Змінюються лише: хто запускає застосунок (gunicorn замість WSGI-файлу PythonAnywhere),
хто віддає статику й HTTPS (nginx), і де лежать дані — це задається в `.env`.

### 1. Код і залежності

```bash
sudo adduser --system --group --home /srv/cottage cottage
```

```bash
sudo -u cottage git clone REPO /srv/cottage/site
```

```bash
cd /srv/cottage/site && sudo -u cottage python3 -m venv .venv
```

```bash
sudo -u cottage .venv/bin/pip install -r requirements.txt gunicorn
```

### 2. `.env`

Те саме, що для PythonAnywhere, плюс за бажанням — шляхи. Усі вони необов'язкові:
без них дані лежать у `instance/` всередині проєкту.

```ini
SECRET_KEY=...
ADMIN_PASSWORD=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DEMO_DATA=0
SESSION_COOKIE_SECURE=1

# дані поза папкою з кодом — зручно для бекапів і оновлень
INSTANCE_PATH=/var/lib/cottage
# або лише файл бази:
# DATABASE_PATH=/var/lib/cottage/site.db
# інший конфіг:
# SITE_CONFIG=config/site.yaml
# сповіщення одразу в запиті (за замовчуванням на VPS — у фоновому потоці):
# NOTIFY_SYNC=1
```

Якщо задали `INSTANCE_PATH`:

```bash
sudo install -d -o cottage -g cottage /var/lib/cottage
```

```bash
sudo -u cottage .venv/bin/python manage.py seed
```

```bash
sudo -u cottage .venv/bin/python manage.py check
```

### 3. gunicorn як сервіс

`/etc/systemd/system/cottage.service`:

```ini
[Unit]
Description=Cottage site
After=network.target

[Service]
User=cottage
Group=cottage
WorkingDirectory=/srv/cottage/site
ExecStart=/srv/cottage/site/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Змінні з `.env` застосунок читає сам — дублювати їх у сервісі не потрібно.
Кілька воркерів безпечні: захист від подвійного бронювання працює на рівні бази (транзакція SQLite),
а не пам'яті процесу.

```bash
sudo systemctl enable --now cottage
```

### 4. nginx і HTTPS

`/etc/nginx/sites-available/cottage`:

```nginx
server {
    server_name example.com www.example.com;

    location /static/ {
        alias /srv/cottage/site/static/;
        expires 30d;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/cottage /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx
```

```bash
sudo certbot --nginx -d example.com -d www.example.com
```

### 5. Оновлення й бекап

```bash
cd /srv/cottage/site && sudo -u cottage git pull && sudo -u cottage .venv/bin/python manage.py seed && sudo systemctl restart cottage
```

Бекап — один файл бази (`/var/lib/cottage/site.db` або `instance/site.db`). Щодня через cron:

```bash
sqlite3 /var/lib/cottage/site.db ".backup '/var/backups/cottage-$(date +\%F).db'"
```

### Кілька сайтів на одному VPS

Окрема папка, окремий `.env`, окремий сервіс і порт на кожного клієнта.
Бази не перетинаються: у кожного проєкту свій `INSTANCE_PATH`.

---

## Якщо щось не так

| Симптом | Причина й рішення |
|---|---|
| Сайт не стартує, у журналі «Конфіг … містить помилки» | `python manage.py validate` покаже, що виправити |
| «База … створена старою версією сайту» | у `DATABASE_PATH` лежить база від старого сайту — вкажіть інший файл |
| В адмінку пускає `admin / demo2026` | не задано `ADMIN_PASSWORD` у `.env`; задайте й перезапустіть |
| Не приходять сповіщення | адмінка → «Надіслати тестове сповіщення» покаже точну помилку Telegram |
| Змінили ціну в конфігу, а на сайті стара | так і задумано: ціни після першого запуску живуть у базі. Змініть в адмінці або `seed --reset` |
| Замість фото заглушки | немає файлів у `static/media/objects/<id>/` — запустіть `python manage.py photos` і закомітьте результат |
| Після оновлення старі стилі | перезапустіть застосунок (Reload) — версія стилів у посиланнях оновиться |
