import asyncio
import json
import os
from typing import Dict, List

import aiofiles
# import aioredis
from redis.asyncio import Redis
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from celery.result import AsyncResult
from .celery_app import celery_app
from .tasks import process_pdf_task
from celery.signals import task_success, task_failure, task_prerun
from starlette.websockets import WebSocketState

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

active_connections: Dict[str, WebSocket] = {}

# Dictionary to map from task_id to client IDs
task_to_clients: Dict[str, List[str]] = {}  # TODO: Modify this because only one client is interested in the task


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
            # TOOD: Analyze what to do here. Retry? Just return an error?
            return {"status": "Error"}

        return FileResponse(txt_path, media_type='text/plain', filename=os.path.basename(txt_path))
    else:
        return {"status": "Processing"}

async def send_task_completed_message(websocket: WebSocket, task_id: str):
    await websocket.send_json({"task_id": task_id, "status": "completed"})

async def redis_listener():
    # Create Redis connection using redis.asyncio
    redis = Redis.from_url(os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'))
    pubsub = redis.pubsub()
    await pubsub.subscribe('task_complete')

    try:
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True)
                if message and message['type'] == 'message':
                    data = json.loads(message['data'])
                    task_id = data['task_id']

                    print("From redis_listener ==> Task ID: ")
                    print(task_id)

                    if task_id in task_to_clients:
                        clients = task_to_clients[task_id]
                        for client_id in clients:
                            websocket = active_connections.get(client_id)
                            if websocket and websocket.client_state == WebSocketState.CONNECTED:
                                await websocket.send_json({
                                    "task_id": task_id,
                                    "status": data['status']
                                })
                        # Clean up after notification
                        del task_to_clients[task_id]
            except Exception as e:
                print(f"Error in redis listener: {e}")
                await asyncio.sleep(1)
    finally:
        # Clean up Redis connection when the listener stops
        await pubsub.unsubscribe('task_complete')
        await redis.close()

app.redis_listener_task = None  # Initialize the task holder

@app.on_event("startup")
async def startup_event():
    # Create and store the background task
    app.redis_listener_task = asyncio.create_task(redis_listener())

# Optionally, clean up on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    if app.redis_listener_task:
        app.redis_listener_task.cancel()
        try:
            await app.redis_listener_task
        except asyncio.CancelledError:
            pass


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:
            data = await websocket.receive_json()
            task_id = data.get("task_id")
            if task_id:
                if task_id in task_to_clients:
                    task_to_clients[task_id].append(client_id)
                else:
                    task_to_clients[task_id] = [client_id]
    except WebSocketDisconnect:
        del active_connections[client_id]
        for clients in task_to_clients.values():
            if client_id in clients:
                clients.remove(client_id)
    except Exception as e:
        await websocket.close()