"""Regressões seguras: arquivos temporários e Windows simulado, sem ajustes reais."""
import json
import os
import tempfile
import time
import unittest
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import game_preparation as gp
import hardware_telemetry as ht
import optimizations as opt
import ui_settings as settings


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            self.assertTrue(settings.save_settings({'lightweight': True, 'interval_seconds': 3}, path)['success'])
            self.assertTrue(settings.load_settings(path)['lightweight'])
            for value in ({'interval_seconds': True}, {'effects': 'fast'}, {'show_intro': 'yes'}, []):
                self.assertFalse(settings.save_settings(value, path)['success'])
            self.assertEqual(settings.load_settings(path)['interval_seconds'], 3)
            path.write_text('{')
            self.assertEqual(settings.load_settings(path), settings.DEFAULTS)

    def test_atomic_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            settings.atomic_json(path, {'old': True})
            with patch.object(settings.os, 'replace', side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    settings.atomic_json(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(len(list(Path(folder).iterdir())), 1)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.prep = gp.GamePreparation(self.temp.name)
        self.active = 'a'
        self.calls = []
        for name, value in [('detect_games', lambda: {'games': [{'id': 'game', 'name': 'Test'}]}),
                            ('power_plan_overview', self.overview), ('activate_power_plan', self.activate),
                            ('record_action', lambda *a, **k: {'id': 'test'}), ('mark_action_undone', lambda *a: None)]:
            p = patch.object(gp, name, value); p.start(); self.addCleanup(p.stop)
        self.assertTrue(self.prep.save('game', 'b', [True, False, True])['success'])

    def overview(self):
        return {'supported': True, 'plans': [{'guid': g, 'name': g, 'active': g == self.active} for g in ('a', 'b', 'c')]}

    def activate(self, guid):
        self.assertTrue((Path(self.temp.name) / 'game_session.json').exists())
        self.calls.append(guid); self.active = guid
        return {'success': True}

    def apply(self):
        review = self.prep.review('game')
        return self.prep.apply(review['token'])

    def test_apply_and_restore_after_restart(self):
        self.assertTrue(self.apply()['success'])
        self.assertEqual(self.active, 'b')
        self.assertTrue(gp.GamePreparation(self.temp.name).restore()['success'])
        self.assertEqual(self.calls, ['b', 'a'])
        self.assertFalse(self.prep.overview('game')['session']['active'])

    def test_stale_confirmation_does_not_change_plan(self):
        token = self.prep.review('game')['token']; self.active = 'c'
        self.assertFalse(self.prep.apply(token)['success'])
        self.assertEqual(self.calls, [])

    def test_backup_failure_prevents_change(self):
        token = self.prep.review('game')['token']
        with patch.object(gp, 'atomic_json', side_effect=OSError('disk full')):
            self.assertFalse(self.prep.apply(token)['success'])
        self.assertEqual(self.calls, [])

    def test_foreign_change_preserved(self):
        self.apply(); self.active = 'c'
        self.assertFalse(self.prep.restore()['success'])
        self.assertEqual(self.active, 'c')
        self.assertTrue(self.prep.overview('game')['session']['active'])

    def test_corrupt_backup_blocks_application(self):
        (Path(self.temp.name) / 'game_session.json').write_text('{')
        self.assertFalse(self.prep.review('game')['success'])
        self.assertEqual(self.calls, [])

    def test_confirmation_single_use_and_expiration(self):
        token = self.prep.review('game')['token']; self.prep.preview['expires'] = 0
        self.assertFalse(self.prep.apply(token)['success'])
        token = self.prep.review('game')['token']
        self.assertTrue(self.prep.apply(token)['success'])
        self.assertFalse(self.prep.apply(token)['success'])
        self.assertEqual(self.calls, ['b'])

    def test_keep_and_invalid_checklist(self):
        self.assertFalse(self.prep.save('game', 'b', [1, 0, 1])['success'])
        self.prep.save('game', 'keep', [False]*3)
        self.assertFalse(self.prep.review('game')['changed'])
        self.assertEqual(self.calls, [])


class CleanupTests(unittest.TestCase):
    def test_only_selected_old_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('old', 'keep', 'recent'):
                (root / name).write_text('data')
            for name in ('old', 'keep'):
                os.utime(root / name, (0, 0))
            with patch.object(opt, '_safe_temp_root', return_value=root):
                result = opt.clean_temp_files(['old', 'recent', '../outside'])
            self.assertEqual(result['removed_count'], 1)
            self.assertTrue((root / 'keep').exists())
            self.assertTrue((root / 'recent').exists())

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'temp'; root.mkdir()
            target = Path(folder) / 'outside'; target.write_text('keep'); os.utime(target, (0, 0))
            try:
                (root / 'link').symlink_to(target)
            except OSError:
                self.skipTest('Sistema sem permissão para symlink')
            self.assertEqual(list(opt._old_temp_files(root, time.time())), [])
            self.assertTrue(target.exists())

    def test_reparse_point_detected(self):
        fake = SimpleNamespace(lstat=lambda: SimpleNamespace(st_file_attributes=0x400), is_symlink=lambda: False)
        self.assertTrue(opt._is_redirected(fake))


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.registry = {'App': ('%APPDATA%/app.exe', 2)}
        self.backup = {}
        def query(key, name):
            if name not in self.registry: raise FileNotFoundError(name)
            return self.registry[name]
        def store(key, name, reserved, kind, command): self.registry[name] = (command, kind)
        fake = SimpleNamespace(HKEY_CURRENT_USER=1, KEY_READ=1, KEY_WRITE=2, REG_SZ=1, REG_EXPAND_SZ=2,
            OpenKey=lambda *args: nullcontext('key'), QueryValueEx=query, SetValueEx=store,
            DeleteValue=lambda key, name: self.registry.pop(name))
        for p in (patch.dict('sys.modules', {'winreg': fake}), patch.object(opt, 'os', SimpleNamespace(name='nt')),
                  patch.object(opt, '_read_startup_backup', lambda: deepcopy(self.backup)),
                  patch.object(opt, '_write_startup_backup', self.write)):
            p.start(); self.addCleanup(p.stop)

    def write(self, value): self.backup = deepcopy(value)

    def test_disable_restore_preserves_command_type(self):
        self.assertTrue(opt.set_startup_enabled('App', False)['success'])
        self.assertNotIn('App', self.registry)
        self.assertTrue(opt.set_startup_enabled('App', True)['success'])
        self.assertEqual(self.registry['App'], ('%APPDATA%/app.exe', 2))
        self.assertEqual(self.backup, {})

    def test_backup_failure_preserves_registry(self):
        with patch.object(opt, '_write_startup_backup', side_effect=OSError('disk full')):
            self.assertFalse(opt.set_startup_enabled('App', False)['success'])
        self.assertIn('App', self.registry)

    def test_foreign_entry_not_overwritten(self):
        opt.set_startup_enabled('App', False); self.registry['App'] = ('new.exe', 1)
        self.assertFalse(opt.set_startup_enabled('App', True)['success'])
        self.assertEqual(self.registry['App'], ('new.exe', 1))
        self.assertIn('App', self.backup)


class TelemetryTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        for value in ('N/A', '[Not Supported]', 'nan', 'inf', -1, None):
            self.assertIsNone(ht.number(value))
        self.assertEqual(ht.number(0), 0)

    def test_nvidia_parsing(self):
        with patch.object(ht, 'find_nvidia_smi', return_value='nvidia-smi'), patch.object(ht, '_run', return_value=SimpleNamespace(returncode=0, stdout='0, GPU, 0, N/A, 10, 100\nmalformed\n')):
            gpu = ht.nvidia_sensors()[0]
        self.assertEqual(gpu['usage_percent'], 0)
        self.assertIsNone(gpu['temperature_c'])

    def test_lhm_parsing(self):
        gpus, temperatures = ht.parse_lhm([{'Parent':'/gpu-amd/0', 'Name':'GPU Core', 'SensorType':'Load', 'Value':42}, {'Parent':'/cpu/0', 'Name':'CPU Package', 'SensorType':'Temperature', 'Value':60}])
        self.assertEqual(gpus[0]['usage_percent'], 42)
        self.assertEqual(temperatures[0]['temperature_c'], 60)

    def test_cache_copied_and_queries_shared(self):
        with patch.object(ht, 'nvidia_sensors', return_value=[]) as query, patch.object(ht, 'linux_sensors', return_value=([], [])), patch.object(ht, 'windows_sensors', return_value=([], [])):
            sampler = ht.Telemetry(); first = sampler.hardware(); first['notes'].append('changed')
            self.assertEqual(sampler.hardware()['notes'], [])
            self.assertEqual(query.call_count, 1)


class PerformanceStorageTests(unittest.TestCase):
    def test_sensor_timestamp_and_temperatures_persist(self):
        from performance_lab import save_result, load_history
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.json'
            sample = {'elapsed': 3, 'cpu_percent': 10, 'ram_percent': 40, 'gpu_percent': None,
                      'gpu_measured_at': 123, 'temperatures': [{'name':'CPU', 'source':'test', 'temperature_c':50}]}
            result = save_result({'success':True}, 'steam:123', 'Test', 'normal', 'before', [sample], path)
            self.assertTrue(result['success'])
            saved = load_history(path)[0]['system']['samples'][0]
            self.assertEqual(saved['gpu_measured_at'], 123)
            self.assertEqual(saved['temperatures'][0]['temperature_c'], 50)
            self.assertIsNone(saved['gpu_percent'])


class WindowsActionTests(unittest.TestCase):
    def test_unknown_power_plan_cannot_be_applied(self):
        with patch.object(opt, 'os', SimpleNamespace(name='nt')), patch.object(opt, 'power_plan_overview', return_value={'supported': True, 'plans': []}), patch.object(opt.subprocess, 'run') as run:
            self.assertFalse(opt.activate_power_plan('381b4222-f694-41f0-9685-ff5bb260df2e')['success'])
            run.assert_not_called()

    def test_power_plan_timeout_reported(self):
        guid = '381b4222-f694-41f0-9685-ff5bb260df2e'
        with patch.object(opt, 'os', SimpleNamespace(name='nt')), patch.object(opt, 'power_plan_overview', return_value={'supported': True, 'plans': [{'guid':guid}]}), patch.object(opt.subprocess, 'run', side_effect=opt.subprocess.TimeoutExpired('powercfg', 8)):
            self.assertFalse(opt.activate_power_plan(guid)['success'])

    def test_pid_reuse_and_system_process_are_blocked(self):
        import main
        from unittest.mock import Mock
        process = Mock(); process.name.return_value = 'app.exe'; process.create_time.return_value = 20
        with patch.object(main.psutil, 'Process', return_value=process):
            self.assertFalse(main.terminate_user_process(999999, 'app.exe', 10)['success'])
            process.name.return_value = 'svchost.exe'
            self.assertFalse(main.terminate_user_process(999999, 'svchost.exe', 20)['success'])
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_history_preserves_plan_changed_elsewhere(self):
        import app_webview as app
        with patch.object(app, 'find_action', return_value={'kind':'power_plan', 'reversible':True, 'undo_data':{'previous_guid':'a', 'expected_guid':'b'}}), patch.object(app, 'power_plan_overview', return_value={'supported':True, 'plans':[{'guid':'c', 'active':True}]}), patch.object(app, 'activate_power_plan') as activate:
            self.assertFalse(app.ShadowApi().undo_history_action('test')['success'])
            activate.assert_not_called()


if __name__ == '__main__': unittest.main()
