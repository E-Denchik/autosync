# Не точка входа для запуска приложения (см. native_app.py) — нужен только
# как FLASK_APP для CLI-команд Flask-Migrate при разработке:
#   FLASK_APP=wsgi.py flask db migrate -m "..."
#   FLASK_APP=wsgi.py flask db upgrade
from app import create_app

app = create_app()
