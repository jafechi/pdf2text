import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Dict
from uuid import uuid4

import aiofiles
import boto3
from pydantic import BaseModel
from redis.asyncio import Redis
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from celery.result import AsyncResult
from .celery_app import celery_app
from .tasks import process_pdf_task
from starlette.websockets import WebSocketState
from .config import s3_client, BUCKET_NAME, AWS_REGION, S3_RAW_FOLDER, S3_PROCESSED_FOLDER

upload_id_to_s3_keys: Dict[str, Dict] = {}


async def setup_redis():
    """Setup Redis connection and pubsub"""
    redis = Redis.from_url(os.getenv('CELERY_RESULT_BACKEND'))
    pubsub = redis.pubsub()

    await pubsub.subscribe('task_complete')
    return redis, pubsub


async def cleanup_redis(app: FastAPI, redis: Redis, pubsub):
    """Cleanup Redis resources"""
    if hasattr(app, 'redis_listener_task'):
        app.redis_listener_task.cancel()
        try:
            await app.redis_listener_task
        except asyncio.CancelledError:
            pass

    await pubsub.close()
    await redis.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: setup Redis
    redis, pubsub = await setup_redis()
    app.redis_listener_task = asyncio.create_task(redis_listener(pubsub))

    try:
        yield
    finally:
        # Shutdown: cleanup Redis
        await cleanup_redis(app, redis, pubsub)


async def handle_redis_message(message: dict):
    """Handle an incoming Redis message and notify the relevant client"""
    if not message or message['type'] != 'message':
        return

    data = json.loads(message['data'])
    task_id = data['task_id']
    status = data['status']
    result = data.get('result')  # Not used.

    client_id = task_id_to_client_id.get(task_id)
    if client_id:
        websocket = active_connections.get(client_id)
        if websocket and websocket.client_state == WebSocketState.CONNECTED:
            # Send notification to the client
            await websocket.send_json({
                "task_id": task_id,
                "status": status,
                "upload_id": task_id_to_upload_id.get(task_id),  # TODO: Can it fail to find the upload_id?
            })
        # Clean up mappings
        del task_id_to_client_id[task_id]
        del task_id_to_upload_id[task_id]


async def redis_listener(pubsub):
    """Listen for Redis messages using get_message"""
    try:
        while True:
            try:
                message = await pubsub.get_message(timeout=1.0)  # 1 second timeout
                if message:
                    await handle_redis_message(message)
                await asyncio.sleep(0.01)  # Small sleep to be nice to the system
            except Exception as e:
                print(f"Error processing message: {e}")
                continue
    except asyncio.CancelledError:
        print("Redis listener shutting down")
        raise
    except Exception as e:
        print(f"Fatal error in redis listener: {e}")
        raise


app = FastAPI(lifespan=lifespan)

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

active_connections: Dict[str, WebSocket] = {}

# Dictionary to map from task_id to client ids
task_id_to_client_id: Dict[str, str] = {}
task_id_to_upload_id: Dict[str, str] = {}


class DownloadUrlRequest(BaseModel):
    upload_id: str


class DownloadUrlResponse(BaseModel):
    download_url: str


@app.post("/generate_download_url", response_model=DownloadUrlResponse)
async def generate_download_url(request: DownloadUrlRequest):

    # TODO: The downloaded files should have a readable name, not just the upload_id.

    s3_keys = upload_id_to_s3_keys.get(request.upload_id)
    if not s3_keys:
        raise HTTPException(status_code=400, detail="Invalid upload_id")

    s3_text_key = s3_keys["s3_text_key"]
    presigned_url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': BUCKET_NAME, 'Key': s3_text_key},
        ExpiresIn=3600  # Only allow the user to download for 1 hour
    )

    return DownloadUrlResponse(download_url=presigned_url)


class UploadCompleteRequest(BaseModel):
    upload_id: str
    client_id: str


@app.post("/upload_complete")
def upload_complete(request: UploadCompleteRequest):
    # Retrieve S3 keys using the upload_id
    s3_keys = upload_id_to_s3_keys.get(request.upload_id)
    if not s3_keys:
        raise HTTPException(status_code=400, detail="Invalid upload_id")

    s3_pdf_key = s3_keys["s3_pdf_key"]
    s3_text_key = s3_keys["s3_text_key"]

    # Assuming process_pdf_task is a Celery task
    task = process_pdf_task.delay(s3_pdf_key, s3_text_key)

    # Store the mappings
    task_id_to_client_id[task.id] = request.client_id
    task_id_to_upload_id[task.id] = request.upload_id

    return {
        "task_id": task.id
    }


@app.get("/result/{task_id}")
def get_result(task_id: str):
    result = AsyncResult(task_id, app=celery_app)

    # TODO: Detect when the task_id is invalid

    if result.ready():
        txt_path = result.get()

        if not txt_path:
            # TODO: Analyze what to do here. Retry? Just return an error?
            return {"status": "Error"}

        return FileResponse(txt_path, media_type='text/plain', filename=os.path.basename(txt_path))
    else:
        return {"status": "Processing"}


@app.post("/generate_presigned_url")
def generate_presigned_url():
    upload_id = str(uuid4())

    s3_pdf_key = f"{S3_RAW_FOLDER}/{upload_id}.pdf"
    s3_text_key = f"{S3_PROCESSED_FOLDER}/{upload_id}.txt"

    presigned_url = s3_client.generate_presigned_post(
        Bucket=BUCKET_NAME,
        Key=s3_pdf_key,
        ExpiresIn=1200  # I assume that no file will take longer than 20 minutes to upload
    )

    upload_id_to_s3_keys[upload_id] = {
        "s3_pdf_key": s3_pdf_key,
        "s3_text_key": s3_text_key
    }

    return {
        "upload_url": presigned_url,
        "upload_id": upload_id
    }


async def send_task_completed_message(websocket: WebSocket, task_id: str):
    await websocket.send_json({"task_id": task_id, "status": "completed"})


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:  # Keep the connection alive
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        del active_connections[client_id]
    except Exception as e:
        await websocket.close()
