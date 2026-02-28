"""
Ollama API client for HyperOrch.

Talks to Ollama's REST API at localhost:11434 for:
- Model management (list, load, unload)
- Chat completions (streaming and non-streaming)
- Embeddings
- Status checks (what's loaded in VRAM)
"""
import json
import time
import httpx
from typing import AsyncGenerator

OLLAMA_BASE = "http://localhost:11434"


class OllamaClient:
    """Async client for the Ollama REST API."""

    def __init__(self, base_url: str = OLLAMA_BASE):
        self.base_url = base_url
        self._loaded_model: str | None = None
        self._last_load_time: float = 0

    # ------------------------------------------------------------------
    # Connection & status
    # ------------------------------------------------------------------
    async def is_running(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{self.base_url}/", timeout=3)
                return r.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        """List models available in Ollama."""
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{self.base_url}/api/tags", timeout=10)
                data = r.json()
                return data.get("models", [])
        except Exception:
            return []

    async def get_running_models(self) -> list[dict]:
        """List models currently loaded in memory."""
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{self.base_url}/api/ps", timeout=5)
                data = r.json()
                return data.get("models", [])
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    async def generate(self, model: str, prompt: str,
                       stream: bool = True, **kwargs) -> AsyncGenerator[str, None]:
        """Generate text (streaming). Yields token strings."""
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            **kwargs
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as c:
            async with c.stream("POST", f"{self.base_url}/api/generate",
                                json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("response", "")
                            if token:
                                yield token
                            if chunk.get("done"):
                                self._loaded_model = model
                                self._last_load_time = time.time()
                                return
                        except json.JSONDecodeError:
                            continue

    async def generate_full(self, model: str, prompt: str, **kwargs) -> str:
        """Generate text (non-streaming). Returns full response string."""
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            **kwargs
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as c:
            r = await c.post(f"{self.base_url}/api/generate", json=payload)
            data = r.json()
            self._loaded_model = model
            self._last_load_time = time.time()
            return data.get("response", "")

    async def chat(self, model: str, messages: list[dict],
                   stream: bool = True, **kwargs) -> AsyncGenerator[str, None]:
        """Chat completion (streaming). Yields content strings."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as c:
            async with c.stream("POST", f"{self.base_url}/api/chat",
                                json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if chunk.get("done"):
                                self._loaded_model = model
                                self._last_load_time = time.time()
                                return
                        except json.JSONDecodeError:
                            continue

    async def embed(self, model: str, text: str) -> list[float]:
        """Generate embeddings."""
        payload = {"model": model, "input": text}
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as c:
            r = await c.post(f"{self.base_url}/api/embed", json=payload)
            data = r.json()
            # Returns list of embeddings; take the first
            embeddings = data.get("embeddings", [[]])
            return embeddings[0] if embeddings else []

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------
    async def preload(self, model: str) -> bool:
        """Preload a model into VRAM without generating anything.
        
        Sends a generate request with empty prompt and keep_alive.
        This forces Ollama to load the model into memory.
        """
        try:
            payload = {
                "model": model,
                "prompt": "",
                "keep_alive": "10m"
            }
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as c:
                r = await c.post(f"{self.base_url}/api/generate", json=payload)
                if r.status_code == 200:
                    self._loaded_model = model
                    self._last_load_time = time.time()
                    return True
        except Exception:
            pass
        return False

    async def unload(self, model: str) -> bool:
        """Unload a model from VRAM by setting keep_alive to 0."""
        try:
            payload = {
                "model": model,
                "prompt": "",
                "keep_alive": 0
            }
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
                r = await c.post(f"{self.base_url}/api/generate", json=payload)
                if r.status_code == 200:
                    if self._loaded_model == model:
                        self._loaded_model = None
                    return True
        except Exception:
            pass
        return False

    @property
    def loaded_model(self) -> str | None:
        """The model we believe is currently loaded in VRAM."""
        return self._loaded_model

    @property
    def last_load_time(self) -> float:
        """Timestamp when the last model was loaded."""
        return self._last_load_time


# Module-level singleton
ollama = OllamaClient()
