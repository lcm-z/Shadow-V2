"""Detecção limitada de jogos e perfis locais do Gaming Hub do Shadow."""

import json
import os
import platform
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PROFILE_OPTIONS = {"balanced", "performance", "quality"}
IGNORED_GAME_NAMES = {
    "steamworks common redistributables",
    "proton easyanticheat runtime",
    "proton battleye runtime",
}


def _steam_roots():
    """Retorna apenas locais comuns do Steam, sem varrer o disco inteiro."""
    home = Path.home()
    candidates = []
    if os.name == "nt":
        for variable in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "Steam")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Steam")
    else:
        candidates.extend([
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        ])

    roots = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in seen and (resolved / "steamapps").is_dir():
            roots.append(resolved)
            seen.add(resolved)
    return roots


def _steam_library_paths(root):
    libraries = [root]
    manifest = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries

    # Aceita formato legado e atual do libraryfolders.vdf.
    for value in re.findall(r'"path"\s*"((?:\\.|[^"])*)"', text):
        value = value.replace("\\\\", "\\").replace('\\"', '"')
        path = Path(value)
        try:
            path = path.resolve()
        except OSError:
            continue
        if path not in libraries and (path / "steamapps").is_dir():
            libraries.append(path)
    return libraries


def _steam_games():
    games = []
    seen = set()
    for root in _steam_roots():
        for library in _steam_library_paths(root):
            manifests = library / "steamapps"
            try:
                files = manifests.glob("appmanifest_*.acf")
                for file in files:
                    try:
                        text = file.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    app_id = re.search(r'"appid"\s*"(\d+)"', text)
                    name = re.search(r'"name"\s*"((?:\\.|[^"])*)"', text)
                    folder = re.search(r'"installdir"\s*"((?:\\.|[^"])*)"', text)
                    if not app_id or not name or not folder:
                        continue
                    game_name = name.group(1).replace('\\"', '"')
                    if game_name.casefold() in IGNORED_GAME_NAMES:
                        continue
                    install_path = (manifests / "common" / folder.group(1)).resolve()
                    common_path = (manifests / "common").resolve()
                    if not install_path.is_dir() or not install_path.is_relative_to(common_path):
                        continue
                    game_id = f"steam:{app_id.group(1)}"
                    if game_id not in seen:
                        games.append({"id": game_id, "name": game_name, "launcher": "Steam", "path": str(install_path)})
                        seen.add(game_id)
            except OSError:
                continue
    return games


def _epic_games():
    if os.name != "nt":
        return []
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    manifest_dir = Path(program_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    games = []
    try:
        manifests = manifest_dir.glob("*.item")
        for file in manifests:
            try:
                record = json.loads(file.read_text(encoding="utf-8"))
                name = record.get("DisplayName") or record.get("AppName")
                location = record.get("InstallLocation")
                app_name = record.get("AppName")
                if not name or not location or not app_name or not Path(location).is_dir():
                    continue
                games.append({"id": f"epic:{app_name}", "name": name, "launcher": "Epic Games", "path": str(Path(location))})
            except (OSError, json.JSONDecodeError):
                continue
    except OSError:
        pass
    return games


def detect_games():
    """Lê manifestos do Steam e Epic em pastas conhecidas; não faz busca recursiva."""
    games = _steam_games() + _epic_games()
    games.sort(key=lambda game: game["name"].casefold())
    return {
        "supported": True,
        "games": games,
        "message": "Jogos instalados encontrados por manifestos do Steam e Epic Games." if games else
        "Nenhum jogo instalado foi encontrado nos manifestos do Steam/Epic. Outros launchers podem ser adicionados depois.",
    }


def profile_storage_path():
    """Pasta de dados local do usuário, fora da pasta do programa."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Shadow" / "game_profiles.json"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "shadow" / "game_profiles.json"


def load_game_profiles(storage_path=None):
    path = Path(storage_path) if storage_path else profile_storage_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Formato inválido")
        profiles = data.get("profiles", {})
        history = data.get("history", [])
        return {"profiles": profiles if isinstance(profiles, dict) else {},
                "history": history if isinstance(history, list) else []}
    except (OSError, json.JSONDecodeError, ValueError):
        return {"profiles": {}, "history": []}


def save_game_profile(game_id, game_name, profile, storage_path=None):
    """Salva somente uma preferência do Shadow; não altera arquivos do jogo ou Windows."""
    if not isinstance(game_id, str) or not re.fullmatch(r"(steam|epic):[A-Za-z0-9_.-]{1,100}", game_id):
        return {"success": False, "message": "Identificador de jogo inválido."}
    if profile not in PROFILE_OPTIONS:
        return {"success": False, "message": "Perfil não reconhecido."}
    name = str(game_name).strip()[:160]
    if not name:
        return {"success": False, "message": "Nome do jogo inválido."}

    path = Path(storage_path) if storage_path else profile_storage_path()
    data = load_game_profiles(path)
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    entry = {"game_id": game_id, "game_name": name, "profile": profile, "saved_at": timestamp}
    data["profiles"][game_id] = entry
    data["history"].insert(0, entry.copy())
    data["history"] = data["history"][:50]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".shadow-profiles-", dir=path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                json.dump(data, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    except OSError as error:
        return {"success": False, "message": f"Não foi possível salvar o perfil: {error}"}
    return {"success": True, "message": "Preferência salva no Shadow.", "data": data}


def hardware_recommendations(game, hardware, memory):
    """Sugestões genéricas com base no hardware identificado, sem prever FPS/compatibilidade."""
    tips = []
    ram_gb = memory.get("total_gb") if isinstance(memory, dict) else None
    if isinstance(ram_gb, (int, float)):
        if ram_gb <= 8:
            tips.append("Seu PC tem até 8 GB de RAM. Considere reduzir texturas e manter poucos aplicativos abertos; confira os requisitos oficiais do jogo.")
        elif ram_gb < 16:
            tips.append("A RAM identificada é menor que 16 GB. Texturas mais leves podem ajudar a evitar pressão de memória em alguns jogos.")
        else:
            tips.append(f"O Shadow identificou {ram_gb:.0f} GB de RAM. Isso, sozinho, não garante desempenho: confira os requisitos oficiais de {game.get('name', 'este jogo')}.")
    else:
        tips.append("Não foi possível confirmar a memória total. Confira os requisitos oficiais do jogo antes de ajustar qualidade gráfica.")

    cpu_name = hardware.get("cpu_name")
    logical_cores = hardware.get("logical_cores")
    if cpu_name and isinstance(logical_cores, int):
        tips.append(f"Processador identificado: {cpu_name} ({logical_cores} threads lógicas). Compare o modelo com o requisito de CPU publicado pelo jogo.")
    elif cpu_name:
        tips.append(f"Processador identificado: {cpu_name}. Confira o requisito de CPU oficial de {game.get('name', 'este jogo')}.")
    else:
        tips.append("O processador não foi identificado nesta leitura. Confira o modelo no Windows e compare com o requisito oficial.")

    gpu_names = hardware.get("gpu_names") or []
    if gpu_names:
        tips.append(f"GPU identificada: {', '.join(gpu_names)}. Compare o modelo com os requisitos oficiais; o Shadow não estima FPS.")
    else:
        tips.append("A GPU não foi identificada. Veja o modelo no Gerenciador de Dispositivos e compare com os requisitos oficiais.")

    tips.append("Se o jogo estiver em um disco quase cheio, liberar espaço pode ajudar atualizações e instalações; não significa aumento garantido de FPS.")
    return tips
