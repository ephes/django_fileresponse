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
from fileresponse.handlers import AsyncFileASGIHandler
from test_s3 import FakeBody, FakeClient, FakeSession, OVERRIDES


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_file_and_directory_fail_before_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in (Path(directory) / "missing", Path(directory)):
                with self.subTest(path=path):
                    messages = []

                    async def send(message):
                        messages.append(message)

                    with self.assertRaises(OSError):
                        await AsyncFileASGIHandler().send_response(http.AiofileFileResponse(path), send)
                    self.assertEqual(messages, [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    async def test_fifo_is_refused_before_headers_without_waiting_for_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fifo"
            os.mkfifo(path)
            messages = []

            async def send(message):
                messages.append(message)

            # Check the open policy before allowing a potentially blocking open.
            real_open = os.open

            def bounded_open(path, flags, *args, **kwargs):
                self.assertTrue(flags & os.O_NONBLOCK)
                return real_open(path, flags, *args, **kwargs)

            with patch.object(http.os, "open", side_effect=bounded_open):
                with self.assertRaises(OSError):
                    await asyncio.wait_for(http.AiofileFileResponse(path).stream(send), 2)
            self.assertEqual(messages, [])

    async def test_missing_s3_key_fails_before_headers_and_closes_client(self):
        failure = FileNotFoundError("synthetic missing key")
        client = FakeClient(FakeBody())

        async def get_object(**kwargs):
            raise failure

        client.get_object = get_object
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(http, "get_session", return_value=FakeSession(client)):
            with self.assertRaises(FileNotFoundError) as raised:
                await http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES).stream(send)
        self.assertIs(raised.exception, failure)
        self.assertEqual(messages, [])
        self.assertTrue(client.exited)

    async def test_header_failure_closes_already_admitted_s3_resources(self):
        body = FakeBody()
        client = FakeClient(body)
        failure = RuntimeError("synthetic header failure")

        async def send(message):
            raise failure

        with patch.object(http, "get_session", return_value=FakeSession(client)):
            with self.assertRaises(RuntimeError) as raised:
                await http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES).stream(send)
        self.assertIs(raised.exception, failure)
        self.assertTrue(body.exited)
        self.assertTrue(client.exited)
        self.assertEqual(body.read_sizes, [])

