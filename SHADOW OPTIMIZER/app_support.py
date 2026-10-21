"""Compatibilidade, inicialização opcional e registro privado de erros."""

import logging
import os
import platform
import re
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


APP_NAME = "Shadow"
_logger = logging.getLogger("shadow")
_logger.setLevel(logging.ERROR)
_logger.propagate = False


def data_directory():
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / APP_NAME
    root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "shadow"


def error_log_path():
    return data_directory() / "logs" / "shadow-errors.log"


def _redact(text):
    value = str(text)
    home = str(Path.home())
    if home:
        value = value.replace(home, "~")
    return value[:12000]


def _get_logger():
    if not _logger.handlers:
        path = error_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            _logger.addHandler(handler)
        except OSError:
            return None
    return _logger


def log_error(message, details=""):
    logger = _get_logger()
    if logger:
        logger.error("%s%s", _redact(message), f"\n{_redact(details)}" if details else "")


def install_exception_logging():
    """Registra exceções não tratadas em arquivo local com rotação limitada."""
    previous_hook = sys.excepthook

    def exception_hook(error_type, error, tb):
        if error_type is not KeyboardInterrupt:
            log_error("Exceção não tratada", "".join(traceback.format_exception(error_type, error, tb)))
        previous_hook(error_type, error, tb)

    sys.excepthook = exception_hook
    if hasattr(threading, "excepthook"):
        previous_thread_hook = threading.excepthook

        def thread_exception_hook(args):
            log_error("Exceção não tratada em segundo plano", "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
            previous_thread_hook(args)

        threading.excepthook = thread_exception_hook


def read_error_log():
    path = error_log_path()
    try:
        contents = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        contents = ""
    except OSError:
        return {"success": False, "message": "Não foi possível ler o arquivo de log.", "contents": ""}
    return {
        "success": True,
        "path": str(path),
        "contents": contents[-100_000:],
        "truncated": len(contents) > 100_000,
    }


def error_log_overview():
    path = error_log_path()
    try:
        size = path.stat().st_size if path.exists() else 0
        supported = True
    except OSError:
        size = 0
        supported = False
    return {"path": str(path), "size_bytes": size, "supported": supported}


def clear_error_log():
    path = error_log_path()
    try:
        # Close the active handler first so the file can be removed on Windows too.
        for handler in list(_logger.handlers):
            handler.close()
            _logger.removeHandler(handler)
        for old_log in path.parent.glob(f"{path.name}*"):
            old_log.unlink(missing_ok=True)
        return {"success": True, "message": "O log de erros local foi limpo."}
    except OSError:
        return {"success": False, "message": "Não foi possível limpar o log de erros."}


def _windows_build(system_info):
    version = str(system_info.get("version", ""))
    match = re.search(r"(?:^|\.)(\d{4,})$", version)
    if match:
        return int(match.group(1))
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            value, _ = winreg.QueryValueEx(key, "CurrentBuildNumber")
        return int(value)
    except (ImportError, OSError, ValueError):
        return 0


def compatibility_overview(system_info=None, gpu_monitoring=False, temperatures=False):
    """Resume a plataforma e indica claramente recursos compatíveis ou limitados."""
    info = system_info or {
        "name": platform.system(),
        "display_name": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "is_windows": os.name == "nt",
    }
    is_windows = os.name == "nt" or bool(info.get("is_windows"))
    build = _windows_build(info) if is_windows else None
    if is_windows:
        release = "Windows 11" if build and build >= 22000 else "Windows 10" if build and build >= 10240 else info.get("display_name", "Windows")
        supported = bool(build and build >= 10240)
        mode = "compatível" if supported else "versão do Windows não confirmada"
    elif info.get("name") == "Linux" or platform.system() == "Linux":
        release = info.get("display_name") or "Linux"
        supported = False
        mode = "desenvolvimento"
    else:
        release = info.get("display_name") or info.get("name") or "Sistema desconhecido"
        supported = False
        mode = "não validado"

    windows_message = "Disponível no Shadow para Windows 10/11." if is_windows else "Indisponível neste sistema; o recurso depende de APIs do Windows."
    capabilities = [
        {"name": "CPU, RAM e processos", "status": "available", "details": "Leitura via psutil; pode variar conforme permissões do sistema."},
        {"name": "Discos e espaço livre", "status": "available", "details": "Unidades acessíveis ao usuário atual."},
        {"name": "Gaming Hub", "status": "limited", "details": "Detecta bibliotecas conhecidas; jogos e lojas não compatíveis podem não aparecer."},
        {"name": "Performance Lab", "status": "limited", "details": "CPU/RAM e importação de CSV; uso de GPU indisponível nesta leitura." if not gpu_monitoring else "CPU/RAM e uso de GPU disponíveis. FPS vem do CSV importado; sensores têm intervalo próprio."},
        {"name": "Temperaturas", "status": "available" if temperatures else "unavailable", "details": "Sensores de leitura disponíveis; fonte indicada no painel." if temperatures else "Nenhum sensor acessível. Windows: NVIDIA ou LibreHardwareMonitor com WMI; Linux: sensores do sistema."},
        {"name": "Limpeza de temporários", "status": "available" if is_windows else "unavailable", "details": windows_message},
        {"name": "Aplicativos na inicialização", "status": "available" if is_windows else "unavailable", "details": "Consulta e alteração limitadas à conta atual do Windows." if is_windows else windows_message},
        {"name": "Planos de energia", "status": "available" if is_windows else "unavailable", "details": windows_message},
        {"name": "Network Lab", "status": "available", "details": "Adaptadores e teste de conectividade; ping depende do destino e da rota."},
    ]
    return {
        "system_name": release,
        "raw_name": info.get("name", platform.system()),
        "release": info.get("release", platform.release()),
        "build": build,
        "mode": mode,
        "supported": supported,
        "target": "Windows 10 e Windows 11",
        "is_windows": is_windows,
        "is_frozen": bool(getattr(sys, "frozen", False)),
        "capabilities": capabilities,
    }


def launch_at_login_overview():
    """A inicialização automática só é oferecida no executável final para Windows."""
    supported = os.name == "nt" and bool(getattr(sys, "frozen", False))
    if not supported:
        return {
            "supported": False,
            "enabled": False,
            "message": "Disponível no Shadow.exe para Windows; fica indisponível no Linux de desenvolvimento.",
        }
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
            command, _ = winreg.QueryValueEx(key, APP_NAME)
        enabled = os.path.normcase(str(command).strip().strip('"')) == os.path.normcase(str(Path(sys.executable).resolve()))
        return {"supported": True, "enabled": enabled, "message": "O Shadow iniciará junto com sua conta do Windows." if enabled else "O Shadow não inicia com o Windows."}
    except FileNotFoundError:
        return {"supported": True, "enabled": False, "message": "O Shadow não inicia com o Windows."}
    except OSError:
        return {"supported": True, "enabled": False, "message": "Não foi possível consultar a inicialização automática."}


def set_launch_at_login(enabled):
    """Define/remova somente o valor Run chamado Shadow, no usuário atual."""
    current = launch_at_login_overview()
    if not current["supported"]:
        return {"success": False, "message": current["message"]}
    command = f'"{Path(sys.executable).resolve()}"'
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            try:
                existing, _ = winreg.QueryValueEx(key, APP_NAME)
            except FileNotFoundError:
                existing = None
            if enabled:
                if existing and os.path.normcase(str(existing).strip().strip('"')) != os.path.normcase(str(Path(sys.executable).resolve())):
                    return {"success": False, "message": "Já existe outra entrada chamada Shadow. Ela foi preservada."}
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
                return {"success": True, "message": "O Shadow iniciará quando você entrar na sua conta do Windows."}
            if existing is None:
                return {"success": True, "message": "A inicialização automática já estava desativada."}
            if os.path.normcase(str(existing).strip().strip('"')) != os.path.normcase(str(Path(sys.executable).resolve())):
                return {"success": False, "message": "A entrada Shadow foi alterada por outro programa e foi preservada."}
            winreg.DeleteValue(key, APP_NAME)
            return {"success": True, "message": "O Shadow não iniciará mais com o Windows."}
    except OSError:
        return {"success": False, "message": "O Windows não permitiu atualizar a inicialização automática."}
