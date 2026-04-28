# SERVICES FOR FILE UPLOAD DOWNLOAD.
import hashlib
from rest_framework.exceptions import ValidationError
from django.conf import settings
from .models import UserFile, SharedLink
from collections import defaultdict
from django.utils import timezone
import calendar
from datetime import datetime, date
from django.db.models import Count, Sum
from django.utils.timezone import make_aware
from datetime import timedelta
from django.urls import reverse
from django.core.mail import EmailMessage


class FileStorageService:

    @staticmethod
    def get_user_files(user, search_term=None, favorites_only=False):
        # Orders by most recent first (-uploaded_at)
        queryset = UserFile.objects.filter(
            owner=user, 
            is_deleted=False
        )
        
        if favorites_only:
            queryset = queryset.filter(is_favorite=True)
            
        if search_term:
            queryset = queryset.filter(
                display_name__icontains=search_term
            ) | queryset.filter(
                filename__icontains=search_term
            ) | queryset.filter(
                description__icontains=search_term
            )
            
        return queryset.order_by('-uploaded_at')

    @staticmethod
    def get_deleted_files(user):
        """
        Returns all soft-deleted files for the user, ordered by deletion timestamp (newest first).
        """
        return UserFile.objects.filter(
            owner=user, 
            is_deleted=True
        ).order_by('-deleted_at')

    ALLOWED_TYPES = {
        'image/jpeg',
        'image/png',
        'application/pdf',
        'video/mp4',
        'text/plain'
    }

    @staticmethod
    def compute_checksum(file_obj, chunk_size=8192):
        """
        Compute SHA-256 checksum without loading entire file into memory.
        """
        sha256 = hashlib.sha256()

        file_obj.seek(0)
        for chunk in iter(lambda: file_obj.read(chunk_size), b''):
            sha256.update(chunk)
        file_obj.seek(0)

        return sha256.hexdigest()

    @staticmethod
    def validate_file(file_obj):
        """
        Validate file size and MIME type.
        """
        # Size validation
        if file_obj.size > settings.MAX_UPLOAD_SIZE:
            max_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(f"File exceeds {max_mb:.2f} MB limit.")

        # MIME validation (basic - header based)
        mime_type = file_obj.content_type or 'application/octet-stream'
        if mime_type not in FileStorageService.ALLOWED_TYPES:
            raise ValidationError(f"File type '{mime_type}' is not supported.")

        return mime_type

    @staticmethod
    def check_duplicate(checksum, user):
        """
        Check if a non-deleted file with the same checksum exists for this user.
        Soft-deleted files are intentionally excluded so that re-uploading a
        trashed file always succeeds.
        """
        return UserFile.objects.filter(
            owner=user,
            checksum=checksum,
            is_deleted=False
        ).first()

    @staticmethod
    def _resolve_duplicate_filename(base_name, user):
        import os
        stem, ext = os.path.splitext(base_name)   # ('report', '.pdf')
        # Count active files whose filename matches <stem>(<N>)<ext> or <stem><ext>
        existing_count = UserFile.objects.filter(
            owner=user,
            is_deleted=False,
            filename__startswith=stem,
        ).count()

        if existing_count == 0:
            return base_name
        return f"{stem}({existing_count}){ext}"

    @staticmethod
    def process_and_store_file(user, file_obj, display_name=None, description=None):
        """
        Main upload handler:
        - validates file
        - computes checksum
        - checks for active duplicates and renames if needed
        - always stores a new record (never silently returns an existing one)

        Duplicate naming pattern:  report.pdf → report(1).pdf → report(2).pdf …
        Soft-deleted files are ignored so re-uploading a trashed file works.
        """

        # Step 1: Validate
        mime_type = FileStorageService.validate_file(file_obj)

        # Step 2: Compute checksum
        checksum = FileStorageService.compute_checksum(file_obj)

        # Step 3: Determine final filename
        # If an active non-deleted file with the same checksum exists, rename.
        existing_file = FileStorageService.check_duplicate(checksum, user)
        if existing_file:
            resolved_filename = FileStorageService._resolve_duplicate_filename(
                file_obj.name, user
            )
        else:
            resolved_filename = file_obj.name

        # Step 4: Save file (always create a new record)
        return UserFile.objects.create(
            owner=user,
            content=file_obj,
            filename=resolved_filename,
            display_name=display_name or resolved_filename,
            description=description,
            file_size_bytes=file_obj.size,
            mime_type=mime_type,
            checksum=checksum
        )
    
    @staticmethod
    def update_file(file, data):
        """
        api : api/products/update/<product id>/
        Update a particular product
        """
        file.display_name = data.get('display_name', file.display_name)
        file.description = data.get('description', file.description)
       
        file.save()
        return file

    @staticmethod
    def toggle_file_favorite(user, file_instance):
        """
        Toggles the favorite status for a specific user and file.
        """
        file_instance.is_favorite = not file_instance.is_favorite
        file_instance.save()
        return file_instance

    @staticmethod
    def soft_delete_file(user, file_instance):
        """
        Marks the file as deleted and records the deletion timestamp.
        """
        from django.utils import timezone
        file_instance.is_deleted = True
        file_instance.deleted_at = timezone.now()
        file_instance.save()
        return file_instance
    
    @staticmethod
    def hard_delete_file(file_instance):
        """
        Toggles the favorite status for a specific user and file.
        """
        file_instance.delete()
        return None
    
    @staticmethod
    def restore_file(user, file_instance):
        """
        Restores a soft-deleted file and clears its deletion timestamp.
        """
        file_instance.is_deleted = False
        file_instance.deleted_at = None
        file_instance.save()
        return file_instance


    @staticmethod
    def restore_all_files(user):
        """
        Restores all files marked as deleted for the given user and clears their deletion timestamps.
        """
        updated_count = UserFile.objects.filter(owner=user, is_deleted=True).update(
            is_deleted=False,
            deleted_at=None
        )
        return updated_count

    @staticmethod
    def empty_trash(user):
        """
        Permanently deletes all files in the trash for the given user.
        """
        deleted_files = UserFile.objects.filter(owner=user, is_deleted=True)
        count = deleted_files.count()
        for file_obj in deleted_files:
            FileStorageService.hard_delete_file(file_obj)
        return count


    @staticmethod
    def get_upload_history(user, year, month):
        # 1. Optimize range filtering
        _, last_day = calendar.monthrange(year, month)
        start_date = make_aware(datetime(year, month, 1))
        end_date = make_aware(datetime(year, month, last_day, 23, 59, 59))

        # 2. Fetch Uploads
        files_qs = UserFile.objects.filter(
            owner=user,
            uploaded_at__range=(start_date, end_date),
            is_deleted=False
        ).only('id', 'display_name', 'filename', 'file_size_bytes', 'uploaded_at').order_by('-uploaded_at')

        # 3. Fetch Shares
        shares_qs = SharedLink.objects.filter(
            file__owner=user,
            created_at__range=(start_date, end_date)
        ).select_related('file').only(
            'token', 
            'file__display_name', 
            'file__filename', 
            'file__file_size_bytes',
            'receipient_email', 
            'created_at', 
            'expires_at',
            'is_revoked',
            'message',
            'file_id'
        ).order_by('-created_at')

        # 4. Global Stats
        total_uploads = UserFile.objects.filter(owner=user, is_deleted=False).count()
        total_shares = SharedLink.objects.filter(file__owner=user).count()

        # 5. Grouping data for the calendar
        history = defaultdict(list)
        
        # Add uploads to history
        for f in files_qs:
            day = f.uploaded_at.day
            local_time = timezone.localtime(f.uploaded_at)
            history[day].append({
                "type": "upload",
                "id": str(f.id),
                "name": f.display_name or f.filename,
                "size": f.file_size_bytes,
                "time": local_time.strftime("%H:%M"),
            })

        # Add shares to history
        for s in shares_qs:
            day = s.created_at.day
            local_time = timezone.localtime(s.created_at)
            history[day].append({
                "type": "share",
                "file_id": str(s.file_id),
                "file_name": s.file.display_name or s.file.filename,
                "recipient_email": s.receipient_email or "Public Link",
                "time": local_time.strftime("%H:%M"),
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "is_revoked": s.is_revoked,
                "is_expired": s.is_expired,
                "message": s.message,
                "file_size_bytes": s.file.file_size_bytes
            })

        # Sort daily events by time descending
        for d in history:
            history[d].sort(key=lambda x: x['time'], reverse=True)

        return {
            "history": history,
            "month_stats": {
                "upload_count": files_qs.count(),
                "share_count": shares_qs.count(),
                "total_size": files_qs.aggregate(Sum('file_size_bytes'))['file_size_bytes__sum'] or 0,
            },
            "global_stats": {
                "total_uploads": total_uploads,
                "total_shares": total_shares
            }
        }
    

    @staticmethod
    def create_shareable_data(file_obj, request, duration_minutes=5, emails=None, message=""):
        """
        api: api/files/<file_id>/generate-link/
        Generate Secure Link and optionally send email to recipients
        """
        try:
            minutes = int(duration_minutes) if duration_minutes else 5
        except (ValueError, TypeError):
            minutes = 5
            
        expiry = timezone.now() + timedelta(minutes=minutes)
        shared_link = SharedLink.objects.create(
            file=file_obj,
            expires_at=expiry
        )
        
        relative_url = reverse('public-download', kwargs={'token': shared_link.token})
        full_url = request.build_absolute_uri(relative_url)
        
        # Email Notification Logic
        if emails and isinstance(emails, list) and len(emails) > 0:
            owner_name = request.user.get_full_name() or request.user.username
            subject = f"{owner_name} shared a file with you: {file_obj.filename}"
            
            # Simple text body (can be upgraded to a template)
            body = (
                f"Hello,\n\n"
                f"{owner_name} has shared a file with you via NexusShare.\n\n"
                f"File: {file_obj.filename}\n"
                f"Secure Link: {full_url}\n"
                f"Expires In: {minutes} minutes\n\n"
            )
            
            if message:
                body += f"Message from {owner_name}:\n\"{message}\"\n\n"
                
            body += "Please download the file before the link expires."

            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.DEFAULT_FROM_EMAIL], # BCC recipients to keep them private from each other
                bcc=emails, 
            )
            email.send(fail_silently=False)

        return {
            "download_url": full_url,
            "filename": file_obj.filename,
            "expires_at": shared_link.expires_at,
            "sent_to": emails if emails else []
        }

    