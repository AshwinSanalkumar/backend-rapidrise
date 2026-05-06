import jwt
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
import urllib.parse

User = get_user_model()

@database_sync_to_async
def get_user(user_id):
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return AnonymousUser()

class CookieJWTAuthMiddleware:
    """
    Custom middleware that takes the JWT token from the cookie or query params.
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Extract token from cookie first
        headers = dict(scope.get('headers', []))
        cookie_header = headers.get(b'cookie', b'').decode()
        
        cookies = {}
        for cookie in cookie_header.split(';'):
            if '=' in cookie:
                k, v = cookie.strip().split('=', 1)
                cookies[k] = v
        
        token = cookies.get('access_token')
        
        # fallback to query string (useful for some types of websocket connections)
        if not token:
            query_string = scope.get('query_string', b'').decode()
            query_params = urllib.parse.parse_qs(query_string)
            token_list = query_params.get('token')
            if token_list:
                token = token_list[0]
        
        if token:
            try:
                # Assuming access_token is a standard JWT with user_id or id
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                user_id = payload.get('user_id') or payload.get('id')
                scope['user'] = await get_user(user_id)
            except (jwt.ExpiredSignatureError, jwt.DecodeError, jwt.InvalidTokenError):
                scope['user'] = AnonymousUser()
        else:
            scope['user'] = AnonymousUser()
            
        return await self.inner(scope, receive, send)