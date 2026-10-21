"""Regressões do fechamento, sem abrir uma janela nem alterar o sistema."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from window_lifecycle import WindowLifecycle


class WindowLifecycleTests(unittest.TestCase):
    def make_window(self, reply=None):
        native = SimpleNamespace(_js_results={}, evaluate_js=Mock())
        native.evaluate_js_trigger = SimpleNamespace(emit=reply or Mock())
        window = SimpleNamespace(gui=SimpleNamespace(renderer="qtwebengine"), native=native)
        lifecycle = WindowLifecycle()
        lifecycle._install_qt_bridge(window)
        return lifecycle, native

    def test_normal_response_preserves_result_and_cleans_request(self):
        lifecycle, native = self.make_window()
        result = {"value": [42]}

        def reply(script, request_id):
            pending = native._js_results[request_id]
            self.assertTrue(pending["parse_json"])
            pending["result"] = result
            pending["semaphore"].release()

        native.evaluate_js_trigger.emit = reply
        returned = native.evaluate_js("example()", True)
        self.assertEqual(returned, result)
        self.assertIsNot(returned, result)
        self.assertEqual(native._js_results, {})

    def test_closing_releases_non_daemon_callback_without_qt_response(self):
        lifecycle, native = self.make_window()
        submitted = threading.Event()
        native.evaluate_js_trigger.emit = lambda *_: submitted.set()
        results = []
        worker = threading.Thread(target=lambda: results.append(native.evaluate_js("reply()", True)))
        worker.start()
        try:
            self.assertTrue(submitted.wait(1))
        finally:
            lifecycle.stop()
            worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [None])
        # O callback tardio do Qt ainda encontra seu registro.
        pending = next(iter(native._js_results.values()))
        pending["semaphore"].release()

    def test_no_new_javascript_after_close(self):
        lifecycle, native = self.make_window()
        lifecycle.stop()
        lifecycle.stop()
        self.assertIsNone(native.evaluate_js("reply()", True))
        native.evaluate_js_trigger.emit.assert_not_called()
        self.assertEqual(native._js_results, {})

    def test_emit_error_does_not_leak_request(self):
        lifecycle, native = self.make_window()
        native.evaluate_js_trigger.emit = Mock(side_effect=RuntimeError("Qt unavailable"))
        with self.assertRaises(RuntimeError):
            native.evaluate_js("reply()", True)
        self.assertEqual(native._js_results, {})

    def test_windows_backend_is_unchanged(self):
        original = Mock()
        window = SimpleNamespace(gui=SimpleNamespace(renderer="edgechromium"), native=SimpleNamespace(evaluate_js=original))
        WindowLifecycle()._install_qt_bridge(window)
        self.assertIs(window.native.evaluate_js, original)

    def test_both_native_close_events_stop_lifecycle(self):
        from webview.event import Event

        for event_name in ("closing", "closed"):
            lifecycle = WindowLifecycle()
            window = SimpleNamespace()
            window.events = SimpleNamespace(**{
                name: Event(window, True) for name in ("closing", "closed", "before_show")
            })
            lifecycle.attach(window)
            self.assertFalse(getattr(window.events, event_name).set())
            self.assertTrue(lifecycle.stopping.is_set())


if __name__ == "__main__":
    unittest.main()
