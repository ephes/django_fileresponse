from pathlib import Path
import tempfile
import unittest

from django.conf import settings
from django.http import BadHeaderError, HttpResponse

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


class HeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_lowercase_headers_preserve_values_and_separate_cookies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"
            path.write_bytes(b"synthetic")
            response = AiofileFileResponse(path)
            response["X-MiXeD-Case"] = "caf\xe9"
            response.set_cookie("first", "one")
            response.set_cookie("second", "two")
            messages = []

            async def send(message):
                messages.append(message)

            await AsyncFileASGIHandler().send_response(response, send)
        headers = messages[0]["headers"]
        self.assertTrue(all(name == name.lower() for name, value in headers))
        self.assertIn((b"x-mixed-case", b"caf\xe9"), headers)
        cookies = [value for name, value in headers if name == b"set-cookie"]
        self.assertEqual(len(cookies), 2)
        self.assertTrue(cookies[0].startswith(b"first=one;"))
        self.assertTrue(cookies[1].startswith(b"second=two;"))

    def test_header_value_validation_is_retained(self):
        response = AiofileFileResponse("unused")
        with self.assertRaises(BadHeaderError):
            response["X-Test"] = "value\r\ninjected: value"
