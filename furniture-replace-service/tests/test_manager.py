import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_manager():
    source = Path(__file__).resolve().parents[1] / "app/models/manager.py"
    spec = importlib.util.spec_from_file_location("manager_under_test", source)
    module = importlib.util.module_from_spec(spec)
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, empty_cache=Mock()))
    config = SimpleNamespace(settings=SimpleNamespace(device="cuda", model_idle_offload_seconds=1, max_loaded_heavy_models=2))
    with patch.dict(sys.modules, {"torch": torch, "app.config": config, spec.name: module}):
        spec.loader.exec_module(module)
    return module


class ManagerTests(unittest.TestCase):
    def test_reaper_skips_model_during_inference(self):
        manager = load_manager().ModelManager()
        move = Mock(side_effect=lambda model, device: model)
        manager.register("lama", Mock(return_value=object()), move)
        with manager.use("lama"):
            manager._registry["lama"].last_used = 0
            reaper = threading.Thread(target=manager.idle_reaper_tick)
            reaper.start()
            reaper.join(timeout=1)
            self.assertFalse(reaper.is_alive())
            self.assertEqual(manager._registry["lama"].device, "gpu")
        manager.idle_reaper_tick()
        self.assertEqual(manager._registry["lama"].device, "cpu")

    def test_switch_keeps_only_one_heavy_model_on_gpu(self):
        manager = load_manager().ModelManager()
        for name in ("lama", "brushnet"):
            manager.register(name, Mock(return_value=object()), lambda model, device: model)
        with manager.use("lama"):
            pass
        with manager.use("brushnet"):
            self.assertEqual(manager._registry["lama"].device, "cpu")
            self.assertEqual(manager._registry["brushnet"].device, "gpu")

    def test_load_failure_releases_inference_lock(self):
        manager = load_manager().ModelManager()
        manager.register("lama", Mock(side_effect=RuntimeError("load failed")), Mock())
        with self.assertRaisesRegex(RuntimeError, "load failed"):
            with manager.use("lama"):
                pass
        self.assertTrue(manager._inference_lock.acquire(blocking=False))
        manager._inference_lock.release()

    def test_heavy_cache_evicts_oldest_before_loading_and_keeps_clip(self):
        manager = load_manager().ModelManager()
        loaders = {}
        for name in ("clip", "segmenter", "brushnet", "prompt_quality"):
            loaders[name] = Mock(side_effect=object)
            manager.register(name, loaders[name], lambda model, device: model)
        for name in ("clip", "segmenter", "brushnet"):
            with manager.use(name):
                pass
        manager._registry["segmenter"].last_used = 0
        manager._registry["brushnet"].last_used = 1

        def load_quality():
            self.assertIsNone(manager._registry["segmenter"].instance)
            self.assertIsNotNone(manager._registry["clip"].instance)
            return object()

        loaders["prompt_quality"].side_effect = load_quality
        with manager.use("prompt_quality"):
            self.assertEqual(manager._registry["segmenter"].device, "not_loaded")
            self.assertEqual(manager._registry["brushnet"].device, "cpu")
            self.assertEqual(manager._registry["prompt_quality"].device, "gpu")
        loaders["prompt_quality"].side_effect = object
        with manager.use("segmenter"):
            pass
        self.assertEqual(loaders["segmenter"].call_count, 2)
        self.assertEqual(loaders["clip"].call_count, 1)

    def test_single_model_limit_releases_previous_gpu_model(self):
        module = load_manager()
        module.settings.max_loaded_heavy_models = 1
        manager = module.ModelManager()
        for name in ("brushnet", "prompt_quality"):
            manager.register(name, Mock(side_effect=object), lambda model, device: model)
        with manager.use("brushnet"):
            pass
        with manager.use("prompt_quality"):
            self.assertIsNone(manager._registry["brushnet"].instance)
            self.assertEqual(manager._registry["brushnet"].device, "not_loaded")
            self.assertEqual(manager._current_heavy_on_gpu, "prompt_quality")

    def test_inference_failure_releases_inference_lock(self):
        manager = load_manager().ModelManager()
        manager.register("lama", Mock(return_value=object()), lambda model, device: model)
        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            with manager.use("lama"):
                raise RuntimeError("inference failed")
        self.assertTrue(manager._inference_lock.acquire(blocking=False))
        manager._inference_lock.release()


if __name__ == "__main__":
    unittest.main()