import asyncio
import contextlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from django.conf import settings

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

from django.core.handlers.asgi import ASGIHandler

import fileresponse.http as http
from test_s3 import FakeBody, FakeClient, FakeSession, OVERRIDES


async def collect(response):
    return b"".join([chunk async for chunk in response])


class DirectIterationTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_streams_through_django_interface_and_stock_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic payload")
            self.assertEqual(await collect(http.AiofileFileResponse(path, chunk_size=4)), b"synthetic payload")

            messages = []

            async def send(message):
                messages.append(message)

            await ASGIHandler().send_response(http.AiofileFileResponse(path, chunk_size=4), send)
            self.assertEqual(messages[0]["type"], "http.response.start")
            self.assertEqual(b"".join(m.get("body", b"") for m in messages[1:]), b"synthetic payload")
            self.assertFalse(messages[-1].get("more_body", False))

    async def test_s3_streams_through_django_interface_and_closes_contexts(self):
        body = FakeBody()
        client = FakeClient(body)
        with patch.object(http, "get_session", return_value=FakeSession(client)):
            response = http.AiobotocoreFileResponse("bucket", "key", chunk_size=5, **OVERRIDES)
            self.assertEqual(await collect(response), b"synthetic object")
        self.assertTrue(body.exited)
        self.assertTrue(client.exited)

    async def test_direct_iteration_is_the_single_consumer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic")
            response = http.AiofileFileResponse(path)
            self.assertEqual(await collect(response), b"synthetic")
            messages = []

            async def send(message):
                messages.append(message)

            with self.assertRaisesRegex(RuntimeError, "already consumed"):
                await response.stream(send)
            self.assertEqual(messages, [])

    async def test_direct_iteration_checks_admitted_length(self):
        body = FakeBody()
        client = FakeClient(body)

        async def get_object(**kwargs):
            return {"Body": body, "ContentLength": len(body.data) + 1}

        client.get_object = get_object
        with patch.object(http, "get_session", return_value=FakeSession(client)):
            response = http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES)
            with self.assertRaisesRegex(OSError, "early EOF"):
                await collect(response)
        self.assertTrue(body.exited)
        self.assertTrue(client.exited)

    async def test_early_close_releases_s3_contexts_and_middleware_iterators(self):
        body = FakeBody()
        client = FakeClient(body)
        closed = []
        with patch.object(http, "get_session", return_value=FakeSession(client)):
            response = http.AiobotocoreFileResponse("bucket", "key", chunk_size=3, **OVERRIDES)
            source = response.streaming_content

            async def wrapper():
                # Does not forward aclose() to the source it wraps.
                try:
                    async for chunk in source:
                        yield chunk
                finally:
                    closed.append("wrapper")

            response.streaming_content = wrapper()
            async with contextlib.aclosing(aiter(response)) as content:
                self.assertEqual(await anext(content), b"syn")
        self.assertEqual(closed, ["wrapper"])
        self.assertTrue(body.exited)
        self.assertTrue(client.exited)

    async def test_stock_handler_send_failure_closes_local_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic payload")
            closed = []
            real_close = os.close

            def close(descriptor):
                closed.append(descriptor)
                real_close(descriptor)

            async def send(message):
                if message.get("body"):
                    raise OSError("synthetic disconnect")

            with patch.object(http.os, "close", side_effect=close):
                with self.assertRaisesRegex(OSError, "synthetic disconnect"):
                    await ASGIHandler().send_response(http.AiofileFileResponse(path, chunk_size=4), send)
            self.assertEqual(len(closed), 1)

    async def test_direct_iteration_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            response = http.AiofileFileResponse(Path(directory) / "missing")
            with self.assertRaises(FileNotFoundError):
                await collect(response)


class LocalAdmissionThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_local_admission_closes_descriptor_opened_later(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic")
            entered = threading.Event()
            release = threading.Event()
            opened = []
            closed_descriptors = []
            closed = asyncio.Event()
            loop = asyncio.get_running_loop()
            real_open = http._open_regular_file
            real_close = os.close

            def slow_open(target):
                entered.set()
                release.wait(5)
                result = real_open(target)
                opened.append(result[0])
                return result

            def close(descriptor):
                real_close(descriptor)
                closed_descriptors.append(descriptor)
                loop.call_soon_threadsafe(closed.set)

            async def send(message):
                raise AssertionError("no message expected")

            with patch.object(http, "_open_regular_file", side_effect=slow_open), \
                    patch.object(http.os, "close", side_effect=close):
                task = asyncio.create_task(http.AiofileFileResponse(path).stream(send))
                await asyncio.to_thread(entered.wait, 5)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                release.set()
                await asyncio.wait_for(closed.wait(), 5)
            self.assertEqual(len(opened), 1)
            self.assertEqual(closed_descriptors, opened)

    async def test_local_admission_does_not_run_on_event_loop_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic")
            threads = []
            real_open = os.open

            def record_open(*args, **kwargs):
                threads.append(threading.current_thread())
                return real_open(*args, **kwargs)

            async def send(message):
                pass

            with patch.object(http.os, "open", side_effect=record_open):
                await http.AiofileFileResponse(path).stream(send)
            self.assertEqual(len(threads), 1)
            self.assertIsNot(threads[0], threading.main_thread())


if __name__ == "__main__":
    unittest.main()
