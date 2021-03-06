# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/02_http.ipynb (unless otherwise specified).

__all__ = ['AsyncResponse', 'AiofileFileResponse', 'AiobotocoreFileResponse']

# Cell

import time

from django.http.response import HttpResponseBase


class AsyncResponse(HttpResponseBase):
    """
    Provides the `is_async_fileresponse` attribute checked by
    fileresponse.handlers.AsyncFileASGIHandler.

    Contains the core content streaming logic which is the same
    for files and other file like streams.
    """

    streaming = True  # common middleware needs this
    is_async_fileresponse = True

    def __init__(self, *args, **kwargs):
        self.chunk_size = kwargs.get("chunk_size", 4096)
        self.raw_headers = kwargs.get("raw_headers", {})

        # copy relevant super kwargs from kwargs
        super_kwargs_names = {"content_type", "status", "reason", "charset", "headers"}
        super_kwargs = {key: kwargs.get(key) for key in super_kwargs_names}

        # set default values
        content_type = kwargs.get("content_type", "application/octet-stream")
        super_kwargs["content_type"] = content_type
        status = kwargs.get("status", 200)
        super().__init__(**super_kwargs)

    @property
    def response_headers(self):
        # copied from django.core.handlers.asgi.ASGIHandler.send_response
        response_headers = []
        for header, value in self.items():
            if isinstance(header, str):
                header = header.encode("ascii")
            if isinstance(value, str):
                value = value.encode("latin1")
            response_headers.append((bytes(header), bytes(value)))
        for c in self.cookies.values():
            response_headers.append(
                (b"Set-Cookie", c.output(header="").encode("ascii").strip())
            )
        return response_headers

    async def send_stream_to_client(self, stream, send):
        """
        Core streaming logic. Supports all streams from which
        chunks of content could be read like this:

        ```python
            chunk = await stream.read(chunk_size)
        ```
        """
        started_serving = time.perf_counter()
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.response_headers,
            }
        )
        chunks = []
        sent_size = 0

        more_body = True
        while more_body:
            chunk = await stream.read(self.chunk_size)
            chunk_len = len(chunk)
            more_body = chunk_len > 0
            chunks.append(chunk)
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": more_body,
                }
            )
            sent_size += chunk_len
        self.elapsed = time.perf_counter() - started_serving

# Cell

import aiofiles


class AiofileFileResponse(AsyncResponse):
    """
    Async response class for serving files from the filesystem. It's only
    used to open a stream and to hand it over to AsyncResponse which then
    handles all of the content streaming.

    It uses aiofiles to get the stream object from which chunks of data could be
    read asynchronously. The aiofiles library uses a threadpool to provide async
    filesystem access.
    """

    def __init__(self, path, chunk_size=4096):
        super().__init__(path, chunk_size=chunk_size)
        self.path = path

    def __repr__(self):
        return "<%(cls)s status_code=%(status_code)d>" % {
            "cls": self.__class__.__name__,
            "status_code": self.status_code,
        }

    async def stream(self, send):
        async with aiofiles.open(self.path, mode="rb") as stream:  # type: ignore
            await self.send_stream_to_client(stream, send)

# Cell

import aiobotocore

from django.conf import settings


class AiobotocoreFileResponse(AsyncResponse):
    """
    Async response class for serving files from an s3 compatible object store
    like [MinIO](http://min.io). It's only about opening / configuring the stream
    and then using AsyncResponse to handle the actual streaming of content to
    the client.

    It uses aiobotocore to get the stream object from which chunks of data could be
    read asynchronously.
    """

    def __init__(self, bucket, key, chunk_size=4096, **kwargs):
        super().__init__(chunk_size=chunk_size)
        self.client_config = self.create_client_config(kwargs)
        self.bucket = bucket
        self.key = key

    def __repr__(self):
        return "<%(cls)s status_code=%(status_code)d>" % {
            "cls": self.__class__.__name__,
            "status_code": self.status_code,
        }

    def create_client_config(self, kwargs):
        return {
            "endpoint_url": kwargs.get(
                "endpoint_url", settings.FILERESPONSE_S3_ENDPOINT_URL
            ),
            "region_name": kwargs.get("region_name", settings.FILERESPONSE_S3_REGION),
            "aws_access_key_id": kwargs.get(
                "aws_access_key_id", settings.FILERESPONSE_S3_ACCESS_KEY_ID
            ),
            "aws_secret_access_key": kwargs.get(
                "secret_access_key", settings.FILERESPONSE_S3_SECRET_ACCESS_KEY
            ),
            "use_ssl": kwargs.get(
                "use_ssl", getattr(settings, "FILERESPONSE_S3_USE_SSL", False)
            ),
        }

    async def stream(self, send):
        session = aiobotocore.get_session()
        async with session.create_client("s3", **self.client_config) as client:
            minio_response = await client.get_object(Bucket=self.bucket, Key=self.key)
            async with minio_response["Body"] as stream:
                await self.send_stream_to_client(stream, send)