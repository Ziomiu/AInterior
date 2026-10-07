import argparse
import base64
from contextlib import redirect_stdout
import importlib.util
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from uuid import uuid4

from PIL import Image
from pydantic import EmailStr, TypeAdapter


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_integrated.py"
SPEC = importlib.util.spec_from_file_location("evaluate_integrated", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class IntegratedEvaluationTests(unittest.TestCase):
    def test_exact_preservation_detects_one_channel_leak(self):
        original = Image.new("RGB", (9, 9), (12, 34, 56))
        mask = Image.new("L", original.size)
        mask.putpixel((4, 4), 255)
        generated = original.copy()
        generated.putpixel((5, 5), (1, 2, 3))
        check = runner.preservation_check(original, generated, mask, 1)
        self.assertTrue(check["passed"])
        self.assertEqual(check["outside_pixels"], 72)
        generated.putpixel((6, 4), (12, 35, 56))
        check = runner.preservation_check(original, generated, mask, 1)
        self.assertFalse(check["passed"])
        self.assertEqual(check["outside_mask_pixels_changed"], 1)

    def test_dilation_threshold_and_border_match_repeated_square_kernel(self):
        original = Image.new("RGB", (9, 9), "white")
        mask = Image.new("L", original.size)
        mask.putpixel((0, 0), 128)
        mask.putpixel((8, 8), 127)
        self.assertEqual(runner.preservation_check(original, original, mask, 2)["outside_pixels"], 72)
        self.assertEqual(runner.preservation_check(original, original, mask, 0)["outside_pixels"], 80)
        with self.assertRaises(runner.EvaluationError):
            runner.preservation_check(original, original.resize((8, 9)), mask, 1)
        self.assertFalse(runner.preservation_check(original, original, Image.new("L", (9, 9), 255), 1)["passed"])

    def test_account_contract_and_credentials_not_in_metadata(self):
        client = runner.BackendClient("http://127.0.0.1:5556", 10)
        with patch.object(client, "request", side_effect=[{"user_id": "new-user"}, {"access_token": "test-token"}]) as request:
            account = client.create_account()
        registration, login = request.call_args_list
        self.assertEqual(registration.args[:2], ("POST", "/auth/register"))
        self.assertEqual(set(registration.args[2]), {"first_name", "last_name", "email", "password", "role"})
        self.assertEqual(registration.args[2]["role"], "user")
        self.assertTrue(account["email"].endswith("@example.com"))
        self.assertEqual(TypeAdapter(EmailStr).validate_python(registration.args[2]["email"]), account["email"])
        self.assertEqual(login.args[:2], ("POST", "/auth/login"))
        self.assertEqual(set(login.args[2]), {"email", "password"})
        self.assertEqual(login.args[2]["password"], registration.args[2]["password"])
        self.assertEqual(client.token, "test-token")
        self.assertEqual(set(account), {"email", "user_id"})

    def test_http_error_body_is_not_exposed(self):
        client = runner.BackendClient("http://127.0.0.1:5556", 10)
        client.token = "never-print-token"
        client.opener.open = Mock(side_effect=HTTPError(
            client.api + "/auth/login", 401, "secret-password", {}, BytesIO(b"never-print-token")))
        with self.assertRaises(runner.ApiError) as caught:
            client.request("POST", "/auth/login", {"password": "secret-password"})
        self.assertEqual(str(caught.exception), "POST /auth/login: HTTP 401")

    def test_poll_records_actual_stages_timing_and_one_sample_per_poll(self):
        job_id = str(uuid4())
        client = Mock()
        client.request.side_effect = [
            {"job_id": job_id, "status": "queued"},
            {"status": "running", "stage": "generating"},
            {"status": "done", "stage": "done", "result": {"elapsed_seconds": 2.5}},
        ]
        args = argparse.Namespace(timeout=60, poll_interval=0.01, gpu_id=0)
        measurement = {"label": "fixture"}
        with patch.object(runner, "sample_vram", side_effect=[
            {"used_mib": 300, "free_mib": 1000}, {"used_mib": 700, "free_mib": 600},
        ]) as sample, patch.object(runner.time, "sleep"), redirect_stdout(StringIO()):
            result = runner.submit_and_poll(client, "/furniture/replace", {"seed": 0}, measurement, args)
        self.assertEqual(result["elapsed_seconds"], 2.5)
        self.assertEqual(sample.call_count, 2)
        self.assertEqual(measurement["server_elapsed_seconds"], 2.5)
        self.assertEqual(measurement["vram_observed_peak_mib"], 700)
        self.assertEqual([row["stage"] for row in measurement["status_stages"]], [None, "generating", "done"])
        self.assertGreaterEqual(measurement["post_and_poll_wall_seconds"], measurement["post_seconds"])
        self.assertEqual(client.request.call_args_list[-1].args, ("GET", f"/furniture/jobs/{job_id}"))

    def test_cross_user_requires_exact_404(self):
        client = Mock()
        client.request.side_effect = runner.ApiError("GET", "/furniture/jobs/other", 404)
        self.assertTrue(runner.expect_not_found(client, "GET", "/furniture/jobs/other")["passed"])
        client.request.side_effect = runner.ApiError("GET", "/furniture/jobs/other", 401)
        self.assertFalse(runner.expect_not_found(client, "GET", "/furniture/jobs/other")["passed"])

    def test_output_is_service_relative_and_nonfinite_timeout_is_rejected(self):
        parser = runner.build_parser()
        args = parser.parse_args([
            "--scene", "room:/unused.png:1:2", "--output", "data/results/integrated-unit-validation",
            "--confirm-staging", "--confirm-gpu-window",
        ])
        with patch.object(Path, "exists", return_value=False):
            runner.validate_args(parser, args)
        self.assertEqual(args.output, runner.RESULTS_ROOT / "integrated-unit-validation")
        args.timeout = float("nan")
        with patch.object(parser, "error", side_effect=ValueError("invalid timeout")):
            with self.assertRaises(ValueError):
                runner.validate_args(parser, args)

    def test_full_runner_uses_corrected_mask_and_redacted_artifacts(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "integrated-unit"
            output.mkdir()
            original_path = Path(temporary) / "room.png"
            Image.new("RGB", (16, 16), (10, 20, 30)).save(original_path)
            corrected_path = Path(temporary) / "corrected.png"
            corrected = Image.new("L", (16, 16))
            corrected.putpixel((8, 8), 255)
            corrected.save(corrected_path)
            original_payload = base64.b64encode(original_path.read_bytes()).decode("ascii")
            mask_payload = base64.b64encode(corrected_path.read_bytes()).decode("ascii")
            job_ids = [str(uuid4()), str(uuid4()), str(uuid4())]
            classification = {"category": "armchair", "confidence": 0.6}
            client = Mock()
            client.create_account.return_value = {"email": "new@example.test", "user_id": "unit"}
            client.request.side_effect = [
                {"job_id": job_ids[0], "status": "queued"},
                {"status": "done", "result": {"mask": mask_payload, "bbox": [8, 8, 9, 9],
                 "score": 0.8, "classification": classification, "mask_review_required": True}},
                {"job_id": job_ids[1], "status": "queued"},
                {"status": "done", "result": {"image": original_payload, "elapsed_seconds": 1.2}},
                {"job_id": job_ids[2], "status": "queued"},
                {"status": "done", "result": {"image": original_payload, "elapsed_seconds": 1.0}},
            ]
            args = runner.build_parser().parse_args([
                "--scene", f"room:{original_path}:8:8", "--mask", f"room:{corrected_path}",
                "--profiles", "balanced", "--mask-growth", "1", "--output", str(output),
            ])
            args.output = output
            report = {"scenes": []}
            with patch.object(runner, "BackendClient", return_value=client), patch.object(runner, "sample_vram", return_value=None), redirect_stdout(StringIO()):
                runner.evaluate(args, report)
            trials = report["scenes"][0]["trials"]
            self.assertEqual([trial["request"]["seed"] for trial in trials], [0, 42])
            self.assertEqual([trial["thermal_candidate"] for trial in trials], ["cold_candidate", "warm_candidate"])
            self.assertEqual(report["scenes"][0]["classification"], classification)
            self.assertTrue(report["checks_passed"])
            posts = [call for call in client.request.call_args_list if call.args[:2] == ("POST", "/furniture/replace")]
            for call in posts:
                self.assertEqual(call.args[2]["mask_job_id"], job_ids[0])
                self.assertEqual(call.args[2]["mask"], mask_payload)
                self.assertEqual(call.args[2]["image"], original_payload)
                self.assertNotIn("image_url", call.args[2])
            self.assertTrue((output / "room/contact-sheet.png").is_file())
            serialized = json.dumps(report)
            self.assertNotIn(original_payload, serialized)
            self.assertNotIn(mask_payload, serialized)


if __name__ == "__main__":
    unittest.main()