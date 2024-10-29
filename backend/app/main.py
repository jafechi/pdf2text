import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Dict

import aiofiles
from redis.asyncio import Redis
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from celery.result import AsyncResult
from .celery_app import celery_app
from .tasks import process_pdf_task
from starlette.websockets import WebSocketState


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

    await pubsub.unsubscribe('task_complete')
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
    data = json.loads(message['data'])
    task_id = data['task_id']

    print("From handle_redis_message ==> Task ID: ")
    print(task_id)

    client_id = task_to_clients.get(task_id)
    if client_id:
        websocket = active_connections.get(client_id)
        if websocket and websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_json({
                "task_id": task_id,
                "status": data['status']
            })
        del task_to_clients[task_id]


async def redis_listener(pubsub):
    """Listen for Redis messages"""
    try:
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True)
                if message and message['type'] == 'message':
                    await handle_redis_message(message)
            except Exception as e:
                print(f"Error in redis listener: {e}")
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        # Handle cancellation gracefully
        pass


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
task_to_clients: Dict[str, str] = {}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    pdf_path = os.path.join(UPLOAD_DIRECTORY, file.filename)
    txt_filename = f"{os.path.splitext(file.filename)[0]}.txt"
    txt_path = os.path.join(UPLOAD_DIRECTORY, txt_filename)

    # Save uploaded PDF
    async with aiofiles.open(pdf_path, 'wb') as out_file:
        content = await file.read()  # async read
        await out_file.write(content)  # async write

    task = process_pdf_task.delay(pdf_path, txt_path)

    return {"task_id": task.id}


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


async def send_task_completed_message(websocket: WebSocket, task_id: str):
    await websocket.send_json({"task_id": task_id, "status": "completed"})


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:
            data = await websocket.receive_json()
            task_id = data.get("task_id")
            if task_id:
                # Simply map the task to this client, overwriting any previous mapping
                task_to_clients[task_id] = client_id
    except WebSocketDisconnect:
        del active_connections[client_id]
        # Remove any tasks associated with this client
        task_ids_to_remove = [
            task_id for task_id, cid in task_to_clients.items()
            if cid == client_id
        ]
        for task_id in task_ids_to_remove:
            del task_to_clients[task_id]
    except Exception as e:
        await websocket.close()