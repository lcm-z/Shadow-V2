"""Ações opcionais do Shadow. Recursos do Windows ficam isolados neste módulo."""

import json
import os
import re
import subprocess
import tempfile
import time
import stat
import threading
from pathlib import Path

import psutil
from ui_settings import atomic_json

_startup_lock = threading.RLock()


TEMP_MIN_AGE_DAYS = 7
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PLAN_GUID_PATTERN = re.compile(r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})")


def disk_overview():
    """Lista unidades acessíveis sem tentar desmontar ou alterar volumes."""
    disks = []
    seen = set()
    for partition in psutil.disk_partitions(all=False):
        mountpoint = partition.mountpoint
        if mountpoint in seen:
            continue
        seen.add(mountpoint)
        try:
            usage = psutil.disk_usage(mountpoint)
        except (OSError, PermissionError):
            continue
        disks.append({
            "name": partition.device or mountpoint,
            "mountpoint": mountpoint,
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "used_percent": usage.percent,
        })
    return disks


def _safe_temp_root():
    """Só permite limpar a pasta TEMP dentro do perfil da pessoa (Windows)."""
    if os.name != "nt":
        return None
    try:
        root = Path(tempfile.gettempdir()).resolve()
        home = Path.home().resolve()
        common = os.path.commonpath([str(root), str(home)])
        if root == home or os.path.normcase(common) != os.path.normcase(str(home)):
            return None
        return root
    except (OSError, ValueError):
        return None


def _is_redirected(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _old_temp_files(root, older_than):
    for folder, directories, files in os.walk(root, topdown=True, followlinks=False):
        safe_directories = []
        for name in directories:
            try:
                if not _is_redirected(Path(folder) / name):
                    safe_directories.append(name)
            except OSError:
                pass
        directories[:] = safe_directories
        for name in files:
            path = Path(folder) / name
            try:
                if _is_redirected(path) or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                    continue
                if path.stat().st_mtime <= older_than:
                    yield path
            except OSError:
                continue


def preview_temp_cleanup():
    """Pré-visualiza arquivos temporários do usuário com pelo menos 7 dias."""
    root = _safe_temp_root()
    if root is None:
        return {
            "supported": False,
            "message": "A limpeza está disponível no Windows e limita-se à pasta TEMP da sua conta.",
            "file_count": 0,
            "bytes": 0,
            "files": [],
        }

    cutoff = time.time() - TEMP_MIN_AGE_DAYS * 24 * 60 * 60
    file_count = 0
    total_bytes = 0
    files = []
    for path in _old_temp_files(root, cutoff):
        try:
            size = path.stat().st_size
            file_count += 1
            total_bytes += size
            files.append({"path": str(path.relative_to(root)), "bytes": size})
        except OSError:
            continue
    files.sort(key=lambda item: item["path"].casefold())
    return {
        "supported": True,
        "root": str(root),
        "file_count": file_count,
        "bytes": total_bytes,
        "files": files,
        "minimum_age_days": TEMP_MIN_AGE_DAYS,
    }


def clean_temp_files(selected_paths):
    """Remove somente arquivos selecionados, antigos e contidos na TEMP da conta."""
    root = _safe_temp_root()
    if root is None:
        return {"success": False, "message": "A limpeza está disponível apenas na pasta TEMP da conta no Windows."}
    if not isinstance(selected_paths, list) or len(selected_paths) > 10000:
        return {"success": False, "message": "A seleção de arquivos é inválida."}
    selected = {value for value in selected_paths if isinstance(value, str)}
    if not selected:
        return {"success": False, "message": "Selecione pelo menos um arquivo para limpar."}

    cutoff = time.time() - TEMP_MIN_AGE_DAYS * 24 * 60 * 60
    removed = 0
    freed_bytes = 0
    skipped = 0
    for path in _old_temp_files(root, cutoff):
        try:
            relative_path = str(path.relative_to(root))
            if relative_path not in selected:
                continue
            if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
                skipped += 1
                continue
            if _is_redirected(path) or not path.resolve().is_relative_to(root.resolve()):
                skipped += 1
                continue
            size = path.stat().st_size
            path.unlink()
            removed += 1
            freed_bytes += size
        except OSError:
            skipped += 1
    return {
        "success": True,
        "removed_count": removed,
        "freed_bytes": freed_bytes,
        "skipped_count": skipped,
        "message": f"Limpeza concluída: {removed} arquivo(s) removido(s); itens em uso ou sem permissão foram ignorados.",
    }


def _startup_backup_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "Shadow" / "disabled_startup.json"


def _read_startup_backup():
    path = _startup_backup_path()
    try:
        backup = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(backup, dict):
        return {}
    return {
        name: saved
        for name, saved in backup.items()
        if isinstance(name, str)
        and isinstance(saved, dict)
        and isinstance(saved.get("command"), str)
        and isinstance(saved.get("type"), int)
    }


def _write_startup_backup(backup):
    atomic_json(_startup_backup_path(), backup)


def startup_overview():
    """Lista apenas a chave Run da conta atual, sem incluir itens de todos os usuários."""
    if os.name != "nt":
        return {"supported": False, "message": "A lista de inicialização está disponível na versão para Windows.", "items": []}

    import winreg

    backup = _read_startup_backup()
    items = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            index = 0
            while True:
                try:
                    name, command, value_type = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    continue
                items.append({"name": name, "command": command, "enabled": True, "source": "Run"})
    except FileNotFoundError:
        pass

    for name, saved in backup.items():
        items.append({"name": name, "command": saved.get("command", ""), "enabled": False, "source": "Run"})
    items.sort(key=lambda item: (not item["enabled"], item["name"].casefold()))
    return {
        "supported": True,
        "scope": "Somente inicialização da sua conta (HKCU Run).",
        "items": items,
    }


def set_startup_enabled(name, enabled):
    with _startup_lock:
        return _set_startup_enabled_locked(name, enabled)


def _set_startup_enabled_locked(name, enabled):
    """Desativa/restaura um valor Run da conta atual com cópia reversível local."""
    if os.name != "nt":
        return {"success": False, "message": "Esta opção está disponível na versão para Windows."}
    if not isinstance(name, str) or not name or len(name) > 255:
        return {"success": False, "message": "Nome de inicialização inválido."}

    import winreg

    backup = _read_startup_backup()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            if enabled:
                saved = backup.get(name)
                if not saved:
                    return {"success": False, "message": "Não há cópia para restaurar este item."}
                try:
                    winreg.QueryValueEx(key, name)
                    return {"success": False, "message": "Já existe um item com esse nome. A cópia foi preservada."}
                except FileNotFoundError:
                    pass
                winreg.SetValueEx(key, name, 0, saved["type"], saved["command"])
                del backup[name]
                try:
                    _write_startup_backup(backup)
                except OSError:
                    winreg.DeleteValue(key, name)
                    raise
                return {"success": True, "message": f"{name} será iniciado novamente quando você entrar no Windows."}

            command, value_type = winreg.QueryValueEx(key, name)
            if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                return {"success": False, "message": "Esse tipo de item não pode ser guardado com segurança."}
            backup[name] = {"command": command, "type": value_type}
            _write_startup_backup(backup)
            try:
                winreg.DeleteValue(key, name)
            except OSError:
                backup.pop(name, None)
                _write_startup_backup(backup)
                raise
            return {"success": True, "message": f"{name} foi removido da inicialização. Você pode reativá-lo pelo Shadow."}
    except FileNotFoundError:
        return {"success": False, "message": "O item mudou desde a leitura. Atualize a lista."}
    except OSError as error:
        return {"success": False, "message": f"O Windows não permitiu alterar este item: {error}"}


def _power_plan_description(guid, name):
    normalized = guid.casefold()
    if normalized == "a1841308-3541-4fab-bc81-f71556f20b4a":
        return "Economiza energia; pode reduzir o desempenho disponível."
    if normalized == "381b4222-f694-41f0-9685-ff5bb260df2e":
        return "Equilibra consumo e desempenho para uso geral."
    if normalized == "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c":
        return "Prioriza desempenho e pode aumentar consumo, calor e ruído. Não garante mais FPS."
    return f"Plano do Windows: {name}. O efeito depende das configurações do computador."


def power_plan_overview():
    """Lê os planos do Windows via powercfg; não modifica o plano ativo."""
    if os.name != "nt":
        return {"supported": False, "message": "Os planos de energia do Windows aparecem na versão para Windows.", "plans": []}
    try:
        result = subprocess.run(["powercfg", "/list"], capture_output=True, text=True, timeout=8)
        if result.returncode != 0:
            return {"supported": False, "message": "O Windows não conseguiu listar os planos de energia.", "plans": []}
        plans = []
        for line in result.stdout.splitlines():
            match = PLAN_GUID_PATTERN.search(line)
            if not match:
                continue
            guid = match.group(1)
            remainder = line[match.end():]
            name_match = re.search(r"\((.*?)\)", remainder)
            name = name_match.group(1).strip() if name_match else "Plano do Windows"
            plans.append({
                "guid": guid,
                "name": name,
                "active": "*" in remainder,
                "description": _power_plan_description(guid, name),
            })
        return {"supported": True, "plans": plans}
    except (OSError, subprocess.TimeoutExpired):
        return {"supported": False, "message": "Não foi possível consultar os planos de energia.", "plans": []}


def activate_power_plan(guid):
    """Ativa um plano que ainda aparece na lista atual do próprio Windows."""
    if os.name != "nt":
        return {"success": False, "message": "Esta opção está disponível na versão para Windows."}
    if not isinstance(guid, str) or not PLAN_GUID_PATTERN.fullmatch(guid):
        return {"success": False, "message": "Plano inválido."}
    overview = power_plan_overview()
    if not overview["supported"] or not any(plan["guid"].casefold() == guid.casefold() for plan in overview["plans"]):
        return {"success": False, "message": "Esse plano não está disponível neste computador."}
    try:
        result = subprocess.run(["powercfg", "/setactive", guid], capture_output=True, text=True, timeout=8)
        if result.returncode != 0:
            return {"success": False, "message": "O Windows não permitiu ativar esse plano."}
        return {"success": True, "message": "Plano de energia atualizado. Você pode alterá-lo novamente quando quiser."}
    except (OSError, subprocess.TimeoutExpired):
        return {"success": False, "message": "Não foi possível alterar o plano de energia."}


def live_system_sample(process_cache, previous_disk_io=None, previous_time=None):
    """Retorna uma amostra para monitoramento contínuo; não altera o sistema."""
    cpu = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    cpu_processes = []
    ram_processes = []
    active_pids = set()

    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            pid = process.info["pid"]
            created = process.create_time()
            cached = process_cache.get(pid)
            if cached is None or cached[0] != created:
                process.cpu_percent(interval=None)
                process_cache[pid] = (created, process)
                process_cpu = 0.0
            else:
                process_cpu = cached[1].cpu_percent(interval=None)
            active_pids.add(pid)
            name = process.info["name"] or "Desconhecido"
            memory_info = process.info["memory_info"]
            if memory_info:
                ram_processes.append({"pid": pid, "name": name, "ram_mb": memory_info.rss / (1024 ** 2)})
            cpu_processes.append({"pid": pid, "name": name, "cpu_percent": process_cpu})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    for pid in set(process_cache) - active_pids:
        process_cache.pop(pid, None)

    disk = psutil.disk_io_counters()
    timestamp = time.monotonic()
    read_mb_s = write_mb_s = 0.0
    if disk and previous_disk_io and previous_time:
        elapsed = max(timestamp - previous_time, 0.01)
        read_mb_s = max(0, disk.read_bytes - previous_disk_io[0]) / (1024 ** 2) / elapsed
        write_mb_s = max(0, disk.write_bytes - previous_disk_io[1]) / (1024 ** 2) / elapsed

    cpu_processes.sort(key=lambda item: item["cpu_percent"], reverse=True)
    ram_processes.sort(key=lambda item: item["ram_mb"], reverse=True)
    return {
        "cpu_percent": cpu,
        "ram_percent": memory.percent,
        "available_gb": memory.available / (1024 ** 3),
        "top_cpu_processes": cpu_processes[:5],
        "top_ram_processes": ram_processes[:5],
        "disk_read_mb_s": read_mb_s,
        "disk_write_mb_s": write_mb_s,
        "disk_io": (disk.read_bytes, disk.write_bytes) if disk else None,
        "timestamp": timestamp,
    }
