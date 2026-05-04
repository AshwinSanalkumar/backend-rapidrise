from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model

User = get_user_model()

@database_sync_to_async
def get_user_from_token(token_key):
    try:
        token = AccessToken(token_key)
        user_id = token['user_id']
        return User.objects.get(id=user_id)
    except Exception:
        return AnonymousUser()

class CookieJWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Extract cookies from headers
        headers = dict(scope['headers'])
        cookie_header = headers.get(b'cookie', b'').decode()
        
        # Parse cookies to find access_token
        cookies = {}
        for cookie in cookie_header.split('; '):
            if '=' in cookie:
                k, v = cookie.split('=', 1)
                cookies[k] = v
        
        token_key = cookies.get('access_token')
        
        if token_key:
            scope['user'] = await get_user_from_token(token_key)
        else:
            scope['user'] = AnonymousUser()

        return await self.app(scope, receive, send)
