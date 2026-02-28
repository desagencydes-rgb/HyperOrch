"""
Task Router for HyperOrch.

Routes tasks to the optimal model/hardware based on configurable task profiles.
Manages model loading, queueing, and hardware assignment.

Task Profiles define: which model to use, GPU vs CPU preference,
priority level, and fallback options.
"""
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator
from hyperorch.ollama_client import ollama
from hyperorch.resource_monitor import get_snapshot


class Hardware(str, Enum):
    GPU = "gpu"
    CPU = "cpu"
    AUTO = "auto"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    LOADING_MODEL = "loading_model"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskProfile:
    """Defines how a task type should be routed."""
    name: str                          # e.g. "coding", "chat", "embed"
    model: str                         # Ollama model name e.g. "qwen2.5-coder:7b"
    hardware: Hardware = Hardware.GPU   # Preferred hardware
    priority: int = 5                  # 1=highest, 10=lowest
    description: str = ""              # Human-readable explanation
    fallback_model: str | None = None  # If primary model unavailable
    max_ctx: int = 4096                # Context window
    guide: str = ""                    # Explanation of why this assignment

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "hardware": self.hardware.value,
            "priority": self.priority,
            "description": self.description,
            "fallback_model": self.fallback_model,
            "max_ctx": self.max_ctx,
            "guide": self.guide,
        }

    @staticmethod
    def from_dict(d: dict) -> "TaskProfile":
        return TaskProfile(
            name=d["name"],
            model=d["model"],
            hardware=Hardware(d.get("hardware", "gpu")),
            priority=d.get("priority", 5),
            description=d.get("description", ""),
            fallback_model=d.get("fallback_model"),
            max_ctx=d.get("max_ctx", 4096),
            guide=d.get("guide", ""),
        )


@dataclass
class TaskResult:
    """Result of a completed task."""
    task_id: str
    profile_name: str
    model_used: str
    hardware_used: str
    status: TaskStatus
    response: str = ""
    tokens_per_sec: float = 0.0
    duration_sec: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "profile_name": self.profile_name,
            "model_used": self.model_used,
            "hardware_used": self.hardware_used,
            "status": self.status.value,
            "response": self.response,
            "tokens_per_sec": self.tokens_per_sec,
            "duration_sec": self.duration_sec,
            "error": self.error,
        }


# --------------------------------------------------------------------------
# Default task profiles optimized for RX 6650 XT (8GB VRAM) + 16GB RAM
# --------------------------------------------------------------------------
DEFAULT_PROFILES: list[TaskProfile] = [
    TaskProfile(
        name="coding",
        model="qwen2.5-coder:7b",
        hardware=Hardware.GPU,
        priority=1,
        description="Code generation and completion",
        fallback_model="deepseek-coder:6.7b",
        max_ctx=8192,
        guide=(
            "Code generation needs fast token output and large context for "
            "understanding codebases. A 7B coding model fits entirely in your "
            "8GB VRAM for maximum speed. GPU is essential here because you're "
            "waiting for every token interactively."
        ),
    ),
    TaskProfile(
        name="chat",
        model="llama3:latest",
        hardware=Hardware.GPU,
        priority=2,
        description="General conversation and Q&A",
        fallback_model="hermes3:8b",
        max_ctx=4096,
        guide=(
            "Chat is interactive — you stare at the screen waiting. GPU gives "
            "you 30-50 tokens/sec vs ~5-10 on CPU. Llama 3 at 4.7GB fits "
            "comfortably in your 8GB VRAM with room to spare."
        ),
    ),
    TaskProfile(
        name="reasoning",
        model="hermes3:8b",
        hardware=Hardware.GPU,
        priority=2,
        description="Complex reasoning and analysis",
        fallback_model="dolphin-llama3:8b",
        max_ctx=4096,
        guide=(
            "Reasoning tasks benefit from larger, smarter models. Hermes 3 "
            "is instruction-tuned for careful step-by-step thinking. GPU keeps "
            "it fast since you usually wait for the full answer."
        ),
    ),
    TaskProfile(
        name="summarize",
        model="dolphin-mistral:latest",
        hardware=Hardware.AUTO,
        priority=5,
        description="Text summarization (can run in background)",
        fallback_model="dolphin-phi:latest",
        max_ctx=4096,
        guide=(
            "Summarization is often a background job — you send a long text "
            "and come back later. AUTO means: use GPU if it's free, otherwise "
            "queue or fall back to a smaller CPU model. No rush."
        ),
    ),
    TaskProfile(
        name="embed",
        model="nomic-embed-text:latest",
        hardware=Hardware.CPU,
        priority=8,
        description="Text embeddings for RAG / search",
        fallback_model=None,
        max_ctx=2048,
        guide=(
            "Embedding models are tiny (~274MB). Running them on CPU is fast "
            "enough and leaves your GPU free for interactive tasks. Never "
            "waste GPU VRAM on a 274MB model when you have 8GB."
        ),
    ),
    TaskProfile(
        name="background",
        model="dolphin-phi:latest",
        hardware=Hardware.CPU,
        priority=10,
        description="Low-priority background tasks",
        fallback_model=None,
        max_ctx=2048,
        guide=(
            "Background tasks (batch processing, data cleanup, etc.) should "
            "use the smallest model on CPU. Dolphin-Phi is only 1.6GB — it "
            "runs fine on CPU and doesn't compete for GPU resources."
        ),
    ),
]


class TaskRouter:
    """Routes tasks to optimal models based on profiles and system state."""

    def __init__(self):
        self.profiles: dict[str, TaskProfile] = {
            p.name: p for p in DEFAULT_PROFILES
        }
        self._task_counter = 0
        self._active_task: dict | None = None
        self._queue: list[dict] = []
        self._history: list[TaskResult] = []
        self._gpu_model: str | None = None  # Model currently loaded on GPU

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------
    def get_profiles(self) -> list[dict]:
        """Get all task profiles as dicts."""
        return [p.to_dict() for p in self.profiles.values()]

    def set_profile(self, profile_dict: dict):
        """Add or update a task profile."""
        p = TaskProfile.from_dict(profile_dict)
        self.profiles[p.name] = p

    def remove_profile(self, name: str) -> bool:
        """Remove a task profile."""
        if name in self.profiles:
            del self.profiles[name]
            return True
        return False

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------
    async def route_task(self, task_type: str, prompt: str,
                         messages: list[dict] | None = None,
                         stream: bool = True) -> AsyncGenerator[dict, None]:
        """Route a task to the right model and yield streaming results.
        
        Yields dicts like:
            {"event": "status", "data": "Loading model..."}
            {"event": "token", "data": "Hello"}
            {"event": "done", "data": {result_dict}}
        """
        profile = self.profiles.get(task_type)
        if not profile:
            yield {"event": "error", "data": f"Unknown task type: {task_type}"}
            return

        self._task_counter += 1
        task_id = f"task_{self._task_counter}_{int(time.time())}"

        # Check if Ollama is running
        if not await ollama.is_running():
            yield {"event": "error", "data": "Ollama is not running. Start it with 'ollama serve'."}
            return

        # Decide which model to use
        model = profile.model
        hardware = profile.hardware

        # AUTO hardware: check if GPU is free
        if hardware == Hardware.AUTO:
            running = await ollama.get_running_models()
            if running:
                # GPU is occupied — use CPU fallback if available
                if profile.fallback_model:
                    model = profile.fallback_model
                    hardware = Hardware.CPU
                    yield {"event": "status",
                           "data": f"GPU busy. Falling back to {model} on CPU."}
                else:
                    hardware = Hardware.GPU  # No fallback, wait for GPU
            else:
                hardware = Hardware.GPU

        yield {"event": "status",
               "data": f"Routing '{task_type}' → {model} ({hardware.value})"}

        # If this model needs GPU and a different model is loaded, warn about swap
        if hardware == Hardware.GPU and self._gpu_model and self._gpu_model != model:
            yield {"event": "status",
                   "data": f"Swapping GPU model: {self._gpu_model} → {model} (~5-10s)"}

        # Preload model
        yield {"event": "status", "data": f"Loading {model}..."}
        start_time = time.time()

        try:
            if messages:
                # Chat mode
                tokens = []
                async for token in ollama.chat(model, messages, stream=True):
                    tokens.append(token)
                    yield {"event": "token", "data": token}
            elif profile.name == "embed":
                # Embedding mode
                embedding = await ollama.embed(model, prompt)
                tokens = [str(len(embedding)) + " dimensions"]
                yield {"event": "token",
                       "data": f"Generated embedding with {len(embedding)} dimensions"}
            else:
                # Generate mode
                tokens = []
                async for token in ollama.generate(model, prompt, stream=True):
                    tokens.append(token)
                    yield {"event": "token", "data": token}

            duration = time.time() - start_time
            full_response = "".join(tokens)
            approx_tps = len(full_response.split()) / max(duration, 0.1) * 1.3

            self._gpu_model = model if hardware == Hardware.GPU else self._gpu_model

            result = TaskResult(
                task_id=task_id,
                profile_name=task_type,
                model_used=model,
                hardware_used=hardware.value,
                status=TaskStatus.COMPLETED,
                response=full_response,
                tokens_per_sec=round(approx_tps, 1),
                duration_sec=round(duration, 2),
            )
            self._history.append(result)

            yield {"event": "done", "data": result.to_dict()}

        except Exception as e:
            result = TaskResult(
                task_id=task_id,
                profile_name=task_type,
                model_used=model,
                hardware_used=hardware.value,
                status=TaskStatus.FAILED,
                error=str(e),
                duration_sec=round(time.time() - start_time, 2),
            )
            self._history.append(result)
            yield {"event": "error", "data": str(e)}

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------
    def get_history(self, limit: int = 20) -> list[dict]:
        """Get recent task history."""
        return [r.to_dict() for r in self._history[-limit:]]

    def get_status(self) -> dict:
        """Current router status."""
        return {
            "gpu_model_loaded": self._gpu_model,
            "profiles_count": len(self.profiles),
            "tasks_completed": len(self._history),
            "queue_length": len(self._queue),
        }


# Module-level singleton
router = TaskRouter()
