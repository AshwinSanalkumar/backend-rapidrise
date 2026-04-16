# SERVICES FRO FILE UPLOAD DOWNLOAD.
from rest_framework.exceptions import ValidationError
from django.conf import settings
from .models import UserFile
from collections import defaultdict
from django.utils import timezone
import calendar
from datetime import datetime, date
from django.db.models import Count, Sum
from django.utils.timezone import make_aware

class FileStorageService:

    @staticmethod
    def get_user_files(user):
        # Orders by most recent first (-uploaded_at)
        return UserFile.objects.filter(
            owner=user, 
            is_deleted=False
        ).order_by('-uploaded_at')

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
    
    # ... your existing process_and_store_file method ...

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
    