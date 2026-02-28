import json
import os
from datetime import datetime
from hyperorch.resource_monitor import get_hardware_info

def get_default_context() -> dict:
    """Returns a full context dict with default values."""
    hw = get_hardware_info()
    
    return {
        "version": "1.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "hardware": {
            "cpu_name": hw["cpu_name"],
            "cpu_cores": hw["cpu_cores"],
            "ram_total_gb": hw["ram_total_gb"],
            "gpu_name": hw["gpu_name"],
            "vram_total_gb": hw["vram_total_gb"]
        },
        "active_model": {
            "name": None,
            "backend": None,
            "gpu_layers": 0,
            "ctx_size": 2048,
            "quantization": None,
            "pid": None
        },
        "model_configs": [
            {
                "name": "example-llama3",
                "backend": "ollama",
                "path": None,
                "default_gpu_layers": -1,
                "default_ctx_size": 4096,
                "default_quantization": None
            }
        ],
        "prompts": [
            {
                "label": "Default System",
                "template": "You are a helpful AI assistant."
            }
        ],
        "cli_settings": {
            "default_backend": "ollama",
            "gguf_search_paths": [".", "models/", "~/models"],
            "auto_detect_on_start": True
        },
        "ui_settings": {
            "theme": "dark",
            "monitor_interval_ms": 1000,
            "log_max_lines": 500
        },
        "orchestrator_settings": {
            "auto_gpu": True,
            "memory_threshold_pct": 85,
            "vram_threshold_pct": 90,
            "prefer_quantization": "Q4_K_M",
            "fallback_remote_endpoint": None
        }
    }


def save_context(data: dict, path: str = "context.json"):
    """Write context state to JSON."""
    data["timestamp"] = datetime.utcnow().isoformat() + "Z"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_context(path: str = "context.json") -> dict:
    """Read context state from JSON. Returns defaults if not found."""
    if not os.path.exists(path):
        return get_default_context()
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return get_default_context()
