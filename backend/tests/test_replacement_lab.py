import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class LabRunnerTests(unittest.TestCase):
    def test_secret_is_private_and_persists_across_restarts(self):
        source = Path(__file__).resolve().parents[1] / "run_replacement_lab.py"
        spec = importlib.util.spec_from_file_location("lab_runner_under_test", source)
        runner = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "dotenv": SimpleNamespace(dotenv_values=lambda path: {"MONGO_URL": "mongodb://mongo:27017"}),
            "uvicorn": SimpleNamespace(run=Mock()),
        }):
            spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(sys, "argv", ["run_replacement_lab.py", "--mongo-env", "unused"]):
            runner.__file__ = str(Path(directory) / "backend/run_replacement_lab.py")
            runner.main()
            secret = os.environ["SECRET_KEY"]
            runner.main()
            self.assertEqual(os.environ["SECRET_KEY"], secret)
            self.assertEqual(os.environ["MONGO_DATABASE"], "ainterior_replacement_lab")
            self.assertEqual(os.environ["MONGO_URL"], "mongodb://127.0.0.1:27017")
            key_path = Path(directory) / "furniture-replace-service/data/lab-jwt.key"
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(runner.uvicorn.run.call_args.kwargs["access_log"])


if __name__ == "__main__":
    unittest.main()