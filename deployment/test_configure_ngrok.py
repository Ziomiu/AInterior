import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import configure_ngrok


class NgrokConfigurationTests(unittest.TestCase):
    def test_port_80_writes_a_private_config_without_printing_the_token(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            Path, "home", return_value=Path(directory)
        ), patch("sys.argv", ["configure_ngrok.py", "--url", "https://example.ngrok-free.dev", "--port", "80"]), patch.object(
            configure_ngrok.getpass, "getpass", return_value="unit-test-placeholder"
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            configure_ngrok.main()
            path = Path(directory) / ".config/ainterior-ngrok/ngrok.yml"
            config = json.loads(path.read_text())
            self.assertEqual(config["endpoints"][0]["upstream"]["url"], "http://127.0.0.1:80")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(config["agent"]["inspect_db_size"], -1)
            self.assertIs(config["agent"]["web_addr"], False)
            self.assertNotIn("unit-test-placeholder", output.getvalue())

    def test_invalid_ports_are_rejected_before_requesting_a_secret(self):
        for port in ("0", "65536"):
            with self.subTest(port=port), patch("sys.argv", [
                "configure_ngrok.py", "--url", "https://example.ngrok-free.dev", "--port", port,
            ]), patch.object(configure_ngrok.getpass, "getpass") as prompt, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    configure_ngrok.main()
                prompt.assert_not_called()