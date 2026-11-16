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


class HttpOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_adapters_preserve_django_options_through_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.txt"
            path.write_bytes(b"synthetic object")
            for adapter in ("file", "s3"):
                with self.subTest(adapter=adapter):
                    options = dict(
                        status=202, reason="Synthetic response", charset="utf-8",
                        content_type="text/custom", headers={
                            "Content-Disposition": 'attachment; filename="synthetic.txt"',
                            "Cache-Control": "private, max-age=60",
                        },
                    )
                    if adapter == "file":
                        response = http.AiofileFileResponse(path, **options)
                    else:
                        response = http.AiobotocoreFileResponse("bucket", "key", **options, **OVERRIDES)
                    messages = []

                    async def send(message):
                        messages.append(message)

                    session = FakeSession(FakeClient(FakeBody()))
                    with patch.object(http, "get_session", return_value=session):
                        await AsyncFileASGIHandler().send_response(response, send)
                    self.assertEqual(messages[0]["status"], 202)
                    self.assertEqual(response.reason_phrase, "Synthetic response")
                    self.assertEqual(response.charset, "utf-8")
                    headers = dict(messages[0]["headers"])
                    self.assertEqual(headers[b"content-type"], b"text/custom")
                    self.assertEqual(headers[b"content-disposition"], b'attachment; filename="synthetic.txt"')
                    self.assertEqual(headers[b"cache-control"], b"private, max-age=60")
                    self.assertFalse(any(b"synthetic-secret" in value for value in headers.values()))
                    self.assertNotIn("status", session.config or {})
                    self.assertNotIn("headers", session.config or {})
                    self.assertEqual(b"".join(m.get("body", b"") for m in messages), b"synthetic object")
