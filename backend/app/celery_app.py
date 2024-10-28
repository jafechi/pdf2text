from celery import Celery
import os

broker_url = os.getenv('CELERY_BROKER_URL')
result_backend = os.getenv('CELERY_RESULT_BACKEND')


celery_app = Celery(
    'worker',
    broker=broker_url,
    backend=result_backend
)

