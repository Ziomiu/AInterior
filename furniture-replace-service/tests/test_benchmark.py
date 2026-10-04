import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_benchmark():
    source = Path(__file__).resolve().parents[1] / "scripts/benchmark.py"
    spec = importlib.util.spec_from_file_location("benchmark_under_test", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "numpy": Mock(), "requests": Mock(),
        "PIL": SimpleNamespace(Image=Mock(), ImageOps=Mock()),
        "app.utils.images": SimpleNamespace(dilate_mask=Mock()),
    }):
        spec.loader.exec_module(module)
    return module


class BenchmarkTests(unittest.TestCase):
    def test_repeated_points_are_preserved(self):
        args = load_benchmark().build_parser().parse_args([
            "scene.png", "--point", "820", "760", "--point", "715", "855",
        ])
        self.assertEqual(args.point, [[820, 760], [715, 855]])

    def test_prompt_only_experiment_does_not_request_reference_mode(self):
        args = load_benchmark().build_parser().parse_args([
            "scene.png", "--point", "820", "760", "--modes", "prompt",
        ])
        self.assertEqual(args.modes, ["prompt"])
    def test_gpu_sample_parses_mib_without_units(self):
        module = load_benchmark()
        with patch.object(module.subprocess, "check_output", return_value="5000, 6000, 80\n"):
            self.assertEqual(module.gpu_sample(), {
                "used_mib": 5000, "free_mib": 6000, "utilization_percent": 80,
            })

    def test_done_job_returns_result(self):
        module = load_benchmark()
        session = Mock()
        session.get.return_value.json.return_value = {"status": "done", "result": {"mask_url": "/results/mask.png"}}
        self.assertEqual(module.poll_job(session, "http://test", "job", 10), {"mask_url": "/results/mask.png"})

    def test_failed_job_surfaces_server_error(self):
        module = load_benchmark()
        session = Mock()
        session.get.return_value.json.return_value = {"status": "failed", "error": "CUDA out of memory"}
        with self.assertRaisesRegex(RuntimeError, "CUDA out of memory"):
            module.poll_job(session, "http://test", "job", 10)

    def test_timeout_does_not_claim_server_cancellation(self):
        module = load_benchmark()
        with patch.object(module.time, "monotonic", side_effect=[0, 20]):
            with self.assertRaisesRegex(TimeoutError, "not cancelled"):
                module.poll_job(Mock(), "http://test", "job", 10)


if __name__ == "__main__":
    unittest.main()