"""
HyperOrch FastAPI server.

Serves the web frontend, REST API, WebSocket streams, and task routing.
"""
import asyncio
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from hyperorch import __version__
from hyperorch.model_manager import detect_all_models, model_process
from hyperorch.resource_monitor import get_snapshot
from hyperorch.context_store import save_context, load_context
from hyperorch.safety import check_memory
from hyperorch.task_router import router
from hyperorch.ollama_client import ollama

app = FastAPI(title="HyperOrch", version=__version__)


# ── Request models ──────────────────────────────────────────────

class LaunchRequest(BaseModel):
    name: str
    backend: str
    path: str | None = None
    gpu_layers: int = 0
    ctx_size: int = 2048
    quantization: str | None = None


class TaskRequest(BaseModel):
    task_type: str
    prompt: str
    messages: list[dict] | None = None


class ProfileRequest(BaseModel):
    name: str
    model: str
    hardware: str = "gpu"
    priority: int = 5
    description: str = ""
    fallback_model: str | None = None
    max_ctx: int = 4096
    guide: str = ""


# ── Static files ────────────────────────────────────────────────

os.makedirs("web/css", exist_ok=True)
os.makedirs("web/js", exist_ok=True)
if os.path.exists("web"):
    app.mount("/static", StaticFiles(directory="web"), name="static")


# ── Core routes ─────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    """Serve the web frontend."""
    if os.path.exists("web/index.html"):
        return FileResponse("web/index.html")
    return {"message": "web/index.html not found."}


@app.get("/api/models")
async def list_models():
    """List detected models (Ollama + GGUF)."""
    return detect_all_models()


@app.post("/api/launch")
async def launch_model(req: LaunchRequest):
    """Launch a model directly (bypass task router)."""
    config = req.dict()
    safety_check = check_memory(config)
    if not safety_check["safe"]:
        raise HTTPException(status_code=400,
                            detail={"warning": safety_check["warning"]})
    success = model_process.launch(config)
    if success:
        return {"status": "success", "message": f"Launched {req.name}"}
    raise HTTPException(status_code=500, detail="Failed to launch model.")


@app.post("/api/stop")
async def stop_model():
    """Stop running model."""
    model_process.stop()
    return {"status": "success", "message": "Model stopped"}


@app.get("/api/status")
async def get_status():
    """System status + router status."""
    return {
        "resources": get_snapshot(),
        "model": model_process.get_info(),
        "router": router.get_status(),
        "ollama_running": await ollama.is_running(),
    }


@app.get("/api/context")
async def read_context():
    """Read context state."""
    return load_context()


@app.post("/api/context")
async def write_context(data: dict):
    """Write context state."""
    save_context(data)
    return {"status": "success", "message": "Context saved"}


# ── Task Router routes ──────────────────────────────────────────

@app.get("/api/tasks/profiles")
async def get_profiles():
    """Get all task profiles with their hardware guides."""
    return router.get_profiles()


@app.post("/api/tasks/profiles")
async def set_profile(req: ProfileRequest):
    """Add or update a task profile."""
    router.set_profile(req.dict())
    return {"status": "success", "message": f"Profile '{req.name}' saved"}


@app.delete("/api/tasks/profiles/{name}")
async def delete_profile(name: str):
    """Delete a task profile."""
    if router.remove_profile(name):
        return {"status": "success"}
    raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")


@app.get("/api/tasks/history")
async def get_history():
    """Get recent task execution history."""
    return router.get_history()


@app.get("/api/tasks/ollama/models")
async def get_ollama_models():
    """Get models from Ollama API (more detail than detect)."""
    return await ollama.list_models()


@app.get("/api/tasks/ollama/running")
async def get_running():
    """Get models currently loaded in Ollama's memory."""
    return await ollama.get_running_models()


@app.post("/api/tasks/preload")
async def preload_model(body: dict):
    """Preload a model into Ollama's VRAM."""
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing 'model' field")
    ok = await ollama.preload(model)
    if ok:
        return {"status": "success", "message": f"{model} loaded into VRAM"}
    raise HTTPException(status_code=500, detail=f"Failed to preload {model}")


@app.post("/api/tasks/unload")
async def unload_model(body: dict):
    """Unload a model from Ollama's VRAM."""
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Missing 'model' field")
    ok = await ollama.unload(model)
    if ok:
        return {"status": "success", "message": f"{model} unloaded"}
    raise HTTPException(status_code=500, detail=f"Failed to unload {model}")


# ── WebSocket: Task streaming ──────────────────────────────────

@app.websocket("/ws/task")
async def websocket_task(websocket: WebSocket):
    """Stream task execution results.
    
    Client sends: {"task_type": "coding", "prompt": "write hello world in python"}
    Server streams: {"event": "token", "data": "..."} / {"event": "done", ...}
    """
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            import json
            try:
                req = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"event": "error", "data": "Invalid JSON"})
                continue

            task_type = req.get("task_type", "chat")
            prompt = req.get("prompt", "")
            messages = req.get("messages")

            async for event in router.route_task(
                    task_type, prompt, messages, stream=True):
                await websocket.send_json(event)

    except WebSocketDisconnect:
        pass


# ── WebSocket: Monitor ─────────────────────────────────────────

@app.websocket("/ws/monitor")
async def websocket_monitor(websocket: WebSocket):
    """Stream resource metrics every second."""
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(get_snapshot())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """Stream model output logs."""
    await websocket.accept()
    try:
        while True:
            out = model_process.read_output()
            if out:
                await websocket.send_text(out)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
