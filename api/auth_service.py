from .models import User
from django.core.exceptions import ValidationError
from rest_framework.response import Response

class AuthenticationService:
    @staticmethod
    def register_user(email, password, first_name, last_name, dob):
        if User.objects.filter(email=email).exists():
            raise ValidationError("Email already registered.")
        return User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            dob=dob
        )
    
    @staticmethod
    def get_user_by_identity(user_data):
        """Internal helper to find a user by email."""
        # Since username = None in your model, we prioritize email
        identity = user_data.get('email')
        try:
            return User.objects.get(email=identity)
        except User.DoesNotExist:
            # Fallback or raise a specific error for the service to handle
            return None
        
    @staticmethod
    def token_service(response: Response, user_data: dict):
        """
        Business logic to transform a JWT body response into HttpOnly cookies.
        """
        user = AuthenticationService.get_user_by_identity(user_data)
        response.data['user'] = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
        }
        access_token = response.data.pop('access', None)
        refresh_token = response.data.pop('refresh', None)

        if access_token:
            response.set_cookie(
                key='access_token',
                value=access_token,
                httponly=True,
                secure=False, 
                samesite='Lax',
                max_age=300,   
            )

        if refresh_token:
            response.set_cookie(
                key='refresh_token',
                value=refresh_token,
                httponly=True,
                secure=False,
                samesite='Lax',
                max_age=86400, 
            )

        return response