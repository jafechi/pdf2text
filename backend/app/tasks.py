import json
import os

import boto3
import redis

from .celery_app import celery_app
from .pdf_processor import PDFProcessor
from celery import Task
from .config import s3_client, BUCKET_NAME

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
def process_pdf_task(self, s3_pdf_key, s3_text_key):
    local_pdf_path = f"/tmp/{os.path.basename(s3_pdf_key)}"
    local_text_path = f"/tmp/{os.path.basename(s3_text_key)}"

    try:
        # Download PDF from S3
        s3_client.download_file(BUCKET_NAME, s3_pdf_key, local_pdf_path)

        # Process PDF
        processor = PDFProcessor()
        result = processor.process_pdf(local_pdf_path, local_text_path)

        if result:
            # Upload processed text back to S3
            s3_client.upload_file(local_text_path, BUCKET_NAME, s3_text_key)
            return s3_text_key
        return None

    finally:
        # Clean up temporary files
        if os.path.exists(local_pdf_path):
            os.remove(local_pdf_path)
        if os.path.exists(local_text_path):
            os.remove(local_text_path)
