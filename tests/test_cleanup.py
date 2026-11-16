import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from django.conf import settings

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

import fileresponse.http as http
from test_s3 import FakeBody, FakeClient, FakeSession, OVERRIDES


class FailingWrapper:
    def __init__(self, content, events, name="iterator"):
        self.content = aiter(content)
        self.events = events
        self.name = name

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await anext(self.content)

    async def aclose(self):
        self.events.append(self.name)
        raise RuntimeError("synthetic private iterator close details")


class CleanupBody(FakeBody):
    def __init__(self, events, primary=None, reading=None):
        super().__init__()
        self.events = events
        self.primary = primary
        self.reading = reading

    async def read(self, size):
        if self.reading is not None:
            self.reading.set()
            await asyncio.Event().wait()
        if self.primary is not None:
            raise self.primary
        return await super().read(size)

    async def __aexit__(self, *args):
        self.events.append("body")
        raise ValueError("synthetic private body close details")


class CleanupClient(FakeClient):
    def __init__(self, body, events):
        super().__init__(body)
        self.events = events

    async def __aexit__(self, *args):
        self.events.append("client")
        raise LookupError("synthetic private client close details")


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_and_send_primary_identity_survives_all_owned_close_failures(self):
        for failure in ("read", "send", "headers"):
            with self.subTest(failure=failure):
                primary = OSError("synthetic primary " + failure)
                events = []
                body = CleanupBody(events, primary if failure == "read" else None)
                client = CleanupClient(body, events)
                response = http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES)
                # Two wrappers that do not forward aclose to their sources.
                response.streaming_content = FailingWrapper(response.streaming_content, events, "inner")
                response.streaming_content = FailingWrapper(response.streaming_content, events, "outer")

                async def send(message):
                    if failure == "headers" or failure == "send" and message.get("body"):
                        raise primary

                with patch.object(http, "get_session", return_value=FakeSession(client)):
                    with self.assertRaises(OSError) as raised:
                        await response.stream(send)
                self.assertIs(raised.exception, primary)
                self.assertEqual(events, ["outer", "inner", "body", "client"])
                notes = primary.__notes__
                self.assertEqual(len(notes), 4)
                self.assertTrue(all("Response cleanup failed" in note for note in notes))
                self.assertTrue(all("private" not in note for note in notes))

    async def test_cancellation_identity_survives_body_client_and_iterator_close_errors(self):
        events = []
        reading = asyncio.Event()
        body = CleanupBody(events, reading=reading)
        client = CleanupClient(body, events)
        response = http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES)
        response.streaming_content = FailingWrapper(response.streaming_content, events)

        async def send(message):
            pass

        with patch.object(http, "get_session", return_value=FakeSession(client)):
            task = asyncio.create_task(response.stream(send))
            await asyncio.wait_for(reading.wait(), 2)
            task.cancel("synthetic cancellation")
            with self.assertRaises(asyncio.CancelledError) as raised:
                await task
        self.assertEqual(raised.exception.args, ("synthetic cancellation",))
        self.assertEqual(events, ["iterator", "body", "client"])
        self.assertEqual(len(raised.exception.__notes__), 3)

    async def test_standalone_cleanup_failure_is_propagated_and_other_closes_attempted(self):
        events = []
        body = CleanupBody(events)
        client = CleanupClient(body, events)
        response = http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES)
        response.streaming_content = FailingWrapper(response.streaming_content, events)

        async def send(message):
            pass

        with patch.object(http, "get_session", return_value=FakeSession(client)):
            with self.assertRaisesRegex(RuntimeError, "synthetic private iterator close details") as raised:
                await response.stream(send)
        self.assertEqual(events, ["iterator", "body", "client"])
        self.assertEqual(len(raised.exception.__notes__), 2)

    async def test_source_iterator_close_failure_does_not_replace_send_failure(self):
        events = []
        primary = OSError("synthetic primary send")

        class CustomResponse(http.AsyncResponse):
            async def _stream_content(self):
                try:
                    yield b"synthetic"
                finally:
                    events.append("source")
                    raise RuntimeError("synthetic source cleanup")

        response = CustomResponse()

        async def send(message):
            if message.get("body"):
                raise primary

        with self.assertRaises(OSError) as raised:
            await response.stream(send)
        self.assertIs(raised.exception, primary)
        self.assertEqual(events, ["source"])
        self.assertEqual(len(primary.__notes__), 1)

    async def test_acquisition_failure_survives_client_close_error_before_headers(self):
        events = []
        primary = FileNotFoundError("synthetic missing key")
        client = CleanupClient(FakeBody(), events)

        async def get_object(**kwargs):
            raise primary

        client.get_object = get_object
        response = http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES)
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(http, "get_session", return_value=FakeSession(client)):
            with self.assertRaises(FileNotFoundError) as raised:
                await response.stream(send)
        self.assertIs(raised.exception, primary)
        self.assertEqual(events, ["client"])
        self.assertEqual(messages, [])
        self.assertEqual(len(primary.__notes__), 1)

    async def test_local_body_and_descriptor_close_errors_preserve_read_failure(self):
        events = []
        primary = OSError("synthetic primary read")
        body = CleanupBody(events, primary=primary)
        real_close = os.close

        def close(descriptor):
            real_close(descriptor)
            events.append("descriptor")
            raise RuntimeError("synthetic descriptor close failure")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic")
            response = http.AiofileFileResponse(path)

            async def send(message):
                pass

            with patch.object(http.aiofiles, "open", return_value=body), patch.object(http.os, "close", side_effect=close):
                with self.assertRaises(OSError) as raised:
                    await response.stream(send)
        self.assertIs(raised.exception, primary)
        self.assertEqual(events, ["body", "descriptor"])
        self.assertEqual(len(primary.__notes__), 2)
