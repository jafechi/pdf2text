from .celery_app import celery_app
from .pdf_processor import PDFProcessor


@celery_app.task
def process_pdf_task(pdf_path, txt_path):
    processor = PDFProcessor()
    result = processor.process_pdf(pdf_path, txt_path)
    if result:
        return txt_path
    else:
        return None
