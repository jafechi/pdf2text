import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Dict
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from celery.result import AsyncResult
from .celery_app import celery_app
from .tasks import process_pdf_task
from starlette.websockets import WebSocketState
from .config import s3_client, BUCKET_NAME, S3_RAW_FOLDER, S3_PROCESSED_FOLDER
from .models import TASK_COMPLETE_CHANNEL, TaskCompleteMessage, WebSocketNotificationMessage

upload_id_to_s3_keys: Dict[str, Dict] = {}

active_connections: Dict[str, WebSocket] = {}


task_id_to_client_id: Dict[str, str] = {}
task_id_to_upload_id: Dict[str, str] = {}


async def setup_redis():
    """Setup Redis connection and pubsub"""
    redis = Redis.from_url(os.getenv('CELERY_RESULT_BACKEND'))
    pubsub = redis.pubsub()

    await pubsub.subscribe(TASK_COMPLETE_CHANNEL)
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
    redis, pubsub = await setup_redis()
    app.redis_listener_task = asyncio.create_task(redis_listener(pubsub))

    try:
        yield
    finally:
        await cleanup_redis(app, redis, pubsub)


async def handle_redis_message(message: dict):
    """Handle an incoming Redis message and notify the relevant client"""
    if not message or message['type'] != 'message':
        return

    try:
        data = TaskCompleteMessage.model_validate(json.loads(message['data']))
    except ValidationError as e:
        print(f"Invalid message format: {e}")
        return

    client_id = task_id_to_client_id.get(data.task_id)
    if client_id:
        websocket = active_connections.get(client_id)
        if websocket and websocket.client_state == WebSocketState.CONNECTED:
            upload_id = task_id_to_upload_id.get(data.task_id)
            task_complete_notification = WebSocketNotificationMessage(task_id=data.task_id, status=data.status,
                                                                      upload_id=upload_id)
            await websocket.send_json(task_complete_notification.model_dump())
        # Clean up mappings
        del task_id_to_client_id[data.task_id]
        del task_id_to_upload_id[data.task_id]


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
    s3_keys = upload_id_to_s3_keys.get(request.upload_id)
    if not s3_keys:
        raise HTTPException(status_code=400, detail="Invalid upload_id")

    s3_pdf_key = s3_keys["s3_pdf_key"]
    s3_text_key = s3_keys["s3_text_key"]

    task = process_pdf_task.delay(s3_pdf_key, s3_text_key)

    task_id_to_client_id[task.id] = request.client_id
    task_id_to_upload_id[task.id] = request.upload_id

    return {
        "task_id": task.id
    }


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
    completed_notification = WebSocketNotificationMessage(task_id=task_id, status="completed")
    await websocket.send_json(completed_notification.model_dump_json())


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
