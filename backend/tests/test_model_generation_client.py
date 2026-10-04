import asyncio
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from PIL import Image

from controllers import model


class FakeComfyClient:
    def __init__(self, wait_for_history=False):
        self.history_started = asyncio.Event()
        self.release_history = asyncio.Event()
        if not wait_for_history:
            self.release_history.set()
        self.prompt = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def post(self, url, json):
        self.prompt = json
        return httpx.Response(
            200,
            json={"prompt_id": "test-prompt"},
            request=httpx.Request("POST", url),
        )

    async def get(self, url):
        self.history_started.set()
        await self.release_history.wait()
        return httpx.Response(
            200,
            json={
                "test-prompt": {
                    "outputs": {"9": {"images": [{"filename": "fixture.png"}]}}
                }
            },
            request=httpx.Request("GET", url),
        )


class ComfyGenerationClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)
        Path("output_images").mkdir()
        Image.new("RGB", (2, 1), (24, 80, 140)).save("output_images/fixture.png")

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    async def test_generation_wait_does_not_block_event_loop(self):
        client = FakeComfyClient(wait_for_history=True)
        with patch.object(model, "COMFYUI_URL", "http://comfy.test"), patch.object(
            model.httpx, "AsyncClient", return_value=client
        ):
            task = asyncio.create_task(model.get_image({"node": "test"}))
            await asyncio.wait_for(client.history_started.wait(), timeout=1)

            loop_tick = asyncio.Event()
            asyncio.get_running_loop().call_soon(loop_tick.set)
            await asyncio.wait_for(loop_tick.wait(), timeout=1)

            client.release_history.set()
            image_base64 = await task

        self.assertEqual(client.prompt, {"prompt": {"node": "test"}})
        self.assertTrue(base64.b64decode(image_base64))

    async def test_queue_timeout_returns_gateway_timeout(self):
        class SlowQueueClient(FakeComfyClient):
            async def post(self, url, json):
                await asyncio.sleep(0.1)
                return await super().post(url, json)

        client = SlowQueueClient()
        with patch.object(model, "COMFYUI_QUEUE_TIMEOUT_SECONDS", 0.01), patch.object(
            model.httpx, "AsyncClient", return_value=client
        ):
            with self.assertRaises(HTTPException) as error:
                await model.get_image({"node": "test"})

        self.assertEqual(error.exception.status_code, 504)