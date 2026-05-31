import threading
import zipfile
from io import BytesIO
from uuid import UUID
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from .models import SharedLink, UserFile

def send_email_async(email):
    try:
        result = email.send(fail_silently=False)
        print("EMAIL SENT:", result)
    except Exception as e:
        print("EMAIL ERROR:", str(e))

class FileShareService:
    @staticmethod
    def bulk_share_files(user, file_ids, request, data):
        """
        Creates a zip archive of multiple files and shares it.
        """
        from .file_service import FileStorageService
        
        if not file_ids:
            return None, "No files provided"
            
        if len(file_ids) != len(set(file_ids)):
            return None, "Duplicate file IDs are not allowed."

        files = UserFile.objects.filter(
            id__in=file_ids,
            owner=user
        )

        if files.count() != len(file_ids):
            return None, "Some files were not found or do not belong to you."

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fid in file_ids:
                try:
                    f = UserFile.objects.get(id=fid, owner=user)
                    zf.writestr(f.filename, f.content.read())
                except Exception:
                    continue
        buffer.seek(0)

        zip_name = f"Shared_Batch_{timezone.now().strftime('%Y%m%d%H%M%S')}.zip"
        zip_obj = ContentFile(buffer.read(), name=zip_name)
        zip_obj.content_type = 'application/zip'
        
        new_file = FileStorageService.process_and_store_file(
            user=user,
            file_obj=zip_obj,
            display_name=f"Bulk Shared Archive ({len(file_ids)} files)",
            description="[SYSTEM_INTERNAL_SHARE]",
            consume_quota=False
        )
        
        return FileShareService.share_file_via_email(
            file_id=str(new_file.id),
            user=user,
            request=request,
            data=data
        )

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

        try:
            download_limit = int(data.get('download_limit', 5))
        except (ValueError, TypeError):
            download_limit = 5

        expiry = timezone.now() + timedelta(minutes=duration)
        
        created_links_info = []

        if not emails:
            shared_link = SharedLink.objects.create(
                file=file_obj, 
                expires_at=expiry,
                message=message,
                download_limit=download_limit
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
                    message=message,
                    download_limit=download_limit
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
        
        total_minutes = int(duration)
        if total_minutes < 60:
            duration_display = f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"
        elif total_minutes < 24 * 60:
            hours = total_minutes // 60
            mins = total_minutes % 60
            duration_display = f"{hours} hour{'s' if hours != 1 else ''}"
            if mins:
                duration_display += f" and {mins} minute{'s' if mins != 1 else ''}"
        else:
            days = total_minutes // (24 * 60)
            hours = (total_minutes % (24 * 60)) // 60
            duration_display = f"{days} day{'s' if days != 1 else ''}"
            if hours:
                duration_display += f" and {hours} hour{'s' if hours != 1 else ''}"
        
        context = {
            'file_name': file_name,
            'url': url,
            'duration_display': duration_display,
            'personal_message': personal_message,
            'sender_display': sender_display,
            'frontend_url': settings.FRONTEND_URL
        }
        
        html_body = render_to_string('emails/file_share.html', context)

        email = EmailMessage(
            subject=subject,
            body=html_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients if len(recipients) == 1 else [],
            bcc=recipients if len(recipients) > 1 else [],
        )
        email.content_subtype = "html"  
        import traceback

        try:
            result = email.send(fail_silently=False)
            print("EMAIL SENT:", result)
        except Exception as e:
            print("EMAIL ERROR:", str(e))
            print(traceback.format_exc())
            raise
        print("EMAIL SENT SUCCESSFULLY")    

    @staticmethod
    def get_file_from_token(token_str, increment_type=None):
        """
        Validates the token and returns (file, shared_link, error).
        increment_type: 'access' (link opened) or 'download' (file fetched).
        """
        try:
            file_token = UUID(token_str)
        except ValueError:
            return None, None, "Invalid download link format."
        try:
            shared_link = SharedLink.objects.get(token=file_token)
        except SharedLink.DoesNotExist:
            return None, None, "Invalid link."
            
        if shared_link.is_revoked:
            return None, None, "This link has been revoked by the owner."
            
        if timezone.now() > shared_link.expires_at:
            return None, None, "This link has expired."

        if increment_type == 'access':
            if not shared_link.is_accessed:
                shared_link.is_accessed = True
                shared_link.save()
        elif increment_type == 'download':
            if shared_link.download_limit == 0:
                return None, None, "This link is for preview only. Downloads are disabled."
            
            if shared_link.download_limit > 0 and shared_link.download_count >= shared_link.download_limit:
                return None, None, "Download limit reached for this link."
            
            shared_link.download_count += 1
            shared_link.save()

        return shared_link.file, shared_link, None

    @staticmethod
    def get_public_tracking_headers(shared_link):
        return {
            'X-Download-Limit': str(shared_link.download_limit),
            'X-Download-Count': str(shared_link.download_count),
            'X-Expires-At': shared_link.expires_at.isoformat() if shared_link.expires_at else '',
            'Access-Control-Expose-Headers': 'Content-Disposition, X-Download-Limit, X-Download-Count, X-Expires-At'
        }

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