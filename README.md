# Welcome to django_fileresponse
> Serve files directly from Django.


`django_fileresponse` is a library that allows you to serve files directly from Django.

## Features of django_fileresponse

`django_fileresponse` provides the following features for developers:

- **Use asyncio to serve files with high concurrency** directly from Django.
- Uses [aiofiles](https://github.com/Tinche/aiofiles) to **asynchronously read from filesystem** and [aiobotocore](https://github.com/aio-libs/aiobotocore) to **asynchronously read from s3 compatible object stores**

## Installing

`django_fileresponse` is on PyPI so you can just run `pip install django_fileresponse`.

## How to use

### Serving from Filesystem

In your views.py add this:

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

