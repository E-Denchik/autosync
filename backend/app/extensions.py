from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

# celery — не устанавливается вовсе в native-сборке (requirements-native.txt),
# чтобы не тащить Celery/kombu/billiard в PyInstaller-бинарник ради того,
# что в этом режиме всё равно не используется (см. config.py: USE_CELERY,
# services/job_queue.py). Импорт делаем опциональным, а не обязательным.
try:
    from celery import Celery

    celery = Celery(__name__)
except ImportError:
    celery = None
