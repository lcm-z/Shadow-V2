"""Histórico local de diagnósticos e ações do Shadow."""

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path


MAX_DIAGNOSTICS = 30
MAX_ACTIONS = 100
_history_lock = threading.RLock()


def history_path():
    """Usa uma pasta de dados do usuário, sem gravar no diretório do projeto."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        folder_name = "Shadow"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        folder_name = "shadow"
    return base / folder_name / "history.json"


def _read(path=None):
    try:
        data = json.loads(Path(path or history_path()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"diagnostics": [], "actions": []}
    if not isinstance(data, dict):
        return {"diagnostics": [], "actions": []}
    diagnostics = data.get("diagnostics", [])
    actions = data.get("actions", [])
    return {
        "diagnostics": diagnostics if isinstance(diagnostics, list) else [],
        "actions": actions if isinstance(actions, list) else [],
    }


def _write(data, path=None):
    destination = Path(path or history_path())
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, destination)


def record_diagnostic(report, path=None):
    """Guarda só um resumo; processos, PIDs e comandos não são persistidos."""
    system = report.get("system") or {}
    memory = report.get("memory") or {}
    monitoring = report.get("monitoring") or {}
    record = {
        "id": uuid.uuid4().hex,
        "timestamp": time.time(),
        "diagnosis": report.get("diagnosis") or {},
        "system": {
            "name": system.get("name", "Desconhecido"),
            "os": system.get("os", "Desconhecido"),
            "release": system.get("release", ""),
            "is_windows": bool(system.get("is_windows")),
        },
        "hardware": {
            "cpu_name": (report.get("hardware") or {}).get("cpu_name", "Não identificado"),
            "gpu_names": (report.get("hardware") or {}).get("gpu_names", [])[:4],
        },
        "cpu_percent": round(float(monitoring.get("average_cpu", report.get("cpu_percent", 0))), 1),
        "ram_percent": round(float(monitoring.get("average_ram", memory.get("used_percent", 0))), 1),
        "ram_total_gb": round(float(memory.get("total_gb", 0)), 2),
    }
    with _history_lock:
        data = _read(path)
        data["diagnostics"].append(record)
        data["diagnostics"] = data["diagnostics"][-MAX_DIAGNOSTICS:]
        _write(data, path)
    return record


def record_action(kind, title, details, undo_data=None, reversible=False, path=None):
    with _history_lock:
        data = _read(path)
        record = {
            "id": uuid.uuid4().hex,
            "timestamp": time.time(),
            "kind": kind,
            "title": title,
            "details": details,
            "reversible": bool(reversible and undo_data),
            "undo_data": undo_data if reversible else None,
            "undone": False,
        }
        data["actions"].append(record)
        data["actions"] = data["actions"][-MAX_ACTIONS:]
        _write(data, path)
    return record


def get_history(path=None):
    with _history_lock:
        data = _read(path)
    return {
        "diagnostics": sorted(data["diagnostics"], key=lambda item: item.get("timestamp", 0), reverse=True),
        "actions": sorted(data["actions"], key=lambda item: item.get("timestamp", 0), reverse=True),
        "storage": "Local neste usuário",
    }


def find_action(action_id, path=None):
    with _history_lock:
        for action in _read(path)["actions"]:
            if action.get("id") == action_id:
                return action
    return None


def mark_action_undone(action_id, path=None):
    with _history_lock:
        data = _read(path)
        for action in data["actions"]:
            if action.get("id") == action_id:
                action["undone"] = True
                action["undone_at"] = time.time()
                _write(data, path)
                return True
    return False
