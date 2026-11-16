import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from django.conf import settings

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

import fileresponse.http as http
from fileresponse.handlers import AsyncFileASGIHandler
from test_middleware import compress
from test_s3 import FakeBody, FakeClient, FakeSession, OVERRIDES


class MetadataTests(unittest.IsolatedAsyncioTestCase):
    async def send_response(self, response, client=None):
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(http, "get_session", return_value=FakeSession(client)):
            await AsyncFileASGIHandler().send_response(response, send)
        return dict(messages[0]["headers"]), b"".join(m.get("body", b"") for m in messages)

    def s3_source(self, **options):
        body = FakeBody()
        client = FakeClient(body)

        async def get_object(**kwargs):
            return {"Body": body, "ContentLength": len(b"synthetic object"), "ContentType": "text/plain"}

        client.get_object = get_object
        return http.AiobotocoreFileResponse("bucket", "key", **OVERRIDES, **options), client

    async def test_sources_supply_content_type_and_length_at_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.txt"
            path.write_bytes(b"synthetic object")
            response, client = self.s3_source()
            for response, client in ((response, client), (http.AiofileFileResponse(path), None)):
                headers, data = await self.send_response(response, client)
                self.assertEqual(headers[b"content-type"], b"text/plain")
                self.assertEqual(headers[b"content-length"], str(len(data)).encode())
                self.assertEqual(data, b"synthetic object")

    async def test_explicit_caller_metadata_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.txt"
            path.write_bytes(b"synthetic object")
            for options in (
                {"content_type": "text/custom", "headers": {"Content-Length": "16"}},
                {"headers": {"Content-Type": "text/custom", "Content-Length": "16"}},
                {},
            ):
                response, client = self.s3_source(**options)
                for response, client in ((response, client), (http.AiofileFileResponse(path, **options), None)):
                    if not options:
                        response["Content-Type"] = "text/custom"
                        response["Content-Length"] = "16"
                    headers, _ = await self.send_response(response, client)
                    self.assertEqual(headers[b"content-type"], b"text/custom")
                    self.assertEqual(headers[b"content-length"], b"16")

    async def test_gzip_never_reinstates_source_or_explicit_uncompressed_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.txt"
            path.write_bytes(b"synthetic object")
            for explicit_length in (False, True):
                options = {"headers": {"Content-Length": "16"}} if explicit_length else {}
                response, client = self.s3_source(**options)
                for response, client in ((response, client), (http.AiofileFileResponse(path, **options), None)):
                    response = compress(response)
                    headers, data = await self.send_response(response, client)
                    self.assertEqual(headers[b"content-type"], b"text/plain")
                    self.assertEqual(headers[b"content-encoding"], b"gzip")
                    self.assertNotIn(b"content-length", headers)
                    self.assertEqual(gzip.decompress(data), b"synthetic object")

    async def test_replacing_streaming_content_discards_source_length(self):
        response, client = self.s3_source(headers={"Content-Length": "16"})
        original = response.streaming_content

        async def changed():
            async for chunk in original:
                yield chunk + b"!"

        response.streaming_content = changed()
        headers, data = await self.send_response(response, client)
        self.assertNotIn(b"content-length", headers)
        self.assertEqual(data, b"synthetic object!")

    async def test_unsafe_s3_metadata_cannot_inject_response_headers(self):
        response, client = self.s3_source()

        async def get_object(**kwargs):
            return {"Body": client.body, "ContentLength": -1, "ContentType": "text/plain\r\nX-Injected: yes"}

        client.get_object = get_object
        headers, _ = await self.send_response(response, client)
        self.assertEqual(headers[b"content-type"], b"application/octet-stream")
        self.assertNotIn(b"content-length", headers)
        self.assertNotIn(b"x-injected", headers)
