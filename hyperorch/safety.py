import os
import click
from hyperorch.resource_monitor import get_snapshot

def estimate_model_memory_gb(model_info: dict) -> float:
    """Estimate memory needed by a model."""
    backend = model_info.get("backend")
    
    if backend == "llamacpp" and "size_gb" in model_info:
        # Give ~1.2x overhead for context + inference
        return model_info["size_gb"] * 1.2
        
    name = model_info.get("name", "").lower()
    
    if "70b" in name or "72b" in name:
        return 40.0
    elif "32b" in name or "34b" in name:
        return 20.0
    elif "13b" in name or "14b" in name:
        return 8.0
    elif "7b" in name or "8b" in name:
        return 4.5
    elif "3b" in name or "1b" in name:
        return 2.0
        
    return 4.0  # Default safe guess


def check_memory(model_info: dict, threshold_pct: int = 85) -> dict:
    """Check if we have enough memory to run this model safely."""
    snap = get_snapshot()
    est_gb = estimate_model_memory_gb(model_info)
    
    available_gb = snap["ram_total_gb"] - snap["ram_used_gb"]
    
    safe = True
    warning = None
    
    # Check if this takes us over threshold%
    projected_used_gb = snap["ram_used_gb"] + est_gb
    projected_pct = (projected_used_gb / snap["ram_total_gb"]) * 100
    
    if projected_pct > threshold_pct:
        safe = False
        warning = f"Model needs ~{est_gb:.1f}GB. This would push system RAM to {projected_pct:.1f}%, exceeding the {threshold_pct}% safety threshold."
        
    if est_gb > available_gb:
        safe = False
        warning = f"Model needs ~{est_gb:.1f}GB but only {available_gb:.1f}GB is available! OOM likely."
        
    return {
        "safe": safe,
        "warning": warning,
        "estimated_gb": est_gb,
        "available_gb": available_gb
    }


def confirm_overwrite(path: str) -> bool:
    """Ask user to confirm before overwriting files."""
    if not os.path.exists(path):
        return True
        
    return click.confirm(f"File {path} already exists. Overwrite?", default=False)
