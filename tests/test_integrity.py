from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from django.conf import settings

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

import fileresponse.http as http
from test_middleware import compress
from test_s3 import FakeBody, FakeClient, FakeSession, OVERRIDES


class IntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_s3_short_or_extra_source_refuses_successful_terminal_body(self):
        for actual in (b"short", b"too long"):
            for compressed in (False, True):
                with self.subTest(actual=actual, compressed=compressed):
                    body = FakeBody()
                    body.data = actual
                    client = FakeClient(body)

                    async def get_object(**kwargs):
                        return {"Body": body, "ContentLength": 6}

                    client.get_object = get_object
                    response = http.AiobotocoreFileResponse("bucket", "key", chunk_size=2, **OVERRIDES)
                    if compressed:
                        response = compress(response)
                    messages = []

                    async def send(message):
                        messages.append(message)

                    with patch.object(http, "get_session", return_value=FakeSession(client)):
                        with self.assertRaisesRegex(OSError, "Source length mismatch"):
                            await response.stream(send)
                    self.assertEqual(messages[0]["type"], "http.response.start")
                    self.assertFalse(any(m.get("more_body") is False for m in messages))
                    self.assertTrue(body.exited)
                    self.assertTrue(client.exited)

    async def test_local_file_shrunk_or_grown_after_admission_refuses_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            for actual in (b"short", b"too long"):
                path.write_bytes(b"source")
                response = http.AiofileFileResponse(path, chunk_size=2)
                messages = []

                async def send(message):
                    messages.append(message)
                    if message["type"] == "http.response.start":
                        path.write_bytes(actual)

                with self.assertRaisesRegex(OSError, "Source length mismatch"):
                    await response.stream(send)
                self.assertEqual(dict(messages[0]["headers"])[b"content-length"], b"6")
                self.assertFalse(any(m.get("more_body") is False for m in messages))

    async def test_expected_source_length_is_independent_of_explicit_http_length(self):
        body = FakeBody()
        client = FakeClient(body)

        async def get_object(**kwargs):
            return {"Body": body, "ContentLength": 17}

        client.get_object = get_object
        response = http.AiobotocoreFileResponse(
            "bucket", "key", headers={"Content-Length": "16"}, **OVERRIDES,
        )
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(http, "get_session", return_value=FakeSession(client)):
            with self.assertRaisesRegex(OSError, "Source length mismatch"):
                await response.stream(send)
        self.assertFalse(any(m.get("more_body") is False for m in messages))

    async def test_wrapper_that_does_not_consume_source_cannot_claim_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic")
            response = http.AiofileFileResponse(path)

            async def replaced():
                yield b"replacement"

            response.streaming_content = replaced()
            messages = []

            async def send(message):
                messages.append(message)

            with self.assertRaisesRegex(OSError, "Source length mismatch"):
                await response.stream(send)
            self.assertFalse(any(m.get("more_body") is False for m in messages))

    async def test_empty_source_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.bin"
            path.write_bytes(b"")
            messages = []

            async def send(message):
                messages.append(message)

            await http.AiofileFileResponse(path).stream(send)
        self.assertEqual(dict(messages[0]["headers"])[b"content-length"], b"0")
        self.assertEqual(messages[-1], {"type": "http.response.body", "body": b"", "more_body": False})
