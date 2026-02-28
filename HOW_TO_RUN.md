# How to Run HyperOrch

## Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com) installed with at least one model

## Quick Start

### Step 1 — Start Ollama
```powershell
ollama serve
```

### Step 2 — Start HyperOrch (new terminal)
```powershell
cd c:\Projects\HyperOrch
python -m hyperorch.cli serve --port 8001
```

### Step 3 — Open browser
```
http://localhost:8001
```

Select a task type, type your prompt, hit **Send Task**.

---

## CLI-Only Mode (no browser needed)

```powershell
python -m hyperorch.cli detect              # See your models
python -m hyperorch.cli status              # Check CPU/RAM/GPU
python -m hyperorch.cli launch llama3:latest # Launch a model
python -m hyperorch.cli stop                # Stop it
python -m hyperorch.cli context save        # Save state
python -m hyperorch.cli context load        # Load state
```

## Task Profiles

| Task Type | Model | Hardware | Use Case |
|-----------|-------|----------|----------|
| coding | qwen2.5-coder:7b | GPU | Code generation |
| chat | llama3:latest | GPU | Conversation |
| reasoning | hermes3:8b | GPU | Analysis & thinking |
| summarize | dolphin-mistral | AUTO | Background summaries |
| embed | nomic-embed-text | CPU | Embeddings for RAG |
| background | dolphin-phi | CPU | Batch processing |
