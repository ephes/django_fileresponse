from types import SimpleNamespace
import unittest
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8")

import fileresponse.http as http
from fileresponse.handlers import AsyncFileASGIHandler


OVERRIDES = {
    "endpoint_url": "https://synthetic.invalid",
    "region_name": "test-region",
    "aws_access_key_id": "synthetic-access",
    "secret_access_key": "synthetic-secret",
    "use_ssl": True,
}
DEFAULTS = {
    "FILERESPONSE_S3_ENDPOINT_URL": "https://default.invalid",
    "FILERESPONSE_S3_REGION": "default-region",
    "FILERESPONSE_S3_ACCESS_KEY_ID": "default-access",
    "FILERESPONSE_S3_SECRET_ACCESS_KEY": "default-secret",
}


class FakeBody:
    def __init__(self):
        self.data = b"synthetic object"
        self.exited = False
        self.read_sizes = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.exited = True

    async def read(self, size):
        self.read_sizes.append(size)
        result, self.data = self.data[:size], self.data[size:]
        return result


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.exited = False
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.exited = True

    async def get_object(self, **kwargs):
        self.request = kwargs
        return {"Body": self.body}


class FakeSession:
    def __init__(self, client):
        self.client = client
        self.config = None

    def create_client(self, service, **kwargs):
        assert service == "s3"
        self.config = kwargs
        return self.client


class S3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_overrides_need_no_s3_settings(self):
        with patch.object(http, "settings", SimpleNamespace()):
            response = http.AiobotocoreFileResponse(
                "synthetic-bucket", "synthetic-key", chunk_size=3, **OVERRIDES
            )
        body = FakeBody()
        client = FakeClient(body)
        session = FakeSession(client)
        messages = []

        async def send(message):
            messages.append(message)

        with patch.object(http, "get_session", return_value=session, create=True) as factory:
            await AsyncFileASGIHandler().send_response(response, send)
        factory.assert_called_once_with()
        self.assertEqual(client.request, {"Bucket": "synthetic-bucket", "Key": "synthetic-key"})
        self.assertEqual(session.config, {
            "endpoint_url": OVERRIDES["endpoint_url"],
            "region_name": OVERRIDES["region_name"],
            "aws_access_key_id": OVERRIDES["aws_access_key_id"],
            "aws_secret_access_key": OVERRIDES["secret_access_key"],
            "use_ssl": True,
        })
        self.assertEqual(messages[0]["type"], "http.response.start")
        self.assertEqual(b"".join(m["body"] for m in messages[1:]), b"synthetic object")
        self.assertFalse(messages[-1]["more_body"])
        self.assertEqual(set(body.read_sizes), {3})
        self.assertTrue(body.exited)
        self.assertTrue(client.exited)

    async def test_public_session_factory_is_used_with_default_settings(self):
        body = FakeBody()
        client = FakeClient(body)
        with patch.object(http, "settings", SimpleNamespace(**DEFAULTS)):
            response = http.AiobotocoreFileResponse("bucket", "key")
        # Real installed public session API, fake only the client's network boundary.
        from aiobotocore.session import AioSession

        async def send(message):
            pass

        with patch.object(AioSession, "create_client", return_value=client) as factory:
            await response.stream(send)
        factory.assert_called_once_with(
            "s3", endpoint_url=DEFAULTS["FILERESPONSE_S3_ENDPOINT_URL"],
            region_name=DEFAULTS["FILERESPONSE_S3_REGION"],
            aws_access_key_id=DEFAULTS["FILERESPONSE_S3_ACCESS_KEY_ID"],
            aws_secret_access_key=DEFAULTS["FILERESPONSE_S3_SECRET_ACCESS_KEY"],
            use_ssl=False,
        )

    async def test_send_failure_closes_body_and_client(self):
        body = FakeBody()
        client = FakeClient(body)
        with patch.object(http, "settings", SimpleNamespace(**DEFAULTS)):
            response = http.AiobotocoreFileResponse("bucket", "key")

        async def send(message):
            if message.get("body"):
                raise RuntimeError("synthetic send failure")

        with patch.object(http, "get_session", return_value=FakeSession(client), create=True):
            with self.assertRaisesRegex(RuntimeError, "synthetic send failure"):
                await response.stream(send)
        self.assertTrue(body.exited)
        self.assertTrue(client.exited)

    def test_missing_required_setting_fails_before_client_creation(self):
        for missing in DEFAULTS:
            values = {k: v for k, v in DEFAULTS.items() if k != missing}
            with self.subTest(missing=missing):
                with patch.object(http, "settings", SimpleNamespace(**values)):
                    with patch.object(http, "get_session", create=True) as factory:
                        with self.assertRaisesRegex(ImproperlyConfigured, missing):
                            http.AiobotocoreFileResponse("bucket", "key")
                    factory.assert_not_called()

    def test_each_option_can_independently_override_a_missing_setting(self):
        for option, setting in (
            ("endpoint_url", "FILERESPONSE_S3_ENDPOINT_URL"),
            ("region_name", "FILERESPONSE_S3_REGION"),
            ("aws_access_key_id", "FILERESPONSE_S3_ACCESS_KEY_ID"),
            ("secret_access_key", "FILERESPONSE_S3_SECRET_ACCESS_KEY"),
        ):
            values = {k: v for k, v in DEFAULTS.items() if k != setting}
            with self.subTest(option=option):
                with patch.object(http, "settings", SimpleNamespace(**values)):
                    response = http.AiobotocoreFileResponse("bucket", "key", **{option: OVERRIDES[option]})
                client_key = "aws_secret_access_key" if option == "secret_access_key" else option
                self.assertEqual(response.client_config[client_key], OVERRIDES[option])

    def test_explicit_false_ssl_overrides_true_setting(self):
        with patch.object(http, "settings", SimpleNamespace(**DEFAULTS, FILERESPONSE_S3_USE_SSL=True)):
            response = http.AiobotocoreFileResponse("bucket", "key", use_ssl=False)
        self.assertIs(response.client_config["use_ssl"], False)
