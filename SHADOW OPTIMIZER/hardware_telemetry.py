"""Sensores somente de leitura. Ausência de sensor é None, nunca uma leitura zero."""

import csv
import io
import json
import math
import os
import re
import subprocess
import threading
import time
from copy import deepcopy
from pathlib import Path

import psutil
from performance_lab import find_nvidia_smi


def number(value, minimum=0, maximum=None):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= minimum and (maximum is None or result <= maximum) else None
    except (TypeError, ValueError):
        return None


def _run(args, timeout):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, check=False,
                          **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))


def nvidia_sensors():
    executable = find_nvidia_smi()
    if not executable:
        return []
    result = _run([executable, "--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.used,memory.total",
                   "--format=csv,noheader,nounits"], 2)
    if result.returncode:
        return []
    gpus = []
    for row in csv.reader(io.StringIO(result.stdout), skipinitialspace=True):
        if len(row) != 6:
            continue
        gpus.append({"id": f"nvidia:{row[0]}", "name": row[1].strip(), "source": "nvidia-smi",
                     "usage_percent": number(row[2], maximum=100), "temperature_c": number(row[3], maximum=150),
                     "memory_used_mb": number(row[4]), "memory_total_mb": number(row[5])})
    return gpus


def linux_sensors(drm_root=Path("/sys/class/drm")):
    gpus, temperatures = [], []
    for card in sorted(drm_root.glob("card[0-9]*")):
        if not re.fullmatch(r"card\d+", card.name):
            continue
        device = card / "device"
        def read(name, scale=1):
            try:
                value = number((device / name).read_text().strip())
                return value / scale if value is not None else None
            except OSError:
                return None
        usage = read("gpu_busy_percent")
        if usage is None or usage > 100:
            continue
        try:
            driver = (device / "driver").resolve().name
        except OSError:
            driver = "GPU"
        gpus.append({"id": card.name, "name": f"{driver} · {card.name}", "source": "Linux sysfs",
                     "usage_percent": usage, "temperature_c": None,
                     "memory_used_mb": read("mem_info_vram_used", 1024**2),
                     "memory_total_mb": read("mem_info_vram_total", 1024**2)})
    read_temperatures = getattr(psutil, "sensors_temperatures", None)
    if read_temperatures:
        for chip, entries in read_temperatures().items():
            for index, entry in enumerate(entries):
                value = number(entry.current, minimum=-20, maximum=150)
                if value is not None:
                    temperatures.append({"name": f"{chip} · {entry.label or index + 1}", "temperature_c": value,
                                         "source": "Sensores do Linux"})
    return gpus, temperatures


def parse_lhm(payload):
    """Converte sensores WMI do LibreHardwareMonitor já aberto pelo usuário."""
    rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    gpus, temperatures = {}, []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parent = str(row.get("Parent", ""))
        name = str(row.get("Name", "Sensor"))
        kind = row.get("SensorType")
        if kind == "Temperature":
            value = number(row.get("Value"), minimum=-20, maximum=150)
            if value is not None:
                temperatures.append({"name": f"{parent} · {name}", "temperature_c": value, "source": "LibreHardwareMonitor"})
        if not parent.startswith(("/gpu-nvidia/", "/gpu-amd/", "/gpu-intel/")):
            continue
        gpu = gpus.setdefault(parent, {"id": parent, "name": parent.strip("/"), "source": "LibreHardwareMonitor",
                                      "usage_percent": None, "temperature_c": None,
                                      "memory_used_mb": None, "memory_total_mb": None})
        if kind == "Load" and name.casefold() in ("gpu core", "gpu 3d"):
            gpu["usage_percent"] = number(row.get("Value"), maximum=100)
        elif kind == "Temperature" and name.casefold() == "gpu core":
            gpu["temperature_c"] = number(row.get("Value"), maximum=150)
    return list(gpus.values()), temperatures


def windows_sensors():
    # Consulta opcional: não instala monitor/driver e não altera configurações WMI.
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
              "@(Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor | "
              "Select-Object Name,Parent,SensorType,Value) | ConvertTo-Json -Compress")
    result = _run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script], 3)
    return parse_lhm(json.loads(result.stdout)) if result.returncode == 0 and result.stdout.strip() else ([], [])


class Telemetry:
    """Cache compartilhado: a tela e o laboratório não multiplicam consultas externas."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cached = None
        self.updated = 0
        self.processes = {}

    def hardware(self, interval=5):
        with self.lock:
            if self.cached is not None and time.monotonic() - self.updated < interval:
                return deepcopy(self.cached)
            gpus, temperatures, notes = [], [], []
            try:
                gpus = nvidia_sensors()
            except (OSError, subprocess.TimeoutExpired):
                notes.append("A consulta NVIDIA não respondeu; seus valores estão indisponíveis.")
            try:
                other_gpus, temperatures = windows_sensors() if os.name == "nt" else linux_sensors()
                # Evita duplicar placas NVIDIA quando nvidia-smi respondeu.
                gpus.extend(g for g in other_gpus if not (gpus and g["id"].startswith("/gpu-nvidia/")))
            except (OSError, ValueError, subprocess.TimeoutExpired, AttributeError):
                notes.append("O provedor de sensores adicional não está disponível.")
            for gpu in gpus:
                if gpu.get("temperature_c") is not None and gpu["source"] == "nvidia-smi":
                    temperatures.append({"name": gpu["name"], "temperature_c": gpu["temperature_c"], "source": gpu["source"]})
            self.cached = {"gpus": gpus, "temperatures": temperatures, "notes": notes, "measured_at": time.time(),
                           "help": "No Windows: NVIDIA via nvidia-smi; AMD/Intel e sensores adicionais via LibreHardwareMonitor aberto com WMI disponível. No Linux: sensores expostos pelo sistema. Ausência de leitura não significa 0."}
            self.updated = time.monotonic()
            return deepcopy(self.cached)

    def own_usage(self):
        # Soma do processo Python e subprocessos, incluindo o renderizador web.
        with self.lock:
            parent = psutil.Process()
            try:
                members = [parent] + parent.children(recursive=True)
            except psutil.Error:
                members = [parent]
            cpu, memory, primed, active = 0.0, 0, False, set()
            for process in members:
                try:
                    key = (process.pid, process.create_time())
                    active.add(key)
                    previous = self.processes.get(key)
                    if previous is None:
                        process.cpu_percent(None)
                        self.processes[key] = process
                    else:
                        cpu += previous.cpu_percent(None)
                        primed = True
                    memory += process.memory_info().rss
                except psutil.Error:
                    continue
            self.processes = {key: value for key, value in self.processes.items() if key in active}
            return {"cpu_percent": round(cpu / (psutil.cpu_count() or 1), 1) if primed else None,
                    "ram_mb": round(memory / (1024**2), 1), "process_count": len(self.processes),
                    "note": "CPU normalizada pelo total de núcleos lógicos. RAM soma RSS e pode contar memória compartilhada mais de uma vez."}
