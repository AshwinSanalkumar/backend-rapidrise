import logging
import threading
import re
import random
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
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from .serializers import UserSerializer
from .email_service import BrevoEmailService

logger = logging.getLogger('users')

token_generator = PasswordResetTokenGenerator()


class AuthenticationService:
    @staticmethod
    def send_template_email(
        to_email,
        subject,
        template_name,
        context
    ):
        html_content = render_to_string(
            template_name,
            context
        )

        BrevoEmailService.send_email(
            subject=subject,
            html_content=html_content,
            recipients=[to_email]
        )

    @staticmethod
    def change_password(user, current_password, new_password):
        """Validates current password and updates to new password."""
        logger.info(f"ACTION PERFORMED: Password change request for user {user.email}")
        if not current_password or not new_password:
            raise ValueError("Both current and new passwords are required.")
        
        if not user.check_password(current_password):
            raise ValueError("Incorrect current password.")

        if current_password == new_password:
            raise ValueError("New password cannot be the same as the old password.")

        user.set_password(new_password)
        user.save()
        return True

    @staticmethod
    def register_user(email, password, first_name, last_name, dob):
        if User.objects.filter(email=email).exists():
            raise ValidationError("Email already registered.")
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            dob=dob
        )
        logger.info(f"ACTION PERFORMED: New user registered: {email}")
        AuthenticationService.send_welcome_email(user)
        return user
    #welcome email

    @staticmethod
    def send_welcome_email(user):

        subject = "Welcome to NexusShare!"

        context = {
            "first_name": user.first_name,
            "frontend_url": settings.FRONTEND_URL,
        }

        html_body = render_to_string(
            "emails/welcome.html",
            context
        )

        def send_async():
            try:
                BrevoEmailService.send_email(
                    subject=subject,
                    html_content=html_body,
                    recipients=[user.email]
                )
            except Exception as e:
                logger.exception(
                    f"Welcome email failed for {user.email}: {str(e)}"
                )

        threading.Thread(
            target=send_async,
            daemon=True
        ).start()
        
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
        response.data['user'] = UserSerializer(user).data
        access_token = response.data.pop('access', None)
        refresh_token = response.data.pop('refresh', None)

        if access_token:
            response.set_cookie(
                key='access_token',
                value=access_token,
                httponly=True,
                secure=True, 
                samesite='None',
                max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()),   
            )

        if refresh_token:
            response.set_cookie(
                key='refresh_token',
                value=refresh_token,
                httponly=True,
                secure=True,
                samesite='None',
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

        context = {
            "first_name": user.first_name,
            "reset_url": reset_url,
            "duration_minutes": 10,
            "frontend_url": settings.FRONTEND_URL,
        }

        def send_async():
            try:
                AuthenticationService.send_template_email(
                    to_email=user.email,
                    subject="Reset Your Password",
                    template_name="emails/password_reset.html",
                    context=context,
                )

            except Exception as e:
                logger.exception(
                    f"Failed to send password reset email to {user.email}: {str(e)}"
                )

        threading.Thread(
            target=send_async,
            daemon=True
        ).start()

    @staticmethod
    def send_password_reset_success_email(user):

        context = {
            "first_name": user.first_name,
            "timestamp": timezone.localtime(
                timezone.now()
            ).strftime("%B %d, %Y at %I:%M %p"),
            "frontend_url": settings.FRONTEND_URL,
        }

        def send_async():
            try:
                AuthenticationService.send_template_email(
                    to_email=user.email,
                    subject="Your NexusShare password has been reset",
                    template_name="emails/password_reset_success.html",
                    context=context,
                )
            except Exception as e:
                logger.exception(
                    f"Failed to send password reset success email to {user.email}: {str(e)}"
                )

        threading.Thread(
            target=send_async,
            daemon=True
        ).start()

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

        if user.check_password(password):
            return False, "Please choose a password that has not been used previously"

        user.set_password(password)
        user.save()
        AuthenticationService.send_password_reset_success_email(user)

        return True, "Password reset successful"

    @staticmethod
    def send_reactivation_otp(email):
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return False, "If the account is eligible for reactivation, an OTP has been sent."

        if user.is_active:
            return False, "Account is already active."

        if not user.disabled_at:
            return False, "Account cannot be reactivated."

        delta = timezone.now() - user.disabled_at

        if delta.days > 30:
            return False, "Reactivation window has expired. Account is scheduled for deletion."

        otp = str(random.randint(100000, 999999))

        user.activation_otp = otp
        user.activation_otp_created_at = timezone.now()
        user.save()

        context = {
            "first_name": user.first_name,
            "otp": otp,
            "frontend_url": settings.FRONTEND_URL,
        }

        def send_async():
            try:
                AuthenticationService.send_template_email(
                    to_email=user.email,
                    subject="NexusShare — Account Reactivation OTP",
                    template_name="emails/reactivation_otp.html",
                    context=context,
                )

            except Exception as e:
                logger.exception(
                    f"Failed to send reactivation OTP to {user.email}: {str(e)}"
                )

        threading.Thread(
            target=send_async,
            daemon=True
        ).start()

        return True, "OTP sent to your registered email."

    @staticmethod
    def verify_reactivation_otp(email, otp):
        """Verify the OTP and reactivate the account."""
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return False, "No account found with this email."

        if user.is_active:
            return False, "Account is already active."

        if not user.activation_otp or not user.activation_otp_created_at:
            return False, "No OTP was requested. Please request a new one."

        # Check 10-minute expiry
        delta = timezone.now() - user.activation_otp_created_at
        if delta.total_seconds() > 600:
            user.activation_otp = None
            user.activation_otp_created_at = None
            user.save()
            return False, "OTP has expired. Please request a new one."

        if user.activation_otp != otp:
            return False, "Invalid OTP. Reactivation failed."

        # Reactivate
        user.is_active = True
        user.disabled_at = None
        user.activation_otp = None
        user.activation_otp_created_at = None
        user.save()
        return True, "Account reactivated successfully."