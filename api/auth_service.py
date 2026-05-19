from .models import User
from django.core.exceptions import ValidationError
from rest_framework.response import Response
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.http import (
    urlsafe_base64_encode,
    urlsafe_base64_decode
)
from django.utils.encoding import (
    force_bytes,
    force_str
)
from django.core.mail import send_mail
from django.conf import settings



token_generator = PasswordResetTokenGenerator()


class AuthenticationService:
    @staticmethod
    def change_password(user, current_password, new_password):
        """Validates current password and updates to new password."""
        if not current_password or not new_password:
            raise ValueError("Both current and new passwords are required.")
        
        if not user.check_password(current_password):
            raise ValueError("Incorrect current password.")

        user.set_password(new_password)
        user.save()
        return True

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
        from .serializers import UserSerializer
        user = AuthenticationService.get_user_by_identity(user_data)
        response.data['user'] = UserSerializer(user).data
        access_token = response.data.pop('access', None)
        refresh_token = response.data.pop('refresh', None)

        if access_token:
            response.set_cookie(
                key='access_token',
                value=access_token,
                httponly=True,
                secure=False, 
                samesite='Lax',
                max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()),   
            )

        if refresh_token:
            response.set_cookie(
                key='refresh_token',
                value=refresh_token,
                httponly=True,
                secure=False,
                samesite='Lax',
                max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()), 
            )

        return response

    @staticmethod
    def send_reset_email(email):

        try:
            user = User.objects.get(email=email)

        except User.DoesNotExist:
            return

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = token_generator.make_token(user)

        reset_url = (
            f"{settings.FRONTEND_URL}"
            f"/reset-password/{uid}/{token}/"
        )

        subject = "Reset Your Password"

        message = f"""
Hi {user.first_name},

Click the link below to reset your password:

{reset_url}

This link will expire in 10 minutes.

If you did not request this, please ignore this email.
"""

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )

    @staticmethod
    def reset_password(uidb64, token, password):

        try:
            uid = force_str(
                urlsafe_base64_decode(uidb64)
            )

            user = User.objects.get(pk=uid)

        except Exception:
            return False, "Invalid reset link"

        if not token_generator.check_token(user, token):
            return False, "Token expired or invalid"

        import re
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        if not re.search(r"[a-z]", password):
            return False, "Password Must contain atleast One lower case"
        if not re.search(r"[A-Z]", password):
            return False, "Password Must contain atleast One Uppercase"
        if not re.search(r"[!@#$%^&*()]", password):
            return False, "Password Must contain atleast One special char"
        if not re.search(r"[0-9]", password):
            return False, "Password Must contain atleast One Number"

        user.set_password(password)
        user.save()

        return True, "Password reset successful"