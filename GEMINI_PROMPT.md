# HyperOrch — Execution Prompt for Gemini 3.1 Pro

You are continuing the **HyperOrch** project. All architecture decisions have been made. Your job is to **implement every file** listed below, exactly as specified. Do NOT redesign or re-architect — just build.

## Project Location
```
c:\Projects\HyperOrch\
```

## Context File
Read `context.json` in the project root FIRST. It contains the full architecture, API specs, schemas, orchestration rules, and dependency list.

---

## BUILD ORDER (follow this exactly)

### Step 1 — Config Files
Create these files in the project root:

**requirements.txt**
```
fastapi>=0.110.0
uvicorn[standard]>=0.28.0
click>=8.1.0
psutil>=5.9.0
gputil>=1.4.0
websockets>=12.0
```

**setup.py**
```python
from setuptools import setup, find_packages

setup(
    name="hyperorch",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.28.0",
        "click>=8.1.0",
        "psutil>=5.9.0",
        "gputil>=1.4.0",
        "websockets>=12.0",
    ],
    entry_points={
        "console_scripts": [
            "hyperorch=hyperorch.cli:main",
        ],
    },
    python_requires=">=3.10",
)
```

**.gitignore**
```
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
.venv/
venv/
env/
.env
node_modules/
*.log
```

---

### Step 2 — Python Package: `hyperorch/`

Create directory `hyperorch/` and the following files inside it.

#### 2a. `hyperorch/__init__.py`
```python
__version__ = "0.1.0"
```

#### 2b. `hyperorch/resource_monitor.py`
This module provides system resource monitoring.

Must implement:
- `get_snapshot() -> dict` — Returns `{"cpu_percent", "ram_used_gb", "ram_total_gb", "ram_percent", "gpu_name", "gpu_util_percent", "vram_used_gb", "vram_total_gb", "vram_percent"}`. GPU fields are `None` if no NVIDIA GPU detected. Use `psutil` for CPU/RAM. Try importing `GPUtil` for GPU — if import fails or no GPU found, set GPU fields to `None`.
- `get_hardware_info() -> dict` — Returns static hardware info: `{"cpu_name": platform.processor(), "cpu_cores": psutil.cpu_count(), "ram_total_gb", "gpu_name", "vram_total_gb"}`.

#### 2c. `hyperorch/model_manager.py`
This module detects and launches models.

Must implement:
- `detect_ollama_models() -> list[dict]` — Run `ollama list` via `subprocess.run`, parse the tabular output. Each model dict: `{"name", "size", "format", "backend": "ollama"}`. If `ollama` not found in PATH, return empty list (don't crash).
- `detect_gguf_models(search_paths: list[str] = None) -> list[dict]` — Scan directories for `*.gguf` files. Default search paths: `[".", "models/", os.path.expanduser("~/.cache/huggingface"), os.path.expanduser("~/models")]`. Each model dict: `{"name": filename, "path": full_path, "size_gb": file_size, "backend": "llamacpp"}`.
- `detect_all_models(search_paths=None) -> list[dict]` — Combines both.
- Class `ModelProcess` with:
  - `__init__(self)` — stores `self.process = None`, `self.model_info = None`
  - `launch(self, config: dict) -> bool` — Launches model. If `config["backend"] == "ollama"`: runs `ollama run <name>`. If `config["backend"] == "llamacpp"`: runs `llama-cli -m <path> -ngl <gpu_layers> -c <ctx_size>`. Store the subprocess in `self.process`. Return True on success.
  - `stop(self) -> bool` — Terminate `self.process`.
  - `is_running(self) -> bool`
  - `get_info(self) -> dict | None`
  - `read_output(self) -> str` — Read available stdout from process (non-blocking).

Use a module-level singleton: `model_process = ModelProcess()`

#### 2d. `hyperorch/context_store.py`
Must implement:
- `get_default_context() -> dict` — Returns a full context dict with default values. Use `resource_monitor.get_hardware_info()` to populate hardware fields. Schema is defined in `context.json` — match it exactly.
- `save_context(data: dict, path: str = "context.json")` — Write JSON with `indent=2`.
- `load_context(path: str = "context.json") -> dict` — Read JSON. If file not found, return `get_default_context()`.

#### 2e. `hyperorch/safety.py`
Must implement:
- `estimate_model_memory_gb(model_info: dict) -> float` — Estimate from file size (for GGUF) or from model name heuristics (for Ollama: "7b" → ~4GB, "13b" → ~8GB, "70b" → ~40GB). Default to 4.0 if can't determine.
- `check_memory(model_info: dict, threshold_pct: int = 85) -> dict` — Returns `{"safe": bool, "warning": str|None, "estimated_gb": float, "available_gb": float}`. Uses `resource_monitor.get_snapshot()`.
- `confirm_overwrite(path: str) -> bool` — CLI-only: uses `click.confirm()` to ask user.

#### 2f. `hyperorch/orchestrator.py`
Must implement:
- `decide_execution_config(model_info: dict, preferences: dict = None) -> dict` — Returns a launch config dict: `{"gpu_layers", "ctx_size", "quantization", "backend", "warnings": []}`. Logic (from context.json orchestrator_logic):
  - Get system snapshot from resource_monitor
  - If GPU available AND vram >= model_size * 1.2 → `gpu_layers = -1` (full offload)
  - If GPU available AND vram >= model_size * 0.5 → calculate proportional layers (e.g. `int((vram / model_size) * 40)`)
  - If vram < model_size * 0.5 or no GPU → `gpu_layers = 0`, recommend quantization
  - Quantization recommendation: ram>=32 → Q8_0, 16-32 → Q5_K_M, 8-16 → Q4_K_M, <8 → Q3_K_S
  - If total memory insufficient → add warning string to warnings list
  - If `preferences` dict has overrides (gpu_layers, ctx_size, quantization), use those instead
- `recommend_fallback(model_info: dict) -> dict` — Returns `{"action": "remote", "message": "...", "endpoint": None}` as a stub.

#### 2g. `hyperorch/server.py`
FastAPI application. Must implement:

```python
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio, json

app = FastAPI(title="HyperOrch", version="0.1.0")
```

Routes (see context.json for full spec):
- `GET /` → `FileResponse("web/index.html")`
- `GET /api/models` → calls `model_manager.detect_all_models()`, returns JSON list
- `POST /api/launch` → receives JSON body `{name, backend, gpu_layers, ctx_size, quantization}`. Calls `safety.check_memory()` first — if not safe, return 400 with warning. Then calls `model_process.launch(config)`. Returns success/failure.
- `POST /api/stop` → calls `model_process.stop()`
- `GET /api/status` → returns `{"resources": resource_monitor.get_snapshot(), "model": model_process.get_info()}`
- `GET /api/context` → returns `context_store.load_context()`
- `POST /api/context` → receives JSON body, calls `context_store.save_context(body)`
- `WS /ws/monitor` → loop: every 1 second, send `resource_monitor.get_snapshot()` as JSON
- `WS /ws/logs` → loop: every 0.5 second, send `model_process.read_output()` if not empty

Mount static files: `app.mount("/static", StaticFiles(directory="web"), name="static")` — but serve CSS/JS from `/static/css/` and `/static/js/`. The index.html refs should use `/static/css/style.css` etc.

#### 2h. `hyperorch/cli.py`
Click CLI. Must implement:

```python
import click

@click.group()
def main():
    """HyperOrch — AI Orchestration System"""
    pass
```

Commands:
- `@main.command("detect")` — calls `detect_all_models()`, prints table of results using `click.echo`
- `@main.command("launch")` with argument `model` and options `--backend`, `--gpu-layers`, `--ctx-size`, `--quant` — calls orchestrator.decide_execution_config, then safety.check_memory, then model_process.launch. Print status.
- `@main.command("stop")` — stops model, prints confirmation
- `@main.command("status")` — prints resource snapshot + model info in formatted way
- `@main.group("context")` with subcommands `save` and `load` that take optional `file` argument
- `@main.command("serve")` with option `--port` (default 8000) — runs `uvicorn.run("hyperorch.server:app", host="0.0.0.0", port=port)`

---

### Step 3 — Frontend: `web/`

Create directories `web/`, `web/css/`, `web/js/`.

#### 3a. `web/css/style.css`
Build a premium dark-mode UI:
- Background: `#0a0a0f` (near-black)
- Cards: `rgba(255,255,255,0.05)` with `backdrop-filter: blur(12px)`, border `1px solid rgba(255,255,255,0.1)`
- Primary accent: `#6c5ce7` (violet), secondary: `#00cec9` (teal)
- Font: Import Google Font `Inter` (weights 400, 500, 600, 700)
- All buttons: rounded corners, gradient backgrounds, hover glow effect with `box-shadow`
- Status indicators: green dot = running, red dot = stopped, amber dot = warning
- Panels: CSS Grid layout, 2-column on desktop, single-column on mobile
- Scrolling log panel: monospace font, dark background, max-height with overflow-y scroll
- Smooth transitions on hover/focus (0.2s ease)
- Active model card: subtle pulsing border animation

#### 3b. `web/index.html`
Single-page app. Structure:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HyperOrch — AI Orchestration</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <!-- HEADER: Logo, title "HyperOrch", connection status dot -->
    <!-- DASHBOARD SECTION: 3 chart canvases (CPU, RAM, GPU) in row -->
    <!-- MODEL PANEL: Model list (populated by JS), launch form (backend select, gpu_layers slider, ctx_size input, quant dropdown), Launch/Stop buttons -->
    <!-- LOGS PANEL: <pre id="log-output"> scrolling log area -->
    <!-- CONTEXT PANEL: Save/Load buttons, <pre id="context-viewer"> JSON display -->
    
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
    <script src="/static/js/websocket.js"></script>
    <script src="/static/js/monitor.js"></script>
    <script src="/static/js/app.js"></script>
</body>
</html>
```

Implement ALL the HTML elements. Don't use placeholders — build the full structure with proper IDs.

#### 3c. `web/js/websocket.js`
```javascript
class HyperWebSocket {
    constructor(path, onMessage) { ... }
    connect() { ... }  // auto-reconnect on close with 3s delay
    disconnect() { ... }
    send(data) { ... }
}
```
Create two instances: one for `/ws/monitor`, one for `/ws/logs`. Export/attach to window.

#### 3d. `web/js/monitor.js`
- Create 3 Chart.js doughnut charts (CPU, RAM, GPU)
- Function `updateCharts(snapshot)` — updates chart data from resource snapshot
- Charts should have the teal/violet color scheme
- GPU chart shows "No GPU" placeholder if gpu fields are null

#### 3e. `web/js/app.js`
Main controller:
- On load: fetch `/api/models`, populate model list. Fetch `/api/status`, update UI.
- `launchModel()` — read form values, POST to `/api/launch`
- `stopModel()` — POST to `/api/stop`
- `saveContext()` — POST to `/api/context` with current state
- `loadContext()` — GET `/api/context`, display in viewer
- Connect WebSocket for monitor → feed `updateCharts()`
- Connect WebSocket for logs → append to `#log-output`
- Update connection status dot based on WebSocket state

---

### Step 4 — README.md

Create `README.md` with:
- Project title and one-line description
- Prerequisites (Python 3.10+, optionally Ollama and/or llama.cpp)
- Install steps: `pip install -e .`
- CLI usage examples for each command
- Web UI: `hyperorch serve` then open http://localhost:8000
- Context system explanation
- Architecture diagram (text-based)
- License: MIT

---

## VERIFICATION STEPS (do these after building)

1. Run `pip install -e .` in the project root
2. Run `hyperorch detect` — should complete without errors (may show 0 models)
3. Run `hyperorch status` — should print CPU/RAM info
4. Run `hyperorch serve` — should start on port 8000
5. Open http://localhost:8000 in browser — verify the UI loads with charts
6. Run `hyperorch context save` — should create/update context.json
7. Run `hyperorch context load` — should print the saved context

---

## IMPORTANT RULES
- Do NOT modify `context.json` structure — it's the project's state schema
- Do NOT add new dependencies beyond what's in requirements.txt
- Do NOT use React, Vue, or any JS framework — vanilla JS only
- ALL Python imports must be from stdlib or from requirements.txt
- Every function must have a docstring
- Handle missing Ollama/llama.cpp gracefully (don't crash — return empty results)
- The web UI must look PREMIUM — dark glassmorphism theme, not a basic HTML page
