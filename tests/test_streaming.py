import asyncio
from pathlib import Path
import tempfile
import tracemalloc
import unittest

from django.conf import settings

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

from fileresponse.http import (
    AiobotocoreFileResponse,
    AiofileFileResponse,
    AsyncResponse,
)


class GeneratedStream:
    """Produce fresh bytes without retaining the synthetic payload."""

    def __init__(self, size):
        self.remaining = size
        self.reads = 0

    async def read(self, size):
        self.reads += 1
        length = min(size, self.remaining)
        self.remaining -= length
        return bytes([self.reads % 251]) * length


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_is_bounded_by_chunk_size(self):
        chunk_size = 64 * 1024
        for route in ("helper", "stream", "wrapped"):
            for total in (1024 * 1024, 32 * 1024 * 1024):
                with self.subTest(total=total, route=route):
                    stream = GeneratedStream(total)
                    class GeneratedResponse(AsyncResponse):
                        async def _stream_content(self):
                            async for chunk in self._read_chunks(stream):
                                yield chunk

                    response = GeneratedResponse(chunk_size=chunk_size)
                    if route == "wrapped":
                        content = response.streaming_content

                        async def wrapped():
                            async for chunk in content:
                                yield chunk

                        response.streaming_content = wrapped()
                    sent = 0
                    bodies = 0

                    async def send(message):
                        nonlocal sent, bodies
                        if message["type"] == "http.response.body":
                            bodies += 1
                            body = message["body"]
                            self.assertEqual(body, bytes([bodies % 251]) * len(body))
                            self.assertLessEqual(len(body), chunk_size)
                            sent += len(body)
                            self.assertEqual(message["more_body"], bool(body))

                    tracemalloc.start()
                    try:
                        if route == "helper":
                            await response.send_stream_to_client(stream, send)
                        else:
                            await response.stream(send)
                        _, peak = tracemalloc.get_traced_memory()
                    finally:
                        tracemalloc.stop()
                    self.assertEqual(sent, total)
                    self.assertEqual(bodies, total // chunk_size + 1)
                    self.assertLess(peak, 8 * chunk_size + 256 * 1024)

    async def test_slow_send_blocks_next_read(self):
        stream = GeneratedStream(6)
        blocked = asyncio.Event()
        release = asyncio.Event()

        async def send(message):
            if message.get("body") and not release.is_set():
                blocked.set()
                await release.wait()

        task = asyncio.create_task(
            AsyncResponse(chunk_size=3).send_stream_to_client(stream, send)
        )
        try:
            await asyncio.wait_for(blocked.wait(), timeout=5)
            await asyncio.sleep(0)
            self.assertEqual(stream.reads, 1)
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=5)
        self.assertEqual(stream.reads, 3)

    async def test_filesystem_delivers_all_bytes_in_small_chunks(self):
        data = bytes(range(251)) * 10
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(data)
            messages = []

            async def send(message):
                messages.append(message)

            await AiofileFileResponse(path, chunk_size=7).stream(send)
        self.assertEqual(messages[0]["type"], "http.response.start")
        bodies = messages[1:]
        self.assertEqual(b"".join(m["body"] for m in bodies), data)
        self.assertTrue(all(len(m["body"]) <= 7 for m in bodies))
        self.assertEqual(bodies[-1]["more_body"], False)


class ChunkSizeTests(unittest.TestCase):
    def test_invalid_sizes_fail_at_construction_for_every_adapter(self):
        for size in (0, -1, True, False, 1.5, "4096", None, 1024 * 1024 + 1):
            for response_class, args in (
                (AsyncResponse, ()),
                (AiofileFileResponse, ("unused",)),
                (AiobotocoreFileResponse, ("unused", "unused")),
            ):
                with self.subTest(size=size, adapter=response_class.__name__):
                    with self.assertRaisesRegex(ValueError, "chunk_size"):
                        response_class(*args, chunk_size=size)

    def test_valid_sizes(self):
        for size in (1, 4096, 1024 * 1024):
            self.assertEqual(AsyncResponse(chunk_size=size).chunk_size, size)
