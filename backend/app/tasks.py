import json
import os

import redis

from .celery_app import celery_app
from .pdf_processor import PDFProcessor
from celery import Task

redis_client = redis.Redis.from_url(os.getenv('CELERY_RESULT_BACKEND'))


class ProcessPDFTask(Task):
    name = 'process_pdf_task'

    def on_success(self, retval, task_id, args, kwargs):
        print(f"Task {task_id} completed successfully with result: {retval}")
        redis_client.publish(
            'task_complete',
            json.dumps({
                'task_id': task_id,
                'status': 'completed',
                'result': retval
            })
        )
        super().on_success(retval, task_id, args, kwargs)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        print(f"Task {task_id} failed with exception: {exc}")
        redis_client.publish(
            'task_complete',
            json.dumps({
                'task_id': task_id,
                'status': 'failed',
                'error': str(exc)
            })
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(bind=True, base=ProcessPDFTask)
def process_pdf_task(self, pdf_path, txt_path):
    processor = PDFProcessor()
    result = processor.process_pdf(pdf_path, txt_path)
    if result:
        return txt_path
    else:
        return None
