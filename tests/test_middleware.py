import asyncio
import gzip
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from django.conf import settings
from django.http import HttpRequest, StreamingHttpResponse
from django.middleware.gzip import GZipMiddleware

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

import fileresponse.http as http
from fileresponse.handlers import AsyncFileASGIHandler


def compress(response):
    request = HttpRequest()
    request.META["HTTP_ACCEPT_ENCODING"] = "gzip"
    middleware = GZipMiddleware(lambda request: response)
    middleware.max_random_bytes = 0
    return middleware.process_response(request, response)


class SyntheticStream:
    def __init__(self, failure=None):
        self.data = b"synthetic content" * 10
        self.failure = failure
        self.entered = False
        self.exited = False
        self.reading = asyncio.Event()

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *args):
        self.exited = True

    async def read(self, size):
        self.reading.set()
        if self.failure == "read":
            raise OSError("synthetic read failure")
        if self.failure == "cancel":
            await asyncio.Event().wait()
        result, self.data = self.data[:size], self.data[size:]
        return result


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_gzip_filesystem_via_both_entry_points(self):
        data = bytes(range(251)) * 20
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(data)
            for use_handler in (True, False):
                with self.subTest(use_handler=use_handler):
                    response = http.AiofileFileResponse(path, chunk_size=73)
                    self.assertIsInstance(response, StreamingHttpResponse)
                    self.assertTrue(response.is_async)
                    response = compress(response)
                    messages = []

                    async def send(message):
                        messages.append(message)

                    if use_handler:
                        await AsyncFileASGIHandler().send_response(response, send)
                    else:
                        await response.stream(send)
                    headers = dict(messages[0]["headers"])
                    self.assertEqual(headers[b"content-encoding"], b"gzip")
                    self.assertEqual(gzip.decompress(b"".join(m["body"] for m in messages[1:])), data)
                    self.assertFalse(messages[-1]["more_body"])

    async def test_s3_gzip(self):
        body = SyntheticStream()
        expected = body.data
        client = SyntheticStream()

        async def get_object(**kwargs):
            return {"Body": body}

        client.get_object = get_object
        session = SimpleNamespace(create_client=lambda *args, **kwargs: client)
        response = http.AiobotocoreFileResponse(
            "bucket", "key", chunk_size=7, endpoint_url="https://synthetic.invalid",
            region_name="test", aws_access_key_id="synthetic", secret_access_key="synthetic",
        )
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(http, "get_session", return_value=session):
            await AsyncFileASGIHandler().send_response(compress(response), send)
        self.assertEqual(gzip.decompress(b"".join(m["body"] for m in messages[1:])), expected)
        self.assertTrue(body.exited)
        self.assertTrue(client.exited)

    async def test_wrapped_stream_failures_close_filesystem_and_s3_resources(self):
        for adapter in ("filesystem", "s3"):
            for failure in ("read", "send", "cancel"):
                with self.subTest(adapter=adapter, failure=failure):
                    body = SyntheticStream(failure)
                    client = SyntheticStream()

                    async def get_object(**kwargs):
                        return {"Body": body}

                    client.get_object = get_object
                    session = SimpleNamespace(create_client=lambda *args, **kwargs: client)
                    if adapter == "filesystem":
                        response = http.AiofileFileResponse("unused", chunk_size=7)
                    else:
                        response = http.AiobotocoreFileResponse(
                            "bucket", "key", chunk_size=7,
                            endpoint_url="https://synthetic.invalid", region_name="test",
                            aws_access_key_id="synthetic", secret_access_key="synthetic",
                        )
                    # Use real GZipMiddleware on errors/cancellation and a
                    # plain transforming wrapper on send failure.
                    if failure != "send":
                        response = compress(response)
                    else:
                        content = response.streaming_content

                        async def wrapped(content=content):
                            async for chunk in content:
                                yield chunk.upper()

                        response.streaming_content = wrapped()

                    async def send(message):
                        if failure == "send" and message.get("body"):
                            raise OSError("synthetic send failure")

                    with patch.object(http.aiofiles, "open", return_value=body), patch.object(
                        http, "get_session", return_value=session
                    ):
                        if failure == "cancel":
                            task = asyncio.create_task(AsyncFileASGIHandler().send_response(response, send))
                            try:
                                await asyncio.wait_for(body.reading.wait(), timeout=5)
                            finally:
                                task.cancel()
                                with self.assertRaises(asyncio.CancelledError):
                                    await task
                        else:
                            with self.assertRaisesRegex(OSError, f"synthetic {failure} failure"):
                                await AsyncFileASGIHandler().send_response(response, send)
                    self.assertTrue(body.entered)
                    self.assertTrue(body.exited)
                    if adapter == "s3":
                        self.assertTrue(client.exited)

    async def test_wrapped_content_is_sent_with_backpressure(self):
        body = SyntheticStream()
        response = http.AiofileFileResponse("unused", chunk_size=7)
        content = response.streaming_content

        async def wrapped():
            async for chunk in content:
                yield chunk.upper()

        response.streaming_content = wrapped()
        blocked = asyncio.Event()
        release = asyncio.Event()
        messages = []

        async def send(message):
            messages.append(message)
            if message.get("body") and not release.is_set():
                blocked.set()
                await release.wait()

        expected = body.data.upper()
        with patch.object(http.aiofiles, "open", return_value=body):
            task = asyncio.create_task(AsyncFileASGIHandler().send_response(response, send))
            try:
                await asyncio.wait_for(blocked.wait(), timeout=5)
                self.assertEqual(len(body.data), len(expected) - 7)
            finally:
                release.set()
                await asyncio.wait_for(task, timeout=5)
        self.assertEqual(b"".join(m["body"] for m in messages[1:]), expected)
        self.assertTrue(body.exited)

    async def test_legacy_adapter_helper_sends_middleware_wrapped_content(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                body = SyntheticStream()
                expected = body.data

                class LegacyResponse(http.AsyncResponse):
                    async def stream(self, send):
                        async with body:
                            await self.send_stream_to_client(body, send)

                response = LegacyResponse(chunk_size=7)
                if compressed:
                    response = compress(response)
                messages = []

                async def send(message):
                    messages.append(message)

                await AsyncFileASGIHandler().send_response(response, send)
                payload = b"".join(m["body"] for m in messages[1:])
                if compressed:
                    self.assertEqual(dict(messages[0]["headers"])[b"content-encoding"], b"gzip")
                    payload = gzip.decompress(payload)
                self.assertEqual(payload, expected)
                self.assertTrue(body.exited)

    async def test_raw_stream_helper_on_builtin_response_uses_supplied_stream(self):
        body = SyntheticStream()
        expected = body.data
        response = compress(http.AiofileFileResponse("unused", chunk_size=7))
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(http.aiofiles, "open", side_effect=AssertionError("unexpected open")):
            async with body:
                await response.send_stream_to_client(body, send)
        self.assertEqual(gzip.decompress(b"".join(m["body"] for m in messages[1:])), expected)
        self.assertTrue(body.exited)
