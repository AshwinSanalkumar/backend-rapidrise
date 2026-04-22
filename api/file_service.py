# SERVICES FRO FILE UPLOAD DOWNLOAD.
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
    def process_and_store_file(user, file_obj,display_name,description):
        """
        api : api/files/upload/
        Upload the file
        """
        if file_obj.size > settings.MAX_UPLOAD_SIZE:
            max_mb = settings.MAX_UPLOAD_SIZE
            raise ValidationError(f"File exceeds {max_mb}MB limit.")
        mime_type = file_obj.content_type or 'application/octet-stream'
        ALLOWED_TYPES = [
            'image/jpeg', 'image/png', 'application/pdf', 
            'video/mp4', 'text/plain'
        ]

        if mime_type not in ALLOWED_TYPES:
            raise ValidationError(f"File type {mime_type} is not supported.")
        return UserFile.objects.create(
            owner=user,
            content=file_obj,
            filename=file_obj.name,
            display_name=display_name,
            description=description,
            file_size_bytes=file_obj.size,
            mime_type=mime_type
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
        Toggles the favorite status for a specific user and file.
        """
        file_instance.is_deleted = True
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
        Toggles the favorite status for a specific user and file.
        """
        file_instance.is_deleted = False
        file_instance.save()
        return file_instance


    @staticmethod
    def restore_all_files(user):
        """
        Restores all files marked as deleted for the given user.
        """
        updated_count = UserFile.objects.filter(owner=user, is_deleted=True).update(is_deleted=False)
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
        # 1. Optimize range filtering (Works better with DB indexes than __year/__month)
        _, last_day = calendar.monthrange(year, month)
        start_date = make_aware(datetime(year, month, 1))
        end_date = make_aware(datetime(year, month, last_day, 23, 59, 59))
        # 2. Optimized Query: Fetch only fields we need
        files_qs = UserFile.objects.filter(
            owner=user,
            uploaded_at__range=(start_date, end_date),
            is_deleted=False
        ).only('id', 'display_name', 'filename', 'file_size_bytes', 'uploaded_at').order_by('-uploaded_at')
        # 3. Database Aggregation: Calculate totals directly in the DB
        # This prevents loading thousands of objects into memory just for counts
        stats = files_qs.aggregate(
            count=Count('id'),
            total_size=Sum('file_size_bytes')
        )
        # 4. Global Stats (Optional: Can still include for the overall "Total Uploads")
        total_uploads = UserFile.objects.filter(owner=user, is_deleted=False).count()
        # 5. Grouping data for the calendar
        history = defaultdict(list)
        for f in files_qs:
            day = f.uploaded_at.day
            local_time = timezone.localtime(f.uploaded_at)
            history[day].append({
                "id": str(f.id),
                "name": f.display_name or f.filename,
                "size": f.file_size_bytes,
                "time": local_time.strftime("%H:%M"),
            })
        return {
            "history": history,
            "month_stats": {
                "count": stats['count'] or 0,
                "total_size": stats['total_size'] or 0,
            },
            "global_stats": {
                "total_uploads": total_uploads
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

    