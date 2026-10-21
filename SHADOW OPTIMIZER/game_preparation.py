"""Preparação por jogo: plano de energia escolhido, cópia local e restauração explícita."""

import json
import threading
import time
from pathlib import Path
from uuid import uuid4

from app_support import data_directory
from gaming import detect_games
from history import record_action, mark_action_undone
from optimizations import power_plan_overview, activate_power_plan
from ui_settings import atomic_json


class GamePreparation:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else data_directory()
        self.lock = threading.RLock()
        self.preview = None

    def _read(self, filename):
        try:
            value = json.loads((self.directory / filename).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Formato inválido")
            return value
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            # Um backup ilegível nunca é tratado como se não existisse.
            raise ValueError("Não foi possível ler os dados da preparação. Preserve o arquivo e consulte o log.") from error

    def _game(self, game_id):
        return next((g for g in detect_games()["games"] if g["id"] == game_id), None)

    def overview(self, game_id):
        with self.lock:
            try:
                preferences = self._read("game_preparation.json")
                session = self._read("game_session.json")
                preference = preferences.get(game_id, {})
                if not isinstance(preference, dict):
                    raise ValueError("Preparação salva inválida; preserve o arquivo para recuperação.")
                plans = power_plan_overview()
                return {"success": True, "preference": preference, "session": session,
                        "power": plans, "game_id": game_id}
            except ValueError as error:
                return {"success": False, "message": str(error)}

    def save(self, game_id, guid, checklist):
        with self.lock:
            if not self._game(game_id):
                return {"success": False, "message": "O jogo não está mais na biblioteca detectada."}
            if not isinstance(checklist, list) or len(checklist) != 3 or any(type(v) is not bool for v in checklist):
                return {"success": False, "message": "Checklist inválido."}
            plans = power_plan_overview()
            if guid != "keep" and not any(p["guid"].casefold() == str(guid).casefold() for p in plans.get("plans", [])):
                return {"success": False, "message": "O plano escolhido não está disponível."}
            try:
                preferences = self._read("game_preparation.json")
                preferences[game_id] = {"power_guid": guid, "checklist": checklist}
                atomic_json(self.directory / "game_preparation.json", preferences)
            except (OSError, ValueError) as error:
                return {"success": False, "message": str(error)}
            return {"success": True, "message": "Preparação salva para este jogo; nenhum ajuste foi aplicado."}

    def review(self, game_id):
        with self.lock:
            self.preview = None
            game = self._game(game_id)
            if not game:
                return {"success": False, "message": "Selecione um jogo instalado."}
            data = self.overview(game_id)
            if not data["success"]:
                return data
            if data["session"].get("active"):
                return {"success": False, "message": "Restaure a preparação anterior antes de preparar outro jogo."}
            guid = data["preference"].get("power_guid", "keep")
            plans = data["power"].get("plans", [])
            current = next((p for p in plans if p.get("active")), None)
            target = next((p for p in plans if p["guid"].casefold() == str(guid).casefold()), None)
            if guid == "keep" or (current and target and current["guid"].casefold() == target["guid"].casefold()):
                return {"success": True, "changed": False, "message": "Nenhum ajuste necessário. O plano atual será mantido; confira seu checklist."}
            if not current or not target or not data["power"].get("supported"):
                return {"success": False, "message": "Não foi possível confirmar o plano atual e o escolhido. Atualize a preparação."}
            token = uuid4().hex
            self.preview = {"token": token, "expires": time.monotonic() + 120, "game_id": game_id,
                            "game_name": game["name"], "previous_guid": current["guid"],
                            "expected_guid": target["guid"], "previous_name": current["name"], "target_name": target["name"]}
            return {"success": True, "changed": True, "token": token,
                    "message": f"Preparar {game['name']}: trocar o plano de energia de {current['name']} para {target['name']}. Pode aumentar consumo, calor e uso da bateria. O plano anterior será guardado para restauração. Nenhum aplicativo será fechado. Aplicar?"}

    def apply(self, token):
        with self.lock:
            preview = self.preview
            self.preview = None  # Confirmação de uso único.
            if not preview or token != preview["token"] or time.monotonic() > preview["expires"]:
                return {"success": False, "message": "A revisão expirou. Revise a preparação novamente."}
            try:
                if self._read("game_session.json").get("active"):
                    return {"success": False, "message": "Já existe uma preparação pendente de restauração."}
                current = next((p for p in power_plan_overview().get("plans", []) if p.get("active")), None)
                if not current or current["guid"].casefold() != preview["previous_guid"].casefold():
                    return {"success": False, "message": "O plano ativo mudou depois da revisão. Nenhum ajuste foi aplicado."}
                session = {key: value for key, value in preview.items() if key not in ("token", "expires")}
                session.update(active=True, applied_at=time.time())
                # A cópia precisa existir ANTES de alterar o Windows.
                atomic_json(self.directory / "game_session.json", session)
                result = activate_power_plan(session["expected_guid"])
                if not result.get("success"):
                    return {"success": False, "message": f"{result.get('message', 'Falha ao aplicar.')} A cópia foi preservada; use Restaurar para verificar o plano."}
                try:
                    action = record_action("power_plan", f"Preparação: {session['game_name']}",
                                           f"{session['previous_name']} → {session['target_name']}. Restauração manual disponível.",
                                           {"previous_guid": session["previous_guid"], "expected_guid": session["expected_guid"]}, reversible=True)
                    session["action_id"] = action["id"]
                    atomic_json(self.directory / "game_session.json", session)
                except OSError:
                    return {"success": True, "message": "Plano aplicado. A cópia para restaurar foi salva, mas o histórico não pôde ser atualizado."}
                return {"success": True, "message": "Preparação aplicada. Ao terminar de jogar, clique em Restaurar plano anterior."}
            except (OSError, ValueError) as error:
                return {"success": False, "message": f"Não foi possível preparar com cópia segura: {error}"}

    def restore(self):
        with self.lock:
            try:
                session = self._read("game_session.json")
                if not session.get("active"):
                    return {"success": False, "message": "Nenhuma preparação ativa."}
                current = next((p for p in power_plan_overview().get("plans", []) if p.get("active")), None)
                if not current:
                    return {"success": False, "message": "Plano ativo não identificado. A cópia foi preservada."}
                current_guid = current["guid"].casefold()
                if current_guid == session["previous_guid"].casefold():
                    result = {"success": True}
                elif current_guid == session["expected_guid"].casefold():
                    result = activate_power_plan(session["previous_guid"])
                else:
                    return {"success": False, "message": "O plano foi alterado fora desta preparação. Ele foi preservado; revise os planos na página Energia."}
                if not result.get("success"):
                    return result
                session["active"] = False
                session["restored_at"] = time.time()
                atomic_json(self.directory / "game_session.json", session)
                if session.get("action_id"):
                    try:
                        mark_action_undone(session["action_id"])
                    except OSError:
                        pass
                return {"success": True, "message": "Plano anterior restaurado; preparação finalizada."}
            except (OSError, ValueError, KeyError) as error:
                return {"success": False, "message": f"Não foi possível finalizar a restauração: {error}. A cópia foi preservada."}
