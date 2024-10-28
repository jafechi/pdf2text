import os
import aiofiles
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from celery.result import AsyncResult
from tasks import extract_text_from_pdf
from celery_app import celery_app

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIRECTORY = "/data"

if not os.path.exists(UPLOAD_DIRECTORY):
    os.makedirs(UPLOAD_DIRECTORY)


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    pdf_path = os.path.join(UPLOAD_DIRECTORY, file.filename)
    txt_filename = f"{os.path.splitext(file.filename)[0]}.txt"
    txt_path = os.path.join(UPLOAD_DIRECTORY, txt_filename)

    # Save uploaded PDF
    async with aiofiles.open(pdf_path, 'wb') as out_file:
        content = await file.read()  # async read
        await out_file.write(content)  # async write

    print("Hello")

    # Start Celery task
    task = extract_text_from_pdf.delay(pdf_path, txt_path)

    return {"task_id": task.id}


@app.get("/result/{task_id}")
def get_result(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    if result.ready():
        txt_path = result.get()
        return FileResponse(txt_path, media_type='text/plain', filename=os.path.basename(txt_path))
    else:
        return {"status": "Processing"}

# TODO: Use websockets to push updates to the client
