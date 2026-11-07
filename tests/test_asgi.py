from pathlib import Path
import tempfile
import unittest

from django.conf import settings
from django.http import HttpResponse

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

from fileresponse.asgi import get_asgi_application
from fileresponse.handlers import AsyncFileASGIHandler
from fileresponse.http import AiofileFileResponse


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_filesystem_response_through_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic file")
            messages = []

            async def send(message):
                messages.append(message)

            await AsyncFileASGIHandler().send_response(AiofileFileResponse(path, chunk_size=2), send)
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(b"".join(m["body"] for m in messages[1:]), b"synthetic file")
        self.assertFalse(messages[-1]["more_body"])

    async def test_normal_django_response_uses_default_handler(self):
        messages = []

        async def send(message):
            messages.append(message)

        await AsyncFileASGIHandler().send_response(HttpResponse(b"ordinary"), send)
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(b"".join(m.get("body", b"") for m in messages[1:]), b"ordinary")

    def test_application_factory(self):
        self.assertIsInstance(get_asgi_application(), AsyncFileASGIHandler)
