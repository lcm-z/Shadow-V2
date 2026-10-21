"""Leitura de capturas CSV e histórico local de medições do Performance Lab."""

import csv
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


MAX_CAPTURE_BYTES = 30 * 1024 * 1024
MAX_FRAME_ROWS = 500_000
MIN_FRAMES_FOR_PERCENTILE = 100
MAX_HISTORY = 50


def history_path():
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "Shadow" / "performance_history.json"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "shadow" / "performance_history.json"


def _number(value):
    if value is None:
        return None
    value = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not value or value.lower() in {"nan", "n/a", "none", "null"}:
        return None
    # CSVs separados por ponto e vírgula podem usar vírgula decimal.
    if "," in value and "." not in value:
        value = value.replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _normalized_header(value):
    return re.sub(r"[^a-z0-9%]", "", (value or "").casefold())


def _pick_column(headers, candidates):
    normalized = {_normalized_header(header): header for header in headers}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    for key, original in normalized.items():
        if any(candidate in key for candidate in candidates):
            return original
    return None


def parse_capture_csv(file_path):
    """Lê CSV bruto de PresentMon/CapFrameX e extrai métricas apenas se existirem."""
    path = Path(file_path)
    try:
        if path.stat().st_size > MAX_CAPTURE_BYTES:
            return {"success": False, "message": "O CSV excede o limite de 30 MB."}
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as capture_file:
            sample = capture_file.read(8192)
            capture_file.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(capture_file, dialect=dialect)
            headers = reader.fieldnames or []
            if not headers:
                return {"success": False, "message": "O arquivo não contém cabeçalhos CSV."}

            frame_column = _pick_column(headers, [
                "msbetweenpresents", "frametime", "frametimes", "frametimems",
                "frametimeinms", "frametimeinmilliseconds", "framems",
            ])
            fps_column = _pick_column(headers, [
                "averagefps", "avgfps", "meanfps", "averageframerate", "fpsaverage",
            ])
            low_column = _pick_column(headers, ["1%low", "1low", "onepercentlow", "low1%", "p99fps"])
            frame_times = []
            fps_values = []
            low_values = []
            if frame_column:
                for row_index, row in enumerate(reader):
                    if row_index >= MAX_FRAME_ROWS:
                        break
                    value = _number(row.get(frame_column))
                    if value is not None and 0.05 <= value <= 60000:
                        frame_times.append(value)
                    if fps_column:
                        fps = _number(row.get(fps_column))
                        if fps is not None and fps > 0:
                            fps_values.append(fps)
                    if low_column:
                        low = _number(row.get(low_column))
                        if low is not None and low > 0:
                            low_values.append(low)
            else:
                for row_index, row in enumerate(reader):
                    if row_index >= MAX_FRAME_ROWS:
                        break
                    if fps_column:
                        fps = _number(row.get(fps_column))
                        if fps is not None and fps > 0:
                            fps_values.append(fps)
                    if low_column:
                        low = _number(row.get(low_column))
                        if low is not None and low > 0:
                            low_values.append(low)

        average_fps = (1000 / (sum(frame_times) / len(frame_times))) if frame_times else (
            sum(fps_values) / len(fps_values) if fps_values else None
        )
        if len(frame_times) >= MIN_FRAMES_FOR_PERCENTILE:
            ordered = sorted(frame_times)
            p99_frame_time = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.99) - 1)]
            slowest_frame_times = sorted(frame_times, reverse=True)[:max(1, math.ceil(len(frame_times) * 0.01))]
            one_percent_low = sum(1000 / frame_time for frame_time in slowest_frame_times) / len(slowest_frame_times)
        else:
            one_percent_low = sum(low_values) / len(low_values) if low_values else None

        if average_fps is None and one_percent_low is None:
            return {
                "success": False,
                "message": "Não encontrei frametimes ou colunas reconhecidas de FPS. Exporte os dados brutos de PresentMon/CapFrameX.",
            }
        return {
            "success": True,
            "source_file": path.name,
            "frame_count": len(frame_times),
            "average_fps": round(average_fps, 2) if average_fps is not None else None,
            "one_percent_low": round(one_percent_low, 2) if one_percent_low is not None else None,
            "average_frametime_ms": round(sum(frame_times) / len(frame_times), 3) if frame_times else None,
            "p99_frametime_ms": round(sorted(frame_times)[min(len(frame_times) - 1, math.ceil(len(frame_times) * 0.99) - 1)], 3) if len(frame_times) >= MIN_FRAMES_FOR_PERCENTILE else None,
            "measurement": "frametimes_csv" if frame_times else "summary_csv",
        }
    except (OSError, csv.Error, UnicodeError) as error:
        return {"success": False, "message": f"Não foi possível ler o CSV: {error}"}


def load_history(storage_path=None):
    path = Path(storage_path) if storage_path else history_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get("records", []) if isinstance(data, dict) else []
        return records if isinstance(records, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_result(capture, game_id, game_name, config_label, phase, samples, storage_path=None):
    if not isinstance(capture, dict) or not capture.get("success"):
        return {"success": False, "message": "A captura de FPS não é válida."}
    if not isinstance(game_id, str) or not re.fullmatch(r"(steam|epic):[A-Za-z0-9_.-]{1,100}", game_id):
        return {"success": False, "message": "Selecione um jogo detectado pelo Gaming Hub."}
    if phase not in {"before", "after", "custom"}:
        return {"success": False, "message": "Tipo de comparação inválido."}
    game_name = str(game_name).strip()[:160]
    config_label = str(config_label).strip()[:100]
    if not game_name or not config_label:
        return {"success": False, "message": "Informe o jogo e um rótulo para esta configuração."}

    valid_samples = []
    for sample in (samples or [])[:1800]:
        if not isinstance(sample, dict):
            continue
        row = {"elapsed": _number(sample.get("elapsed"))}
        for key in ("cpu_percent", "ram_percent", "gpu_percent"):
            value = _number(sample.get(key))
            row[key] = round(max(0, min(100, value)), 1) if value is not None else None
        row["gpu_measured_at"] = _number(sample.get("gpu_measured_at"))
        row["temperatures"] = []
        temperatures = sample.get("temperatures", [])
        for sensor in (temperatures if isinstance(temperatures, list) else [])[:128]:
            if not isinstance(sensor, dict):
                continue
            value = _number(sensor.get("temperature_c"))
            if value is not None and -20 <= value <= 150:
                row["temperatures"].append({"name": str(sensor.get("name", ""))[:160],
                                            "source": str(sensor.get("source", ""))[:80],
                                            "temperature_c": value})
        if row["elapsed"] is not None:
            valid_samples.append(row)
    if not valid_samples:
        return {"success": False, "message": "Inicie e finalize uma sessão de monitoramento antes de salvar o resultado."}

    cpu_values = [item["cpu_percent"] for item in valid_samples if item["cpu_percent"] is not None]
    ram_values = [item["ram_percent"] for item in valid_samples if item["ram_percent"] is not None]
    gpu_values = [item["gpu_percent"] for item in valid_samples if item["gpu_percent"] is not None]
    result = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "game_id": game_id,
        "game_name": game_name,
        "config_label": config_label,
        "phase": phase,
        "saved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "capture": {key: capture.get(key) for key in (
            "source_file", "frame_count", "average_fps", "one_percent_low",
            "average_frametime_ms", "p99_frametime_ms", "measurement",
        )},
        "system": {
            "sample_count": len(valid_samples),
            "duration_seconds": round(valid_samples[-1]["elapsed"], 1),
            "cpu_average": round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None,
            "ram_average": round(sum(ram_values) / len(ram_values), 1) if ram_values else None,
            "gpu_average": round(sum(gpu_values) / len(gpu_values), 1) if gpu_values else None,
            "samples": valid_samples,
        },
    }
    path = Path(storage_path) if storage_path else history_path()
    records = load_history(path)
    records.insert(0, result)
    records = records[:MAX_HISTORY]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".shadow-performance-", dir=path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({"records": records}, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except OSError as error:
        return {"success": False, "message": f"Não foi possível salvar o histórico: {error}"}
    return {"success": True, "message": "Medição salva no histórico local.", "record": result, "records": records}


def find_nvidia_smi():
    executable = shutil.which("nvidia-smi")
    if executable:
        return executable
    if os.name == "nt":
        program_files = os.environ.get("ProgramW6432", os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidate = Path(program_files) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def read_gpu_utilization(executable=None):
    executable = executable or find_nvidia_smi()
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2,
            check=False,
        )
        values = [_number(line) for line in result.stdout.splitlines()]
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), 1) if result.returncode == 0 and values else None
    except (OSError, subprocess.TimeoutExpired):
        return None
