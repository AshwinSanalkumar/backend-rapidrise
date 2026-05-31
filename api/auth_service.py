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
from django.template.loader import render_to_string
from django.utils import timezone
import resend


token_generator = PasswordResetTokenGenerator()


class AuthenticationService:
    @staticmethod
    def change_password(user, current_password, new_password):
        """Validates current password and updates to new password."""
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
        AuthenticationService.send_welcome_email(user)
        return user
    #welcome email
    @staticmethod
    def send_welcome_email(user):
        import threading
        from django.core.mail import EmailMessage

        subject = "Welcome to NexusShare!"
        context = {
            'first_name': user.first_name,
            'frontend_url': settings.FRONTEND_URL
        }
        
        html_body = render_to_string('emails/welcome.html', context)
        
        email = EmailMessage(
            subject=subject,
            body=html_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.content_subtype = "html"
        
        def send_async():
            try:
                email.send(fail_silently=True)
            except Exception:
                pass
                
        threading.Thread(target=send_async).start()
    
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

        subject = "Reset Your Password"

        duration = 10
        context = {
            'first_name': user.first_name,
            'reset_url': reset_url,
            'duration_minutes': duration,
            'frontend_url': settings.FRONTEND_URL
        }
        
        html_body = render_to_string('emails/password_reset.html', context)
        
        message = f"Hi {user.first_name},\n\nClick the link below to reset your password:\n{reset_url}\n\nThis link will expire in {duration} minutes.\n\nIf you did not request this, please ignore this email."

        resend.api_key = settings.RESEND_API_KEY

        try:
            result = resend.Emails.send({
                "from": "NexusShare <onboarding@resend.dev>",
                "to": [user.email],
                "subject": subject,
                "text": message,
                "html": html_body,
            })
            print("PASSWORD RESET EMAIL SENT:", result)
        except Exception as e:
            print("PASSWORD RESET EMAIL ERROR:", str(e))
            raise

    @staticmethod
    def send_password_reset_success_email(user):
        import threading
        from django.core.mail import EmailMessage
        from django.utils import timezone

        subject = "Your NexusShare password has been reset"
        context = {
            'first_name': user.first_name,
            'timestamp': timezone.localtime(timezone.now()).strftime('%B %d, %Y at %I:%M %p'),
            'frontend_url': settings.FRONTEND_URL
        }
        
        try:
            html_body = render_to_string('emails/password_reset_success.html', context)
        except Exception:
            html_body = None
            
        plain = f"Hi {user.first_name},\n\nYour NexusShare password was successfully reset on {context['timestamp']}.\n\nIf you did not request this, please contact support immediately."

        email = EmailMessage(
            subject=subject,
            body=html_body or plain,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        if html_body:
            email.content_subtype = "html"
        
        def send_async():
            try:
                email.send(fail_silently=True)
            except Exception:
                pass
                
        threading.Thread(target=send_async).start()

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

        if user.check_password(password):
            return False, "Please choose a password that has not been used previously"

        user.set_password(password)
        user.save()
        AuthenticationService.send_password_reset_success_email(user)

        return True, "Password reset successful"

    @staticmethod
    def send_reactivation_otp(email):
        """Generate a 6-digit OTP, save it on the user, and email it."""
        import random, threading
        from django.core.mail import EmailMessage

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

        subject = "NexusShare — Account Reactivation OTP"
        context = {
            'first_name': user.first_name,
            'otp': otp,
            'frontend_url': settings.FRONTEND_URL
        }

        try:
            html_body = render_to_string('emails/reactivation_otp.html', context)
        except Exception:
            html_body = None

        plain = (
            f"Hi {user.first_name},\n\n"
            f"Your account reactivation OTP is: {otp}\n\n"
            f"This code expires in 10 minutes.\n\n"
            f"If you did not request this, please ignore this email."
        )

        email_msg = EmailMessage(
            subject=subject,
            body=html_body or plain,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        if html_body:
            email_msg.content_subtype = "html"

        def send_async():
            try:
                email_msg.send(fail_silently=True)
            except Exception:
                pass

        threading.Thread(target=send_async).start()
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
        from django.utils import timezone as tz
        delta = tz.now() - user.activation_otp_created_at
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