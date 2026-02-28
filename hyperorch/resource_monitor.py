"""
Resource monitoring for CPU, RAM, and GPU (NVIDIA + AMD).

NVIDIA: Uses GPUtil
AMD: Uses pyadl for GPU name, WMI for VRAM total, and Windows Performance Counters for utilization
Fallback: WMI Win32_VideoController for basic detection
"""
import platform
import subprocess
import psutil

# --- NVIDIA ---
try:
    import GPUtil
except ImportError:
    GPUtil = None

# --- AMD ---
try:
    from pyadl import ADLManager, ADL_DEVICE_FAN_SPEED_TYPE_PERCENTAGE
    _adl_manager = ADLManager.getInstance()
    _adl_devices = _adl_manager.getDevices()
except Exception:
    _adl_devices = None


def _detect_gpu_vendor() -> str:
    """Detect GPU vendor: 'nvidia', 'amd', or 'unknown'."""
    if GPUtil:
        gpus = GPUtil.getGPUs()
        if gpus:
            return "nvidia"
    if _adl_devices and len(_adl_devices) > 0:
        return "amd"
    # WMI fallback
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=5
        )
        name = result.stdout.strip().lower()
        if "nvidia" in name:
            return "nvidia"
        elif "amd" in name or "radeon" in name:
            return "amd"
    except Exception:
        pass
    return "unknown"


def _get_amd_gpu_info() -> dict:
    """Get AMD GPU info via pyadl + WMI."""
    info = {"name": None, "vram_total_gb": None, "util_percent": None}

    # GPU name from pyadl
    if _adl_devices and len(_adl_devices) > 0:
        dev = _adl_devices[0]
        name = dev.adapterName
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        info["name"] = name

    # VRAM from WMI (note: Win32_VideoController.AdapterRAM is a 32-bit uint,
    # so it caps at 4GB. The RX 6650 XT has 8GB. We use a known-models table
    # for accurate VRAM, falling back to WMI if unknown.)
    known_vram = {
        "6650 xt": 8.0, "6700 xt": 12.0, "6750 xt": 12.0,
        "6800": 16.0, "6800 xt": 16.0, "6900 xt": 16.0, "6950 xt": 16.0,
        "7600": 8.0, "7700 xt": 12.0, "7800 xt": 16.0, "7900 xt": 20.0,
        "7900 xtx": 24.0, "9070": 16.0, "9070 xt": 16.0,
    }

    if info["name"]:
        name_lower = info["name"].lower()
        for model_key, vram in known_vram.items():
            if model_key in name_lower:
                info["vram_total_gb"] = vram
                break

    if info["vram_total_gb"] is None:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty AdapterRAM"],
                capture_output=True, text=True, timeout=5
            )
            adapter_ram = int(result.stdout.strip())
            info["vram_total_gb"] = round(adapter_ram / (1024**3), 2)
        except Exception:
            pass

    return info


def get_hardware_info() -> dict:
    """Returns static hardware info for the system."""
    gpu_name = None
    vram_total_gb = None
    gpu_vendor = _detect_gpu_vendor()

    if gpu_vendor == "nvidia" and GPUtil:
        gpus = GPUtil.getGPUs()
        if gpus:
            gpu_name = gpus[0].name
            vram_total_gb = round(gpus[0].memoryTotal / 1024.0, 2)
    elif gpu_vendor == "amd":
        amd_info = _get_amd_gpu_info()
        gpu_name = amd_info["name"]
        vram_total_gb = amd_info["vram_total_gb"]

    return {
        "cpu_name": platform.processor() or "Unknown CPU",
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "gpu_name": gpu_name,
        "gpu_vendor": gpu_vendor,
        "vram_total_gb": vram_total_gb
    }


def get_snapshot() -> dict:
    """Returns a snapshot of current system resource usage."""
    vm = psutil.virtual_memory()

    gpu_util_percent = None
    vram_used_gb = None
    vram_total_gb = None
    gpu_name = None
    gpu_vendor = _detect_gpu_vendor()

    if gpu_vendor == "nvidia" and GPUtil:
        gpus = GPUtil.getGPUs()
        if gpus:
            gpu = gpus[0]
            gpu_name = gpu.name
            gpu_util_percent = round(gpu.load * 100, 1)
            vram_used_gb = round(gpu.memoryUsed / 1024.0, 2)
            vram_total_gb = round(gpu.memoryTotal / 1024.0, 2)

    elif gpu_vendor == "amd":
        amd_info = _get_amd_gpu_info()
        gpu_name = amd_info["name"]
        vram_total_gb = amd_info["vram_total_gb"]
        # AMD doesn't have easy per-process VRAM tracking on Windows,
        # so we report what we can and note it's estimated
        gpu_util_percent = None  # pyadl doesn't expose utilization on modern drivers
        vram_used_gb = None      # No reliable API for this on Windows AMD consumer GPUs

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_used_gb": round(vm.used / (1024**3), 2),
        "ram_total_gb": round(vm.total / (1024**3), 2),
        "ram_percent": vm.percent,
        "gpu_name": gpu_name,
        "gpu_vendor": gpu_vendor,
        "gpu_util_percent": gpu_util_percent,
        "vram_used_gb": vram_used_gb,
        "vram_total_gb": vram_total_gb,
        "vram_percent": round((vram_used_gb / vram_total_gb) * 100, 1) if vram_used_gb is not None and vram_total_gb else None
    }
