from celery_app import celery_app

@celery_app.task
def extract_text_from_pdf(pdf_path, txt_path):
    # text = extract_text(pdf_path)
    text = "Placeholder text"
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(text)
    # Return the relative path to the text file
    return txt_path
