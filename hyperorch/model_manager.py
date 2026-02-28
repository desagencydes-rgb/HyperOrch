import os
import subprocess
from pathlib import Path
from queue import Queue
from threading import Thread

class ModelProcess:
    def __init__(self):
        self.process = None
        self.model_info = None
        self.stdout_queue = Queue()
        self._reader_thread = None

    def _enqueue_output(self, out, queue):
        try:
            for line in iter(out.readline, b''):
                queue.put(line.decode('utf-8', errors='replace'))
        except ValueError:
            pass  # Process closed
        out.close()

    def launch(self, config: dict) -> bool:
        """Launch a model subprocess.
        
        Supported backends:
          - 'ollama': Uses `ollama run <name>`. GPU offload is automatic
            (Ollama v0.12.6+ supports Vulkan for AMD GPUs).
          - 'llamacpp': Uses `llama-cli` with -ngl for GPU layer offload.
            Works with both CUDA (NVIDIA) and Vulkan (AMD) builds.
        """
        if self.is_running():
            self.stop()
            
        self.model_info = config
        backend = config.get("backend")
        
        try:
            if backend == "ollama":
                # Ollama v0.17.1 has built-in Vulkan support for AMD GPUs.
                # GPU offload happens automatically — no extra flags needed.
                cmd = ["ollama", "run", config["name"]]
            elif backend in ("llamacpp", "llamacpp-vulkan"):
                # llama-cli with Vulkan build uses the same -ngl flag as CUDA.
                # The user must have a Vulkan-enabled llama-cli binary.
                exe = config.get("executable", "llama-cli")
                cmd = [
                    exe,
                    "-m", config["path"],
                    "-ngl", str(config.get("gpu_layers", 0)),
                    "-c", str(config.get("ctx_size", 2048))
                ]
            else:
                return False

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                bufsize=1
            )
            
            # Start background thread to read output without blocking
            self._reader_thread = Thread(target=self._enqueue_output, args=(self.process.stdout, self.stdout_queue))
            self._reader_thread.daemon = True
            self._reader_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to launch model: {e}")
            self.process = None
            self.model_info = None
            return False

    def stop(self) -> bool:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            self.model_info = None
        return True

    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def get_info(self) -> dict | None:
        if not self.is_running():
            return None
        return self.model_info

    def read_output(self) -> str:
        out = []
        while not self.stdout_queue.empty():
            out.append(self.stdout_queue.get_nowait())
        return "".join(out)


model_process = ModelProcess()


def detect_ollama_models() -> list[dict]:
    """Detect models from Ollama."""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        models = []
        if len(lines) > 1:
            for line in lines[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    # e.g. "llama3:latest  1234567890ab  4.7 GB  2 days ago"
                    name = parts[0]
                    size = parts[-4] + " " + parts[-3]
                    models.append({
                        "name": name,
                        "size": size,
                        "format": "Unknown",
                        "backend": "ollama"
                    })
        return models
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


def detect_gguf_models(search_paths: list[str] = None) -> list[dict]:
    """Detect GGUF models in standard locations."""
    if search_paths is None:
        search_paths = [
            ".", 
            "models/", 
            os.path.expanduser("~/.cache/huggingface"), 
            os.path.expanduser("~/models")
        ]
        
    models = []
    
    for base_path in search_paths:
        path = Path(base_path)
        if not path.exists() or not path.is_dir():
            continue
            
        try:
            # We don't want to scan too deep, 2 levels max
            for gguf_file in path.rglob("*.gguf"):
                size_gb = round(gguf_file.stat().st_size / (1024**3), 2)
                models.append({
                    "name": gguf_file.name,
                    "path": str(gguf_file.absolute()),
                    "size_gb": size_gb,
                    "backend": "llamacpp"
                })
        except (PermissionError, OSError):
            continue
            
    return models


def detect_all_models(search_paths: list[str] = None) -> list[dict]:
    """Returns a combined list of Ollama and GGUF models."""
    return detect_ollama_models() + detect_gguf_models(search_paths)
