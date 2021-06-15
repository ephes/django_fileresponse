# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/01_handlers.ipynb (unless otherwise specified).

__all__ = ['AsyncFileASGIHandler']

# Cell

from asgiref.sync import sync_to_async
from django.core.handlers.asgi import ASGIHandler


class AsyncFileASGIHandler(ASGIHandler):
    async def send_response(self, response, send):
        if response.is_async:
            return response.stream(send)
        else:
            return super().send_response(response, send)