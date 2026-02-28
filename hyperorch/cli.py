import click
import json
import uvicorn
from .model_manager import detect_all_models, model_process
from .orchestrator import decide_execution_config
from .safety import check_memory, confirm_overwrite
from .resource_monitor import get_snapshot
from .context_store import save_context, load_context, get_default_context

@click.group()
def main():
    """HyperOrch — AI Orchestration System"""
    pass

@main.command("detect")
def detect():
    """Scan for Ollama and GGUF models."""
    models = detect_all_models()
    click.echo(f"Detected {len(models)} models:")
    for m in models:
        click.echo(f" - {m.get('name')} [{m.get('backend')}]")

@main.command("launch")
@click.argument("model")
@click.option("--backend", help="Backend type (ollama or llamacpp)")
@click.option("--gpu-layers", type=int, help="Number of layers to offload to GPU")
@click.option("--ctx-size", type=int, default=2048, help="Context window size")
@click.option("--quant", help="Quantization level")
def launch(model, backend, gpu_layers, ctx_size, quant):
    """Launch a model."""
    models = detect_all_models()
    target = next((m for m in models if m.get("name") == model), None)
    
    if not target:
        # User specified a model name directly, create a minimal dict
        target = {"name": model, "backend": backend or "ollama"}
        
    preferences = {"ctx_size": ctx_size}
    if gpu_layers is not None: preferences["gpu_layers"] = gpu_layers
    if quant: preferences["quantization"] = quant
    
    config = decide_execution_config(target, preferences)
    
    safety = check_memory(config)
    if not safety["safe"]:
        click.echo(click.style("WARNING: Memory unsafe!", fg="yellow"))
        click.echo(safety["warning"])
        if not click.confirm("Proceed anyway?"):
            return
            
    click.echo(f"Launching {model} with config: {config}")
    if model_process.launch(config):
        click.echo("Started successfully.")
    else:
        click.echo("Failed to launch.", err=True)

@main.command("stop")
def stop():
    """Stop the running model."""
    model_process.stop()
    click.echo("Model stopped.")

@main.command("status")
def status():
    """Print system and model status."""
    snap = get_snapshot()
    click.echo("--- System ---")
    click.echo(f"CPU: {snap.get('cpu_percent')}%")
    click.echo(f"RAM: {snap.get('ram_used_gb')}GB / {snap.get('ram_total_gb')}GB")
    if snap.get('gpu_name'):
        click.echo(f"GPU: {snap.get('gpu_name')} ({snap.get('gpu_util_percent')}% util, {snap.get('vram_used_gb')}GB / {snap.get('vram_total_gb')}GB VRAM)")
    else:
        click.echo("GPU: None")
        
    click.echo("\n--- Model ---")
    info = model_process.get_info()
    if info:
        click.echo(json.dumps(info, indent=2))
    else:
        click.echo("No model running.")

@main.group("context")
def context():
    """Manage context.json state."""
    pass

@context.command("save")
@click.argument("file", default="context.json", required=False)
def context_save(file):
    """Save context state to file."""
    if confirm_overwrite(file):
        data = load_context("context.json")  # Read latest
        save_context(data, file)
        click.echo(f"Context saved to {file}")

@context.command("load")
@click.argument("file", default="context.json", required=False)
def context_load(file):
    """Load context state from file."""
    data = load_context(file)
    click.echo(json.dumps(data, indent=2))

@main.command("serve")
@click.option("--port", default=8000, help="Port to run server on")
def serve(port):
    """Start HyperOrch Web Server."""
    click.echo(f"Starting HyperOrch Web UI on port {port}...")
    uvicorn.run("hyperorch.server:app", host="0.0.0.0", port=port, log_level="info")

if __name__ == "__main__":
    main()