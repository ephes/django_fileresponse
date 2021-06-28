# Welcome to django_fileresponse
> Serve files directly from Django.


`django_fileresponse` is a library that allows you to serve files directly from Django.

## Features of django_fileresponse

`django_fileresponse` provides the following features for developers:

- **Use asyncio to serve files with high concurrency** directly from Django.
- Uses [aiofiles](https://github.com/Tinche/aiofiles) to **asynchronously read from filesystem** and [aiobotocore](https://github.com/aio-libs/aiobotocore) to **asynchronously read from s3 compatible object stores**

## Installing

`django_fileresponse` is on PyPI so you can just run `pip install django_fileresponse`.

## Replace Default ASGIHandler

You have to replace Djangos `ASGIHandler`, because it synchronously calls `__next__` in [for part in response](https://github.com/django/django/blob/66af94d56ea08ccf8d906708a6cc002dd3ab24d3/django/core/handlers/asgi.py#L242) which makes it impossible to await reading from a filesystem/object-store.


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

## How to use Async Fileresponses in your Views

Add functions below to your `views.py`

### Serving from Filesystem

```python
from fileresponse.http import AiofileFileResponse as AiofileFileResponse


async def get_file(request, path):
    file_path = Path(path)
    return AiofileFileResponse(file_path)
```


    <IPython.core.display.Javascript object>


### Serve Files from an S3 Compatible Object Store

```python
from fileresponse.http import AiobotocoreFileResponse


async def get_file(request, key):
    bucket = settings.FILERESPONSE_S3_ACCESS_KEY_ID
    return AiobotocoreFileResponse(bucket, key, chunk_size=4096)
```


    <IPython.core.display.Javascript object>


## Settings

### Example Settings for an S3 Compatible Object Store

```
FILERESPONSE_S3_ACCESS_KEY_ID="minioadmin"
FILERESPONSE_S3_SECRET_ACCESS_KEY="minioadmin"
FILERESPONSE_S3_REGION="us-west-2"
FILERESPONSE_S3_STORAGE_BUCKET_NAME="fileresponse"
FILERESPONSE_S3_ENDPOINT_URL="http://localhost:9000"
```
