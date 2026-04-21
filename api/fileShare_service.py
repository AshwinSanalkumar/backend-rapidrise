import token
from uuid import UUID
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.exceptions import ObjectDoesNotExist
from .models import SharedLink, UserFile

class FileShareService:
    @staticmethod
    def share_file_via_email(file_id, user, request, data):
        try:
            file_uuid = UUID(file_id)
            file_obj = UserFile.objects.get(id=file_uuid, owner=user)
        except (ValueError, ObjectDoesNotExist):
            return None, "File not found or invalid ID."

        emails = data.get('emails', [])
        if isinstance(emails, str):
            emails = [emails]   
        message = data.get('message', "")
        
        try:
            duration = int(data.get('duration_minutes', 60))
        except (ValueError, TypeError):
            duration = 60

        expiry = timezone.now() + timedelta(minutes=duration)
        shared_link = SharedLink.objects.create(
            file=file_obj,
            expires_at=expiry
        )

        token = shared_link.token
        full_url = f"{settings.FRONTEND_URL}/public/{token}"
        # relative_url = reverse('shared-file', kwargs={'token': shared_link.token})
        # full_url = request.build_absolute_uri(relative_url)

        if emails:
            FileShareService._send_notification(
                file_name=file_obj.filename,
                url=full_url,
                duration=duration,
                recipients=emails,
                personal_message=message,
                sender=user
            )

        return {
            "download_url": full_url,
            "expires_at": shared_link.expires_at,
            "recipients": emails
        }, None

    @staticmethod
    def _send_notification(file_name, url, duration, recipients, personal_message, sender):
        sender_display = sender.get_full_name() or sender.username
        subject = f"Secure file shared with you: {file_name}"
        
        body = (
            f"Hello,\n\n"
            f"{sender_display} has shared a file with you via NexusShare.\n\n"
            f"File: {file_name}\n"
            f"Access Link: {url}\n"
            f"This link will expire in {duration} minutes.\n\n"
        )
        
        if personal_message:
            body += f"Message from sender:\n\"{personal_message}\"\n\n"

        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients if len(recipients) == 1 else [],
            bcc=recipients if len(recipients) > 1 else [],
        )
        # Send immediately; ensure settings.py SMTP is configured
        email.send(fail_silently=False)

    @staticmethod
    def get_file_from_token(token_str):
        """
        Validates the token and returns the file object if access is permitted.
        """
        try:
            file_token = UUID(token_str)
        except ValueError:
            return None, "Invalid download link format."
        try:
            shared_link = SharedLink.objects.get(token=file_token)
        except SharedLink.DoesNotExist:
            return None, "Invalid link."
        if shared_link.is_accessed:
            return None, "This link has already been used and is no longer valid."
        if timezone.now() > shared_link.expires_at:
            return None, "This link has expired."
        shared_link.is_accessed = True
        shared_link.save()

        return shared_link.file, None