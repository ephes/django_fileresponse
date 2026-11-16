import asyncio
import unittest

from django.conf import settings

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

import fileresponse.http as http
from test_s3 import FakeBody




class SingleConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_sequential_stream_and_helper_attempts_are_refused_before_headers(self):
        for first_helper in (False, True):
            response = http.AsyncResponse()
            messages = []

            async def send(message):
                messages.append(message)

            if first_helper:
                await response.send_stream_to_client(FakeBody(), send)
            else:
                await response.stream(send)
            first_messages = list(messages)
            for second_helper in (False, True):
                with self.assertRaisesRegex(RuntimeError, "Response stream already consumed"):
                    if second_helper:
                        await response.send_stream_to_client(FakeBody(), send)
                    else:
                        await response.stream(send)
                self.assertEqual(messages, first_messages)

    async def test_concurrent_attempt_cannot_replace_an_admitted_stream(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        response = http.AsyncResponse(chunk_size=3)
        messages = []

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.start":
                entered.set()
                await release.wait()

        first = asyncio.create_task(response.send_stream_to_client(FakeBody(), send))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            with self.assertRaisesRegex(RuntimeError, "Response stream already consumed"):
                await asyncio.wait_for(response.send_stream_to_client(FakeBody(), send), 0.1)
        finally:
            release.set()
            await first
        self.assertEqual(sum(m["type"] == "http.response.start" for m in messages), 1)
        self.assertEqual(b"".join(m.get("body", b"") for m in messages), b"synthetic object")

    async def test_failed_admission_also_consumes_response(self):
        response = http.AiofileFileResponse("synthetic-missing-file")
        messages = []

        async def send(message):
            messages.append(message)

        with self.assertRaises(FileNotFoundError):
            await response.stream(send)
        with self.assertRaisesRegex(RuntimeError, "Response stream already consumed"):
            await response.stream(send)
        self.assertEqual(messages, [])
