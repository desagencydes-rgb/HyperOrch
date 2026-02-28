from hyperorch.resource_monitor import get_snapshot

def decide_execution_config(model_info: dict, preferences: dict = None) -> dict:
    """Determine the optimal execution setup based on system resources.
    
    AMD Radeon GPUs use the Vulkan backend for GPU offloading.
    NVIDIA GPUs use CUDA. Both use the same -ngl (gpu_layers) flag in llama.cpp.
    Ollama v0.17.1+ handles GPU offload automatically for both vendors.
    """
    if preferences is None:
        preferences = {}
        
    config = {
        "name": model_info.get("name"),
        "backend": model_info.get("backend", "ollama"),
        "path": model_info.get("path"),
        "gpu_layers": 0,
        "ctx_size": preferences.get("ctx_size", 2048),
        "quantization": preferences.get("quantization", None),
        "gpu_vendor": "unknown",
        "warnings": []
    }
    
    # Estimate model size
    size_gb = model_info.get("size_gb")
    if size_gb is None:
        name = model_info.get("name", "").lower()
        if "70b" in name or "72b" in name:
            size_gb = 40.0
        elif "32b" in name or "34b" in name:
            size_gb = 20.0
        elif "13b" in name or "14b" in name:
            size_gb = 8.0
        elif "7b" in name or "8b" in name:
            size_gb = 4.5
        elif "3b" in name:
            size_gb = 2.0
        elif "1b" in name:
            size_gb = 1.0
        else:
            size_gb = 4.0
            
    snap = get_snapshot()
    gpu_vendor = snap.get("gpu_vendor", "unknown")
    config["gpu_vendor"] = gpu_vendor
    vram_gb = snap.get("vram_total_gb")
    ram_gb = snap.get("ram_total_gb", 16.0)
    ram_avail_gb = ram_gb - snap.get("ram_used_gb", 0)
    
    # --- GPU OFFLOAD LOGIC ---
    if gpu_vendor == "amd" and vram_gb:
        # AMD Radeon: Vulkan backend.
        # On AMD, we can't easily measure VRAM usage from Python,
        # so we use total VRAM and assume ~1GB is used by the OS/desktop.
        vram_avail_gb = vram_gb - 1.0  # Reserve ~1GB for desktop compositor
        
        if vram_avail_gb >= (size_gb * 1.1):
            config["gpu_layers"] = -1  # Full offload via Vulkan
        elif vram_avail_gb >= (size_gb * 0.4):
            # Proportional layers — Vulkan handles this identically to CUDA
            config["gpu_layers"] = int((vram_avail_gb / size_gb) * 35)
        else:
            config["gpu_layers"] = 0
            config["warnings"].append(
                f"AMD GPU ({snap.get('gpu_name')}) has {vram_gb}GB VRAM — "
                f"not enough for {size_gb:.1f}GB model. Running on CPU."
            )
            
        # For llama.cpp on AMD, note Vulkan backend requirement
        if config["backend"] == "llamacpp":
            config["backend"] = "llamacpp-vulkan"
            config["warnings"].append(
                "AMD GPU detected. Using Vulkan backend. "
                "Ensure you downloaded the llama.cpp Vulkan build from GitHub releases."
            )
            
    elif gpu_vendor == "nvidia" and vram_gb:
        vram_used = snap.get("vram_used_gb", 0)
        vram_avail_gb = vram_gb - vram_used
        
        if vram_avail_gb >= (size_gb * 1.2):
            config["gpu_layers"] = -1
        elif vram_avail_gb >= (size_gb * 0.5):
            config["gpu_layers"] = int((vram_avail_gb / size_gb) * 40)
        else:
            config["gpu_layers"] = 0
            config["warnings"].append("Not enough VRAM for significant GPU offload.")
    else:
        config["gpu_layers"] = 0
        if gpu_vendor == "amd" and not vram_gb:
            config["warnings"].append(
                "AMD GPU detected but VRAM size unknown. "
                "Try setting gpu_layers manually (e.g. --gpu-layers 20)."
            )
        
    # --- QUANTIZATION LOGIC ---
    if not config["quantization"]:
        total_mem = ram_avail_gb + (vram_gb or 0)
        if total_mem >= 32:
            config["quantization"] = "Q8_0"
        elif total_mem >= 16:
            config["quantization"] = "Q5_K_M"
        elif total_mem >= 8:
            config["quantization"] = "Q4_K_M"
        else:
            config["quantization"] = "Q3_K_S"
            config["warnings"].append("Very low total memory. Consider a smaller model.")
                
    # Memory safety
    total_avail = ram_avail_gb + (vram_gb - 1.0 if vram_gb else 0)
    if size_gb * 1.1 > total_avail:
        config["warnings"].append(
            f"Model needs ~{size_gb:.1f}GB but only ~{total_avail:.1f}GB total available. "
            "May fail to load or run very slowly."
        )
        
    # User overrides
    if "gpu_layers" in preferences:
        config["gpu_layers"] = preferences["gpu_layers"]
    if "backend" in preferences and preferences["backend"]:
        config["backend"] = preferences["backend"]
        
    return config


def recommend_fallback(model_info: dict) -> dict:
    """Recommend fallback remote execution if local resources are insufficient."""
    return {
        "action": "remote",
        "message": f"Local resources insufficient for {model_info.get('name')}. Recommend cloud offload.",
        "endpoint": None
    }
