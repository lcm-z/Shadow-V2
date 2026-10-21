"""Preferências locais de interface, independentes das configurações do Windows."""

import json
import os
import tempfile
import threading
from pathlib import Path

from app_support import data_directory

DEFAULTS = {"lightweight": False, "interval_seconds": 1, "effects": "full", "show_intro": True}
_lock = threading.RLock()


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError("Configurações inválidas.")
    result = {key: value.get(key, default) for key, default in DEFAULTS.items()}
    if type(result["lightweight"]) is not bool or type(result["show_intro"]) is not bool:
        raise ValueError("As opções de modo leve e apresentação devem ser ligadas ou desligadas.")
    if type(result["interval_seconds"]) is not int or result["interval_seconds"] not in (1, 3, 5):
        raise ValueError("Escolha um intervalo de 1, 3 ou 5 segundos.")
    if result["effects"] not in ("full", "reduced", "off"):
        raise ValueError("Escolha uma intensidade de efeitos válida.")
    return result


def settings_path():
    return data_directory() / "settings.json"


def load_settings(path=None):
    with _lock:
        try:
            return validate_settings(json.loads(Path(path or settings_path()).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return dict(DEFAULTS)


def atomic_json(path, data):
    """Escreve um arquivo completo antes de substituir a versão anterior."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".shadow-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_settings(value, path=None):
    try:
        result = validate_settings(value)
        with _lock:
            atomic_json(path or settings_path(), result)
        return {"success": True, "settings": result, "message": "Preferências salvas neste computador."}
    except (OSError, ValueError, TypeError) as error:
        return {"success": False, "message": str(error)}
