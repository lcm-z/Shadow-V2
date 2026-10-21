"""Encerra as esperas da ponte JavaScript quando a janela do Shadow fecha."""

from copy import deepcopy
import threading
from uuid import uuid4


class WindowLifecycle:
    def __init__(self):
        self.stopping = threading.Event()

    def stop(self):
        # Não retorna False: isso cancelaria o fechamento no pywebview.
        self.stopping.set()

    def attach(self, window):
        window.events.closing += self.stop
        window.events.closed += self.stop
        window.events.before_show += lambda: self._install_qt_bridge(window)

    def _install_qt_bridge(self, window):
        """Compatibilidade com a espera sem timeout do pywebview 6.2 / Qt.

        O Qt pode parar antes de responder ao último callback de uma API.
        A thread desse callback não é daemon e mantém o Python aberto.
        Preservamos o protocolo do Qt, mas paramos de esperar ao fechar.
        O backend Edge/WebView2 do Windows continua usando sua própria ponte.
        """
        if getattr(window.gui, "renderer", "") not in {"qtwebengine", "qtwebkit"}:
            return
        native = window.native
        if not all(hasattr(native, name) for name in ("_js_results", "evaluate_js_trigger")):
            raise RuntimeError("A ponte Qt mudou; revise a compatibilidade do fechamento do Shadow.")

        def evaluate_js(script, parse_json):
            if self.stopping.is_set():
                return None
            request_id = uuid4().hex
            ready = threading.Semaphore(0)
            pending = {"semaphore": ready, "result": "", "parse_json": parse_json}
            native._js_results[request_id] = pending
            try:
                if self.stopping.is_set():
                    return None
                native.evaluate_js_trigger.emit(script, request_id)
                while not self.stopping.is_set():
                    if ready.acquire(timeout=0.05):
                        return deepcopy(pending["result"])
                return None
            finally:
                # Durante o fechamento, um último callback do Qt ainda pode
                # consultar esta entrada. Ela será liberada com a janela.
                if not self.stopping.is_set():
                    native._js_results.pop(request_id, None)

        native.evaluate_js = evaluate_js
