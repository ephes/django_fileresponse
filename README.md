# Welcome to django_fileresponse
> Serve files directly from Django.


`django_fileresponse` ([link to documentation](https://ephes.github.io/django_fileresponse/)) is a library that allows you to serve files directly from Django.

## Features of django_fileresponse

`django_fileresponse` provides the following features for developers:

- **Use asyncio to serve files with high concurrency** directly from Django.
- Uses [aiofiles](https://github.com/Tinche/aiofiles) to **asynchronously read from filesystem** and [aiobotocore](https://github.com/aio-libs/aiobotocore) to **asynchronously read from s3 compatible object stores**

Streaming memory is proportional to the chunk size; emitted payloads are not
retained. Each send is awaited before reading again, so slow clients apply
backpressure. All response classes accept `chunk_size` as an integer from
1 through 1,048,576 bytes (1 MiB), default 4096. Invalid values, including
booleans, raise `ValueError` before opening a stream or sending headers.

## Installing

`django_fileresponse` is on PyPI so you can just run `pip install django_fileresponse`.

## Replace Default ASGIHandler

You have to replace Djangos `ASGIHandler`, because it synchronously calls `__next__` in [for part in response](https://github.com/django/django/blob/66af94d56ea08ccf8d906708a6cc002dd3ab24d3/django/core/handlers/asgi.py#L242) which makes it impossible to await reading from a filesystem/object-store.

So you have to replace the default `ASGIHandler` in `asgi.py`.

So instead of building your application like this:

```python
from django.core.asgi import get_asgi_application

application = get_asgi_application()
```

You have to import a modified ASGIHandler from fileresponse:

```python
from fileresponse.asgi import get_asgi_application

application = get_asgi_application()
```

If you use a different mechanism to launch your application, you could also just import the modified `AsyncFileASGIHandler` directly:

```python
from fileresponse.handlers import AsyncFileASGIHandler

django.setup(set_prefix=False)
application = AsyncFileASGIHandler()
```

## How to use Async Fileresponses in your Views

Add functions below to your `views.py`

### Serving from Filesystem

```python
from fileresponse.http import AiofileFileResponse as AiofileFileResponse


async def get_file(request, path):
    file_path = Path(path)
    return AiofileFileResponse(file_path)
```

### Serve Files from an S3 Compatible Object Store

```python
from fileresponse.http import AiobotocoreFileResponse


async def get_file(request, key):
    bucket = settings.FILERESPONSE_S3_STORAGE_BUCKET_NAME
    return AiobotocoreFileResponse(bucket, key, chunk_size=4096)
```

## Settings

### Example Settings for an S3 Compatible Object Store

```
FILERESPONSE_S3_ACCESS_KEY_ID="minioadmin"
FILERESPONSE_S3_SECRET_ACCESS_KEY="minioadmin"
FILERESPONSE_S3_REGION="us-west-2"
FILERESPONSE_S3_STORAGE_BUCKET_NAME="fileresponse"
FILERESPONSE_S3_ENDPOINT_URL="http://localhost:9000"
```

Alternatively pass `endpoint_url`, `region_name`, `aws_access_key_id`,
`secret_access_key` and `use_ssl` to `AiobotocoreFileResponse`. These option
names are unchanged; `secret_access_key` becomes the client
`aws_secret_access_key`. Explicit values bypass their individual S3 settings.
All four endpoint/region/credential values must be supplied either as overrides
or Django settings; missing settings raise `ImproperlyConfigured` before
network access. `use_ssl` defaults to `False` when neither option nor setting
is supplied. Django itself must still be configured.

## Development and validation

The supported toolchain is CPython 3.11–3.13, Django 5.2, aiofiles 24.1–25.x,
and aiobotocore 2.21–2.x. The development extra pins nbdev 1.2.11 and its
compatible conversion dependencies; nbdev 2 uses a different notebook format.
The package version is unchanged.

In a virtual environment, install `python -m pip install -e '.[dev]'`, then run:

```sh
ruff check fileresponse tests scripts
mypy fileresponse scripts
python scripts/generate.py --check
python -m unittest discover -s tests -v
python -m build
python scripts/package_smoke.py
```

CI runs these checks on every supported Python version with read-only repository
permissions. Tests generate synthetic bytes and temporary files, fake S3 clients,
and verify memory bounds, backpressure, chunk validation, ASGI handling, and
client/body cleanup. They need no object-store settings, credentials, or services.
The package smoke test installs both wheel and sdist in fresh environments and
runs the same suite outside the checkout. Remove old `dist/` artifacts before
rebuilding so it contains exactly one wheel and one sdist.

Edit `nbs/*.ipynb`, then run `python scripts/generate.py --docs` to regenerate
Python, README and API HTML. Generation uses a disposable copy, preserves the
published documentation base URL, and executes only import/show_doc cells for
API documentation. `--check` verifies the generated Python and README without
changing the checkout; add `--docs` to check API HTML too. The MinIO, sample
project and concurrent-download demonstrations are excluded from mandatory CI
and documentation execution.


## More Information

* [DjangoCon Europe 2021 Talk about file serving with Django](https://wersdoerfer.de/blogs/ephes_blog/djangocon-2021/)
* [Podcast episode about DjangoCon Europe 2021](https://python-podcast.de/show/djangoconeu-2021/)
