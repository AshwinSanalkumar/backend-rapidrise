import threading
from uuid import UUID
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.exceptions import ObjectDoesNotExist
from .models import SharedLink, UserFile

def send_email_async(email):
    """
    Helper function to send email in a background thread.
    """
    try:
        email.send(fail_silently=True)
    except:
        pass

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
        
        created_links_info = []

        if not emails:
            # Fallback to single link without recipient if no emails provided
            shared_link = SharedLink.objects.create(
                file=file_obj, 
                expires_at=expiry,
                message=message
            )
            token = shared_link.token
            full_url = f"{settings.FRONTEND_URL}/public/{token}"
            created_links_info.append({"url": full_url, "expires_at": expiry, "recipient": "Public"})
        else:
            for email_addr in emails:
                shared_link = SharedLink.objects.create(
                    file=file_obj,
                    expires_at=expiry,
                    receipient_email=email_addr,
                    message=message
                )
                token = shared_link.token
                full_url = f"{settings.FRONTEND_URL}/public/{token}"
                
                FileShareService._send_notification(
                    file_name=file_obj.filename,
                    url=full_url,
                    duration=duration,
                    recipients=[email_addr],
                    personal_message=message,
                    sender=user
                )
                created_links_info.append({
                    "url": full_url,
                    "expires_at": expiry,
                    "recipient": email_addr
                })

        return {
            "links": created_links_info,
            "count": len(created_links_info)
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
        # Offload sending to a background thread to prevent request blocking
        thread = threading.Thread(target=send_email_async, args=(email,))
        thread.start()

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
            
        if shared_link.is_revoked:
            return None, "This link has been revoked by the owner."
            
        if timezone.now() > shared_link.expires_at:
            return None, "This link has expired."
        
        shared_link.is_accessed = True
        shared_link.accessed_at = timezone.now()
        shared_link.save()
        return shared_link.file, None

    @staticmethod
    def revoke_shared_link(token_str, user):
        """
        Revokes a shared link.
        """
        try:
            link_token = UUID(token_str)
            shared_link = SharedLink.objects.get(token=link_token, file__owner=user)
        except (ValueError, SharedLink.DoesNotExist):
            return False, "Link not found or access denied."
            
        shared_link.is_revoked = True
        shared_link.revoked_at = timezone.now()
        shared_link.save()
        return True, "Link revoked successfully."

    @staticmethod
    def list_user_shares(user, search_term=None, status_filter=None, file_id=None):
        """
        Returns all active/inactive shared links created by the user, with optional search and status filter.
        """
        from django.db.models import Q
        queryset = SharedLink.objects.filter(file__owner=user).select_related('file').order_by('-created_at')
        
        now = timezone.now()

        if file_id:
            queryset = queryset.filter(file_id=file_id)

        if status_filter:
            if status_filter == 'active':
                queryset = queryset.filter(is_revoked=False, expires_at__gt=now)
            elif status_filter == 'accessed':
                queryset = queryset.filter(is_accessed=True)
            elif status_filter == 'expired':
                queryset = queryset.filter(expires_at__lte=now)
            elif status_filter == 'revoked':
                queryset = queryset.filter(is_revoked=True)

        if search_term:
            queryset = queryset.filter(
                Q(file__filename__icontains=search_term) |
                Q(file__display_name__icontains=search_term) |
                Q(receipient_email__icontains=search_term)
            )
            
        return queryset