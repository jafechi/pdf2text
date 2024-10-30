import json
import os

import redis
from .celery_app import celery_app
from .models import TaskCompleteMessage, TASK_COMPLETE_CHANNEL
from .pdf_to_text_converter import PDFToTextConverter
from celery import Task
from .config import s3_client, BUCKET_NAME

redis_client = redis.Redis.from_url(os.getenv('CELERY_RESULT_BACKEND'))


class ProcessPDFTask(Task):
    name = 'process_pdf_task'

    def on_success(self, retval, task_id, args, kwargs):
        print(f"Task {task_id} completed successfully with result: {retval}")
        message = TaskCompleteMessage(
            task_id=task_id,
            status='completed',
            result=retval
        )
        redis_client.publish(TASK_COMPLETE_CHANNEL, message.model_dump_json())
        super().on_success(retval, task_id, args, kwargs)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        print(f"Task {task_id} failed with exception: {exc}")
        message = TaskCompleteMessage(
            task_id=task_id,
            status='failed',
            error=str(exc)
        )
        redis_client.publish(TASK_COMPLETE_CHANNEL, message.model_dump_json())
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(bind=True, base=ProcessPDFTask)
def process_pdf_task(self, s3_pdf_key, s3_text_key):
    TEMPORARY_FOLDER = '/tmp'
    local_pdf_path = f"{TEMPORARY_FOLDER}/{os.path.basename(s3_pdf_key)}"
    local_text_path = f"{TEMPORARY_FOLDER}/{os.path.basename(s3_text_key)}"

    try:
        s3_client.download_file(BUCKET_NAME, s3_pdf_key, local_pdf_path)

        processor = PDFToTextConverter()

        result = processor.convert_pdf(local_pdf_path, local_text_path)

        if result:
            s3_client.upload_file(local_text_path, BUCKET_NAME, s3_text_key)
            return s3_text_key

        return None

    finally:
        if os.path.exists(local_pdf_path):
            os.remove(local_pdf_path)
        if os.path.exists(local_text_path):
            os.remove(local_text_path)
