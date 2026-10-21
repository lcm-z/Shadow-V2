"""Abre a interface web do Shadow dentro de uma janela desktop."""

import io
import time
from contextlib import redirect_stdout
from pathlib import Path
import sys
import threading

import psutil
from window_lifecycle import WindowLifecycle
from hardware_telemetry import Telemetry
from game_preparation import GamePreparation
from ui_settings import load_settings, save_settings

from main import build_diagnostic_findings, collect_system_info, scan_system, terminate_user_process
from optimizations import (
    activate_power_plan,
    clean_temp_files,
    disk_overview,
    live_system_sample,
    power_plan_overview,
    preview_temp_cleanup,
    set_startup_enabled,
    startup_overview,
)
from gaming import detect_games, hardware_recommendations, load_game_profiles, save_game_profile
from performance_lab import (
    load_history as load_performance_history,
    parse_capture_csv,
    save_result as save_performance_result,
)
from network_lab import network_overview, run_connectivity_test
from history import find_action, get_history, mark_action_undone, record_action, record_diagnostic
from app_support import (
    clear_error_log,
    compatibility_overview,
    error_log_overview,
    install_exception_logging,
    launch_at_login_overview,
    log_error,
    read_error_log,
    set_launch_at_login,
)


class ShadowApi:
    """Métodos Python que a interface JavaScript pode chamar."""

    def __init__(self):
        self.window = None
        self.process_cache = {}
        self.previous_disk_io = None
        self.previous_sample_time = None
        self.performance_started_at = None
        self.performance_samples = []
        self.last_performance_session = []
        self.last_performance_session_has_gpu = False
        self.performance_lock = threading.Lock()
        self.scan_lock = threading.Lock()
        self.live_lock = threading.Lock()
        self.telemetry = Telemetry()
        self.preparation = GamePreparation()
        self.scan_stages = [
            "Preparando leitura",
            "Identificando sistema e hardware",
            "Analisando memória e processos",
            "Amostrando CPU e RAM por 5 segundos",
            "Consolidando o relatório",
        ]
        self.scan_state = {"running": False, "success": None, "stage": None, "stages": [], "report": None, "error": ""}

    def scan(self):
        # A tela recebe o relatório como dados; o texto do modo console fica oculto.
        with redirect_stdout(io.StringIO()):
            report = scan_system(monitor_duration=5)
        return self._save_scan_report(report)

    def _save_scan_report(self, report):
        try:
            record_diagnostic(report)
        except OSError:
            # A análise continua disponível se o armazenamento local estiver bloqueado.
            pass
        return report

    def start_scan(self):
        """Inicia uma análise em segundo plano para manter a janela responsiva."""
        with self.scan_lock:
            if self.scan_state.get("running"):
                return {"success": False, "message": "Uma análise já está em andamento."}
            self.scan_state = {
                "running": True,
                "success": None,
                "stage": None,
                "stages": [{"name": name, "status": "pending"} for name in self.scan_stages],
                "report": None,
                "error": "",
            }
        worker = threading.Thread(target=self._run_scan_in_background, name="ShadowScan", daemon=True)
        worker.start()
        return {"success": True}

    def _update_scan_progress(self, stage, status):
        with self.scan_lock:
            self.scan_state["stage"] = stage
            for item in self.scan_state["stages"]:
                if item["name"] == stage:
                    item["status"] = status
                    break

    def _run_scan_in_background(self):
        try:
            with redirect_stdout(io.StringIO()):
                report = scan_system(monitor_duration=5, progress_callback=self._update_scan_progress)
            self._save_scan_report(report)
        except Exception as error:
            log_error("Falha durante a análise do sistema", f"{type(error).__name__}: {error}")
            with self.scan_lock:
                active = next((item for item in self.scan_state["stages"] if item["status"] == "active"), None)
                if active:
                    active["status"] = "failed"
                self.scan_state.update({"running": False, "success": False, "error": str(error)[:1000]})
            return
        with self.scan_lock:
            self.scan_state.update({"running": False, "success": True, "report": report, "error": ""})

    def scan_progress(self):
        with self.scan_lock:
            return {
                "running": self.scan_state["running"],
                "success": self.scan_state["success"],
                "stage": self.scan_state["stage"],
                "stages": [dict(item) for item in self.scan_state["stages"]],
                "report": self.scan_state["report"],
                "error": self.scan_state["error"],
            }

    def terminate_process(self, pid, expected_name, expected_create_time):
        """Encerra somente o processo escolhido e validado pelo usuário na tela."""
        result = terminate_user_process(pid, expected_name, expected_create_time)
        if result.get("success"):
            self._record_action("process", f"Aplicativo encerrado: {expected_name}",
                                "A ação não pode ser desfeita pelo Shadow.")
        return result

    @staticmethod
    def _record_action(kind, title, details, undo_data=None, reversible=False):
        try:
            record_action(kind, title, details, undo_data, reversible)
        except OSError:
            # A ação do usuário já ocorreu; falha ao gravar o histórico não a desfaz.
            pass

    def history_overview(self):
        return get_history()

    def undo_history_action(self, action_id):
        action = find_action(action_id)
        if not action:
            return {"success": False, "message": "Esta ação não está mais no histórico."}
        if not action.get("reversible") or action.get("undone"):
            return {"success": False, "message": "Esta ação não pode ser desfeita pelo Shadow."}

        data = action.get("undo_data") or {}
        if action.get("kind") == "startup":
            overview = startup_overview()
            item = next((item for item in overview.get("items", []) if item.get("name") == data.get("name")), None)
            if not overview.get("supported") or not item or item.get("enabled") != data.get("expected_enabled"):
                return {"success": False, "message": "O item mudou desde a ação. Atualize a lista antes de tentar desfazer."}
            result = set_startup_enabled(data["name"], data["previous_enabled"])
        elif action.get("kind") == "power_plan":
            overview = power_plan_overview()
            active = next((plan.get("guid") for plan in overview.get("plans", []) if plan.get("active")), None)
            expected = data.get("expected_guid") or ""
            if not overview.get("supported") or not active or active.casefold() != expected.casefold():
                return {"success": False, "message": "O plano ativo mudou desde a ação. Atualize a página antes de tentar desfazer."}
            result = activate_power_plan(data.get("previous_guid", ""))
        elif action.get("kind") == "app_startup":
            current = launch_at_login_overview()
            if not current.get("supported") or current.get("enabled") != data.get("expected_enabled"):
                return {"success": False, "message": "A inicialização do Shadow mudou desde a ação. Atualize as configurações."}
            result = set_launch_at_login(data.get("previous_enabled", False))
        else:
            return {"success": False, "message": "O Shadow não tem uma restauração segura para esta ação."}

        if result.get("success"):
            try:
                mark_action_undone(action_id)
            except OSError:
                return {"success": True, "message": f"{result.get('message', 'Ação desfeita')} O histórico não conseguiu atualizar o marcador."}
        return result

    def close_app(self):
        """Fecha a janela principal quando a pessoa usa o botão da interface."""
        if self.window is not None:
            self.window.destroy()

    def optimizer_overview(self):
        """Carrega os recursos opcionais sem fazer alterações no computador."""
        return {
            "disks": disk_overview(),
            "temp_cleanup": preview_temp_cleanup(),
            "startup": startup_overview(),
            "power_plans": power_plan_overview(),
        }

    def diagnostic_findings(self, report, overview):
        """Gera achados explicáveis com as medições e listas já coletadas."""
        return build_diagnostic_findings(report, overview)

    def gaming_overview(self):
        """Lista jogos encontrados e preferências locais do Gaming Hub."""
        return {**detect_games(), **load_game_profiles()}

    def save_game_profile(self, game_id, game_name, profile):
        return save_game_profile(game_id, game_name, profile)

    def game_recommendations(self, game_id, game_name, hardware, memory):
        return hardware_recommendations(
            {"id": game_id, "name": game_name}, hardware or {}, memory or {}
        )

    def performance_overview(self):
        records = self._performance_summaries(load_performance_history())
        hardware = self.telemetry.hardware()
        supported = any(g.get("usage_percent") is not None for g in hardware["gpus"])
        return {
            "records": records,
            "gpu_supported": supported,
            "gpu_message": "GPU: maior uso entre as placas com leitura; sensores atualizados a cada 5 s (10 s no modo leve)." if supported
            else "Uso de GPU indisponível nesta leitura. CPU/RAM continuam disponíveis. Veja Sensores na visão geral.",
        }

    @staticmethod
    def _performance_summaries(records):
        """A interface recebe resumos; as séries completas continuam no histórico local."""
        summaries = []
        for record in records:
            if not isinstance(record, dict):
                continue
            summary = dict(record)
            system = dict(summary.get("system", {}))
            system.pop("samples", None)
            summary["system"] = system
            summaries.append(summary)
        return summaries

    def start_performance_monitoring(self):
        with self.performance_lock:
            if self.performance_started_at is not None:
                return {"success": False, "message": "Já existe uma sessão de monitoramento em andamento."}
            self.performance_samples = []
            self.performance_started_at = time.monotonic()
            self.performance_gpu_supported = any(g.get("usage_percent") is not None for g in self.telemetry.hardware()["gpus"])
            psutil.cpu_percent(interval=None)  # A primeira chamada prepara a próxima leitura.
            return {"success": True, "started_at": time.time(), "gpu_supported": self.performance_gpu_supported}

    def sample_performance_monitoring(self):
        with self.performance_lock:
            if self.performance_started_at is None:
                return {"success": False, "message": "Nenhuma sessão de monitoramento está ativa."}
            if time.monotonic() - self.performance_started_at >= 1800:
                return {"success": False, "limit_reached": True, "message": "Limite de 30 minutos atingido; sessão finalizada."}
            cpu = psutil.cpu_percent(interval=0.12)
            memory = psutil.virtual_memory()
            settings = load_settings()
            hardware = self.telemetry.hardware(10 if settings["lightweight"] else 5)
            values = [g["usage_percent"] for g in hardware["gpus"] if g.get("usage_percent") is not None]
            gpu = max(values) if values else None
            sample = {
                "elapsed": round(time.monotonic() - self.performance_started_at, 2),
                "cpu_percent": round(cpu, 1),
                "ram_percent": round(memory.percent, 1),
                "gpu_percent": gpu,
                "gpu_measured_at": hardware["measured_at"],
                "temperatures": hardware["temperatures"],
            }
            self.performance_samples.append(sample)
            return {"success": True, "sample": sample, "sample_count": len(self.performance_samples)}

    def stop_performance_monitoring(self):
        with self.performance_lock:
            if self.performance_started_at is None:
                return {"success": False, "message": "Nenhuma sessão de monitoramento está ativa."}
            samples = self.performance_samples
            self.performance_started_at = None
            self.performance_samples = []
            self.last_performance_session = samples
            self.last_performance_session_has_gpu = self.performance_gpu_supported
            return {"success": True, "samples": samples, "gpu_supported": self.last_performance_session_has_gpu}

    def discard_performance_session(self):
        with self.performance_lock:
            if self.performance_started_at is not None:
                return {"success": False, "message": "Finalize o monitoramento antes de descartar a sessão."}
            self.last_performance_session = []
            self.performance_samples = []
            return {"success": True}

    def choose_performance_capture(self):
        if self.window is None:
            return {"success": False, "message": "A janela do Shadow não está disponível."}
        import webview

        file_dialog = getattr(webview, "FileDialog", None)
        dialog_type = None
        if file_dialog is not None:
            for name in ("OPEN", "LOAD"):
                candidate = getattr(file_dialog, name, None)
                if candidate is not None:
                    dialog_type = candidate
                    break
        if dialog_type is None:
            dialog_type = getattr(webview, "OPEN_DIALOG", None)
        if dialog_type is None:
            return {"success": False, "message": "A versão do pywebview não oferece diálogo de abertura de arquivo."}
        selected = self.window.create_file_dialog(
            dialog_type,
            allow_multiple=False,
            file_types=("CSV de benchmark (*.csv)", "Todos os arquivos (*.*)"),
        )
        if not selected:
            return {"success": False, "cancelled": True, "message": "Seleção cancelada."}
        return parse_capture_csv(selected[0])

    def save_performance_result(self, capture, game_id, game_name, config_label, phase):
        with self.performance_lock:
            result = save_performance_result(
                capture,
                game_id,
                game_name,
                config_label,
                phase,
                self.last_performance_session,
            )
            if result.get("success"):
                self.last_performance_session = []
                result["records"] = self._performance_summaries(result.get("records", []))
            return result

    def performance_history(self):
        return self._performance_summaries(load_performance_history())

    def network_overview(self):
        return network_overview()

    def run_network_test(self, target):
        return run_connectivity_test(target)

    def settings_overview(self):
        system = collect_system_info()
        hardware = self.telemetry.hardware()
        gpu_supported = any(g.get("usage_percent") is not None for g in hardware["gpus"])
        return {
            "compatibility": compatibility_overview(system, gpu_supported, bool(hardware["temperatures"])),
            "launch_at_login": launch_at_login_overview(),
            "error_log": error_log_overview(),
            "preferences": load_settings(),
        }

    def ui_preferences(self):
        return load_settings()

    def save_ui_preferences(self, value):
        return save_settings(value)

    def telemetry_snapshot(self):
        settings = load_settings()
        return {**self.telemetry.hardware(10 if settings["lightweight"] else 5), "shadow": self.telemetry.own_usage()}

    def game_preparation_overview(self, game_id):
        return self.preparation.overview(game_id)

    def save_game_preparation(self, game_id, guid, checklist):
        return self.preparation.save(game_id, guid, checklist)

    def review_game_preparation(self, game_id):
        return self.preparation.review(game_id)

    def apply_game_preparation(self, token):
        return self.preparation.apply(token)

    def restore_game_preparation(self):
        return self.preparation.restore()

    def set_launch_at_login(self, enabled):
        previous = launch_at_login_overview()
        result = set_launch_at_login(bool(enabled))
        if result.get("success") and previous.get("supported") and previous.get("enabled") != bool(enabled):
            self._record_action(
                "app_startup", "Inicialização do Shadow",
                "Preferência de início junto com a conta atual do Windows.",
                {"previous_enabled": previous["enabled"], "expected_enabled": bool(enabled)},
                reversible=True,
            )
        return result

    def read_error_log(self):
        return read_error_log()

    def clear_error_log(self):
        return clear_error_log()

    def log_frontend_error(self, message, source=""):
        log_error(f"Erro da interface: {str(message)[:1000]}", f"Origem: {str(source)[:500]}" if source else "")
        return {"success": True}

    def clean_temp(self, selected_paths):
        result = clean_temp_files(selected_paths)
        if result.get("success") and result.get("removed_count", 0):
            self._record_action(
                "cleanup", "Arquivos temporários removidos",
                f"{result['removed_count']} arquivo(s); {result.get('freed_bytes', 0)} bytes. Ação irreversível.",
            )
        return result

    def set_startup(self, name, enabled):
        overview = startup_overview()
        item = next((item for item in overview.get("items", []) if item.get("name") == name), None)
        previous = item.get("enabled") if item else None
        result = set_startup_enabled(name, bool(enabled))
        if result.get("success") and previous is not None and previous != bool(enabled):
            self._record_action(
                "startup", f"Inicialização: {name}",
                "Alteração na inicialização da conta atual. Pode ser desfeita enquanto o item não mudar novamente.",
                {"name": name, "previous_enabled": previous, "expected_enabled": bool(enabled)},
                reversible=True,
            )
        return result

    def set_power_plan(self, guid):
        before = power_plan_overview()
        previous = next((plan for plan in before.get("plans", []) if plan.get("active")), None)
        selected = next((plan for plan in before.get("plans", []) if plan.get("guid", "").casefold() == str(guid).casefold()), None)
        result = activate_power_plan(guid)
        if result.get("success") and previous and selected and previous.get("guid", "").casefold() != selected.get("guid", "").casefold():
            self._record_action(
                "power_plan", f"Plano de energia: {selected.get('name', 'Plano do Windows')}",
                "Plano ativo alterado no Windows. Pode ser desfeito se o plano escolhido continuar ativo.",
                {"previous_guid": previous["guid"], "expected_guid": selected["guid"]},
                reversible=True,
            )
        return result

    def live_sample(self):
        with self.live_lock:
            return self._live_sample_locked()

    def _live_sample_locked(self):
        sample = live_system_sample(
            self.process_cache,
            self.previous_disk_io,
            self.previous_sample_time,
        )
        self.previous_disk_io = sample["disk_io"]
        self.previous_sample_time = sample["timestamp"]
        return {key: value for key, value in sample.items() if key not in {"disk_io", "timestamp"}}


def launch_gui():
    install_exception_logging()
    try:
        import webview
    except ImportError:
        log_error("Não foi possível importar pywebview", "A interface desktop não pôde iniciar.")
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                "O Shadow não conseguiu iniciar a interface. Verifique se o Microsoft Edge WebView2 Runtime está instalado.",
                "Shadow | PC Optimizer",
                0x10,
            )
            return
        print(
            "O Shadow precisa do pywebview para abrir a interface HTML/CSS.\n"
            "No CachyOS, use um ambiente virtual para instalar as dependências:\n"
            "  python -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  python -m pip install -r requirements.txt\n"
            "  python main.py",
            file=sys.stderr,
        )
        return

    page = Path(__file__).parent / "ui" / "index.html"
    api = ShadowApi()
    window = webview.create_window(
        "Shadow | PC Optimizer",
        str(page),
        js_api=api,
        width=1120,
        height=780,
        min_size=(900, 650),
        background_color="#0b0814",
    )
    api.window = window
    lifecycle = WindowLifecycle()
    lifecycle.attach(window)
    try:
        if sys.platform == "win32":
            # O pacote Windows usa somente Edge WebView2/WinForms, sem incluir Qt/GTK.
            webview.start(gui="edgechromium")
        else:
            webview.start()
    finally:
        lifecycle.stop()


if __name__ == "__main__":
    launch_gui()
