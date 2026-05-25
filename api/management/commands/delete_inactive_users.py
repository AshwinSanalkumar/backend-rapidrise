from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from api.models import User
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
import shutil
import os
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Permanently deletes user accounts that have been inactive for more than 30 days'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting inactive user account cleanup...")
        threshold_date = timezone.now() - timedelta(days=30)
        queryset = User.objects.filter(
            is_active=False,
            disabled_at__lt=threshold_date
        )

        deleted_count = 0
        total_count = queryset.count()
        
        self.stdout.write(f"Found {total_count} accounts eligible for deletion.")

        for user in queryset:
            email_sent = False
            try:
                self.send_deletion_email(user)
                email_sent = True
            except Exception as e:
                logger.error(f"Failed to send deletion email to {user.email}: {str(e)}")
                self.stdout.write(self.style.WARNING(f"Could not send email to {user.email}, proceeding with deletion."))

            try:
                user_id = user.id
                user_media_path = os.path.join(settings.MEDIA_ROOT, f"user_{user_id}")
                
                if os.path.exists(user_media_path):
                    shutil.rmtree(user_media_path)
                    self.stdout.write(f"Deleted storage for user {user_id}")


                user.delete()
                deleted_count += 1
                self.stdout.write(self.style.SUCCESS(f"Successfully deleted user: {user.email}"))

            except Exception as e:
                logger.error(f"Error deleting user {user.email}: {str(e)}")
                self.stderr.write(self.style.ERROR(f"Error deleting user {user.email}: {str(e)}"))

        self.stdout.write(self.style.SUCCESS(f"Cleanup complete. Deleted {deleted_count} out of {total_count} accounts."))

    def send_deletion_email(self, user):
        """Sends the final account deletion notification."""
        subject = "NexusShare — Account Deleted"
        context = {
            'first_name': user.first_name,
            'frontend_url': settings.FRONTEND_URL
        }
        
        try:
            html_body = render_to_string('emails/account_deleted.html', context)
        except Exception:
            html_body = None

        plain_text = (
            f"Hi {user.first_name},\n\n"
            f"As requested, your NexusShare account has been permanently deleted. "
            f"All your data and files have been removed from our systems.\n\n"
            f"Thank you for using NexusShare."
        )

        email = EmailMessage(
            subject=subject,
            body=html_body or plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        if html_body:
            email.content_subtype = "html"
        email.send(fail_silently=False)
