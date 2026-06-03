# SERVICES FOR FILE UPLOAD DOWNLOAD.
import logging
import hashlib
import magic
import mimetypes
import os
import uuid
import calendar
from datetime import datetime, date, timedelta
from collections import defaultdict
from rest_framework.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone
from django.utils.timezone import make_aware
from django.db.models import Count, Sum, Q, Case, When, Value, IntegerField
from django.urls import reverse
from django.core.mail import EmailMessage
from django.db import transaction
from django.core.files import File as DjangoFile
from .models import UserFile, SharedLink, User, ChunkedUpload
from .supabase_storage import SupabaseStorageService

logger = logging.getLogger('files')


class FileStorageService:
    IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    DOC_TYPES = [
        'application/pdf', 
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'text/plain',
        'application/zip',
        'application/x-zip-compressed'
    ]
    MEDIA_TYPES = ['video/mp4', 'video/quicktime', 'audio/mpeg', 'audio/mp4', 'audio/x-m4a', 'audio/wav']
    
    ALLOWED_TYPES = settings.ALLOWED_TYPES

    # =========================
    # Retrieval & Search
    # =========================

    @staticmethod
    def get_user_files(user, search_term=None, favorites_only=False):
        # Orders by most recent first (-uploaded_at)
        queryset = UserFile.objects.filter(
            owner=user, 
            is_deleted=False
        ).exclude(description='[SYSTEM_INTERNAL_SHARE]')
        
        if favorites_only:
            queryset = queryset.filter(is_favorite=True)
            
        if search_term:
            queryset = queryset.filter(
                Q(display_name__icontains=search_term) |
                Q(filename__icontains=search_term) |
                Q(description__icontains=search_term)
            )
            
        return queryset.order_by('-uploaded_at')

    # =========================
    # Upload Management
    # =========================

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
    def validate_file(file_obj, check_size=True):
        """
        Validate file size and MIME type.
        """
        # Size validation
        if check_size and file_obj.size > settings.MAX_UPLOAD_SIZE:
            max_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(f"File exceeds {max_mb:.2f} MB limit.")

        # MIME validation (Accurate content-based detection using python-magic)
        # Read the first 2048 bytes for magic number detection
        file_obj.seek(0)
        file_content = file_obj.read(2048)
        file_obj.seek(0) # Reset pointer
        
        mime_type = magic.from_buffer(file_content, mime=True)
        
        # If magic is too generic or fails, fall back to extension-based guessing
        if not mime_type or mime_type == 'application/octet-stream':
            guessed_type = mimetypes.guess_type(file_obj.name)[0]
            if guessed_type:
                mime_type = guessed_type
            elif not mime_type:
                # If both fail, use a safe default
                mime_type = 'application/octet-stream'

        if mime_type not in FileStorageService.ALLOWED_TYPES:
            raise ValidationError(f"File type '{mime_type}' is not supported.")

        return mime_type

    @staticmethod
    def resolve_filename(base_name, user, checksum):
        """
        Ensures a unique filename for the user.
        Renames if:
        1. A file with the same name already exists.
        2. A file with the same content (checksum) already exists.
        """
        name_exists = UserFile.objects.filter(owner=user, filename=base_name, is_deleted=False).exists()
        checksum_exists = FileStorageService.check_duplicate(checksum, user)

        if not (name_exists or checksum_exists):
            return base_name

        stem, ext = os.path.splitext(base_name)
        existing_count = UserFile.objects.filter(
            owner=user,
            is_deleted=False,
            filename__startswith=stem,
        ).count()

        return f"{stem}({existing_count}){ext}"

    @staticmethod
    def process_and_store_file(user, file_obj, display_name=None, description=None, consume_quota=True):
        """
        Main upload handler:
        - validates file
        - computes checksum
        - checks for active duplicates and renames if needed
        - always stores a new record
        """
        with transaction.atomic():
            user_locked = User.objects.select_for_update().get(pk=user.pk)

            if consume_quota and user_locked.consumed_storage + file_obj.size > user_locked.storage_limit_bytes:
                raise ValidationError("Storage limit exceeded. Please clean up your vault.")

            mime_type = FileStorageService.validate_file(file_obj, check_size=consume_quota)


            # Important: compute_checksum reads the stream
            checksum = FileStorageService.compute_checksum(file_obj)
            file_obj.seek(0)  # Reset pointer for saving

            resolved_filename = FileStorageService.resolve_filename(
                file_obj.name,
                user_locked,
                checksum
            )

            # --- SUPABASE INTEGRATION ---
            # Using the exact logic provided by the user
            storage_name = f"uploads/{uuid.uuid4()}_{file_obj.name}"
            
            # Ensure pointer is at start before manual read in Supabase service
            file_obj.seek(0)
            SupabaseStorageService.upload_file(file_obj, storage_name)
            # ---------------------------

            new_file = UserFile.objects.create(
                owner=user_locked,
                content=storage_name, # Storing the supabase path
                filename=resolved_filename,
                display_name=display_name or resolved_filename,
                description=description,
                file_size_bytes=file_obj.size,
                mime_type=mime_type,
                checksum=checksum
            )
            if consume_quota:
                user_locked.consumed_storage += file_obj.size
                user_locked.save(update_fields=['consumed_storage'])
            
            logger.info(f"ACTION PERFORMED: File stored: {new_file.filename} (ID: {new_file.id}) for user {user.email}")
            return new_file

    @staticmethod
    def init_chunked_upload(user, filename, total_size):
        """Initializes a chunked upload session."""
        # Check quota first
        if user.consumed_storage + total_size > user.storage_limit_bytes:
            raise ValidationError("Storage limit exceeded.")

        # Check overall file size limit (100MB)
        if total_size > settings.MAX_UPLOAD_SIZE:
            max_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(f"File exceeds {max_mb:.2f} MB limit.")

        # Create temporary file path
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            
        temp_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(temp_dir, temp_filename)
        
        chunked_upload = ChunkedUpload.objects.create(
            user=user,
            filename=filename,
            total_size=total_size,
            file_path=file_path
        )
        return chunked_upload

    @staticmethod
    def save_chunk(chunked_upload, chunk_file, offset):
        """Saves a chunk of data to the temporary file."""
        if chunked_upload.status != 'uploading':
            raise ValidationError("Upload session is not active.")

        # Extra safety: prevent chunks from being saved if the total size exceeds the limit
        if chunked_upload.total_size > settings.MAX_UPLOAD_SIZE:
            max_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(f"File exceeds {max_mb:.2f} MB limit.")

        # If it's a resume and offset is less than current_size, 
        # we probably want to seek to that offset and overwrite if necessary, 
        # but for simplicity let's assume sequential chunks for now.
        
        with open(chunked_upload.file_path, 'ab') as f:
            f.write(chunk_file.read())
            
        chunked_upload.current_size = os.path.getsize(chunked_upload.file_path)
        chunked_upload.save()
        return chunked_upload

    @staticmethod
    def finalize_chunked_upload(chunked_upload, display_name=None, description=None):
        """Finalizes the chunked upload by creating a UserFile record."""
        if chunked_upload.current_size < chunked_upload.total_size:
            raise ValidationError("Upload incomplete.")

        with open(chunked_upload.file_path, 'rb') as f:
            django_file = DjangoFile(f, name=chunked_upload.filename)
            # content_type will be accurately detected by magic in validate_file
            
            user_file = FileStorageService.process_and_store_file(
                user=chunked_upload.user,
                file_obj=django_file,
                display_name=display_name,
                description=description
            )
            
        # Cleanup
        chunked_upload.status = 'completed'
        chunked_upload.save()
        if os.path.exists(chunked_upload.file_path):
            os.remove(chunked_upload.file_path)
            
        return user_file

    # =========================
    # File Operations
    # =========================

    @staticmethod
    def update_file(file, data):
        """
        Update file metadata (name, description)
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

    # =========================
    # Trash Management
    # =========================

    @staticmethod
    def get_deleted_files(user):
        """
        Returns all soft-deleted files for the user, ordered by deletion timestamp.
        """
        return UserFile.objects.filter(
            owner=user, 
            is_deleted=True
        ).exclude(description='[SYSTEM_INTERNAL_SHARE]').order_by('-deleted_at')

    @staticmethod
    def soft_delete_file(user, file_instance):
        """
        Marks the file as deleted and records the deletion timestamp.
        """
        file_instance.is_deleted = True
        file_instance.deleted_at = timezone.now()
        file_instance.save()
        logger.info(f"ACTION PERFORMED: File moved to trash: {file_instance.filename} (ID: {file_instance.id})")
        return file_instance
    
    @staticmethod
    def hard_delete_file(file_instance):
        """
        Permanently deletes the file and updates user consumption.
        """
        with transaction.atomic():
            size = file_instance.file_size_bytes
            owner_locked = User.objects.select_for_update().get(pk=file_instance.owner.pk)
            
            file_instance.delete()
            
            # Update consumption on the locked user record
            owner_locked.consumed_storage = max(0, owner_locked.consumed_storage - size)
            owner_locked.save(update_fields=['consumed_storage'])
            
            logger.info(f"ACTION PERFORMED: File permanently deleted: {file_instance.filename} (ID: {file_instance.id})")
            return None
    
    @staticmethod
    def restore_file(user, file_instance):
        """
        Restores a soft-deleted file.
        """
        file_instance.is_deleted = False
        file_instance.deleted_at = None
        file_instance.save()
        return file_instance

    @staticmethod
    def restore_all_files(user):
        """
        Restores all files marked as deleted for the given user.
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

    # =========================
    # Duplicate Detection
    # =========================

    @staticmethod
    def check_duplicate(checksum, user):
        """
        Check if a non-deleted file with the same checksum exists.
        """
        return UserFile.objects.filter(
            owner=user,
            checksum=checksum,
            is_deleted=False
        ).first()

    @staticmethod
    def get_duplicate_groups(user):
        """
        Finds files with the same checksum for a user.
        """
        duplicate_checksums = UserFile.objects.filter(
            owner=user, 
            is_deleted=False, 
            checksum__isnull=False
        ).values('checksum').annotate(count=Count('id')).filter(count__gt=1)

        result = []
        for item in duplicate_checksums:
            checksum = item['checksum']
            files = UserFile.objects.filter(
                owner=user, 
                is_deleted=False, 
                checksum=checksum
            ).order_by('uploaded_at') # First one is treated as "original"

            files_data = []
            for i, f in enumerate(files):
                files_data.append({
                    "id": str(f.id),
                    "filename": f.display_name or f.filename,
                    "path": f.filename,
                    "date": f.uploaded_at.strftime("%b %d, %Y"),
                    "size_bytes": f.file_size_bytes,
                    "isOriginal": i == 0
                })

            result.append({
                "checksum": checksum,
                "fileName": files[0].display_name or files[0].filename,
                "size": f"{files[0].file_size_bytes / (1024*1024):.2f} MB",
                "total_size_bytes": files[0].file_size_bytes,
                "instances": files_data
            })
        
        return result

    @staticmethod
    def cleanup_duplicates(user):
        """
        Deletes all duplicate file instances for the user.
        """
        groups = FileStorageService.get_duplicate_groups(user)
        deleted_count = 0
        for group in groups:
            duplicates = [inst for inst in group['instances'] if not inst['isOriginal']]
            for dup in duplicates:
                file_id = dup['id']
                file_obj = UserFile.objects.filter(owner=user, id=file_id).first()
                if file_obj:
                    FileStorageService.hard_delete_file(file_obj)
                    deleted_count += 1
        return deleted_count


    # =========================
    # Analytics
    # =========================

    @staticmethod
    def get_upload_history(user, year, month):
        _, last_day = calendar.monthrange(year, month)
        start_date = make_aware(datetime(year, month, 1))
        end_date = make_aware(datetime(year, month, last_day, 23, 59, 59))

        files_qs = UserFile.objects.filter(
            owner=user,
            uploaded_at__range=(start_date, end_date),
            is_deleted=False
        ).exclude(description='[SYSTEM_INTERNAL_SHARE]').only('id', 'display_name', 'filename', 'file_size_bytes', 'uploaded_at').order_by('-uploaded_at')

        shares_qs = SharedLink.objects.filter(
            file__owner=user,
            created_at__range=(start_date, end_date)
        ).select_related('file').only(
            'token', 'file__display_name', 'file__filename', 'file__file_size_bytes',
            'receipient_email', 'created_at', 'expires_at', 'is_revoked', 'message', 'file_id',
            'is_accessed', 'download_count', 'download_limit', 'revoked_at'
        ).order_by('-created_at')

        total_uploads = UserFile.objects.filter(owner=user, is_deleted=False).exclude(description='[SYSTEM_INTERNAL_SHARE]').count()
        total_shares = SharedLink.objects.filter(file__owner=user).count()

        history = defaultdict(list)
        for f in files_qs:
            day = f.uploaded_at.day
            history[day].append({
                "type": "upload",
                "id": str(f.id),
                "name": f.display_name or f.filename,
                "size": f.file_size_bytes,
                "time": timezone.localtime(f.uploaded_at).strftime("%H:%M"),
            })

        for s in shares_qs:
            day = s.created_at.day
            history[day].append({
                "type": "share",
                "file_id": str(s.file_id),
                "file_name": s.file.display_name or s.file.filename,
                "file_size_bytes": s.file.file_size_bytes,
                "recipient_email": s.receipient_email or "Public Link",
                "receipient_email": s.receipient_email,
                "time": timezone.localtime(s.created_at).strftime("%H:%M"),
                "is_revoked": s.is_revoked,
                "is_expired": s.is_expired,
                "is_accessed": s.is_accessed,
                "download_count": s.download_count,
                "download_limit": s.download_limit,
                "message": s.message,
                "created_at": s.created_at,
                "expires_at": s.expires_at,
                "revoked_at": s.revoked_at
            })

        for d in history:
            history[d].sort(key=lambda x: x['time'], reverse=True)

        total_active_links = SharedLink.objects.filter(file__owner=user, is_revoked=False).exclude(expires_at__lt=timezone.now()).count()

        return {
            "history": history,
            "month_stats": {
                "upload_count": files_qs.count(),
                "share_count": shares_qs.count(),
                "total_size": files_qs.aggregate(Sum('file_size_bytes'))['file_size_bytes__sum'] or 0,
            },
            "global_stats": {
                "total_uploads": total_uploads,
                "total_shares": total_shares,
                "active_links": total_active_links
            }
        }

    @staticmethod
    def get_activity_snapshots(user):
        """
        Calculates daily upload volume (MB) for last 7 days 
        and weekly upload count for last 4 weeks.
        """
        now = timezone.now()
        
        # 1. Daily Volume (Last 7 Days)
        daily = []
        for i in range(6, -1, -1):
            day = now - timedelta(days=i)
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            size_bytes = UserFile.objects.filter(
                owner=user, uploaded_at__range=(start, end), is_deleted=False
            ).exclude(description='[SYSTEM_INTERNAL_SHARE]').aggregate(total=Sum('file_size_bytes'))['total'] or 0
            
            daily.append({
                "label": day.strftime("%b %d"),
                "value": round(size_bytes / (1024 * 1024), 1),
                "unit": "MB"
            })

        # 2. Weekly Count (Last 4 Weeks)
        weekly = []
        for i in range(3, -1, -1):
            start = (now - timedelta(weeks=i+1)).replace(hour=0, minute=0, second=0)
            end = (now - timedelta(weeks=i)).replace(hour=23, minute=59, second=59)
            
            count = UserFile.objects.filter(
                owner=user, uploaded_at__range=(start, end), is_deleted=False
            ).exclude(description='[SYSTEM_INTERNAL_SHARE]').count()
            
            weekly.append({
                "label": f"{start.strftime('%b %d')} - {end.strftime('%b %d')}",
                "value": count,
                "unit": "Files"
            })

        return {"daily": daily, "weekly": weekly}

    @staticmethod
    def get_storage_snapshots(user):
        """
        Calculates storage usage snapshots for the last 6 months.
        """
        snapshots = []
        now = timezone.now()
        
        for i in range(5, -1, -1):
            month = now.month - i
            year = now.year
            while month <= 0:
                month += 12
                year -= 1
            
            _, last_day = calendar.monthrange(year, month)
            month_end = make_aware(datetime(year, month, last_day, 23, 59, 59))
            
            size_at_point = UserFile.objects.filter(
                owner=user, uploaded_at__lte=month_end
            ).filter(
                Q(is_deleted=False) | Q(deleted_at__gt=month_end)
            ).exclude(description='[SYSTEM_INTERNAL_SHARE]').aggregate(total=Sum('file_size_bytes'))['total'] or 0
            
            limit = user.storage_limit_bytes
            percentage = (size_at_point / limit * 100) if limit > 0 else 0
            
            snapshots.append({
                "label": month_end.strftime("%b"),
                "value": round(percentage, 1),
                "raw_size": size_at_point
            })
            
        return snapshots

    # =========================
    # Storage Insights
    # =========================

    @staticmethod
    def get_storage_stats(user):
        """
        Calculates storage usage breakdown across categories.
        """
        stats = UserFile.objects.filter(owner=user, is_deleted=False).exclude(description='[SYSTEM_INTERNAL_SHARE]').aggregate(
            images_size=Sum(Case(When(mime_type__in=FileStorageService.IMAGE_TYPES, then='file_size_bytes'), default=0, output_field=IntegerField())),
            docs_size=Sum(Case(When(mime_type__in=FileStorageService.DOC_TYPES, then='file_size_bytes'), default=0, output_field=IntegerField())),
            media_size=Sum(Case(When(mime_type__in=FileStorageService.MEDIA_TYPES, then='file_size_bytes'), default=0, output_field=IntegerField())),
            others_size=Sum(Case(When(~Q(mime_type__in=FileStorageService.IMAGE_TYPES + FileStorageService.DOC_TYPES + FileStorageService.MEDIA_TYPES), then='file_size_bytes'), default=0, output_field=IntegerField()))
        )

        trash_stats = UserFile.objects.filter(owner=user, is_deleted=True).exclude(description='[SYSTEM_INTERNAL_SHARE]').aggregate(trash_size=Sum('file_size_bytes'))
        trash_bytes = trash_stats['trash_size'] or 0

        total_active_bytes = (stats['images_size'] or 0) + (stats['docs_size'] or 0) + \
                             (stats['media_size'] or 0) + (stats['others_size'] or 0)
        
        total_limit = user.storage_limit_bytes

        def format_size(size_bytes):
            if size_bytes > 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
            return f"{size_bytes / (1024 * 1024):.1f} MB"

        categories = [
            {"name": "Images", "size": format_size(stats['images_size'] or 0), "color": "bg-yellow-500", "percentage": (stats['images_size'] or 0) / total_active_bytes * 100 if total_active_bytes > 0 else 0},
            {"name": "Documents", "size": format_size(stats['docs_size'] or 0), "color": "bg-green-500", "percentage": (stats['docs_size'] or 0) / total_active_bytes * 100 if total_active_bytes > 0 else 0},
            {"name": "Media", "size": format_size(stats['media_size'] or 0), "color": "bg-purple-500", "percentage": (stats['media_size'] or 0) / total_active_bytes * 100 if total_active_bytes > 0 else 0},
            {"name": "Others", "size": format_size(stats['others_size'] or 0), "color": "bg-gray-400", "percentage": (stats['others_size'] or 0) / total_active_bytes * 100 if total_active_bytes > 0 else 0},
        ]

        return {
            "total": total_limit / (1024 * 1024 * 1024),
            "used": round(user.consumed_storage / (1024 * 1024 ),2), 
            "trash_size": format_size(trash_bytes),
            "trash_raw": trash_bytes,
            "categories": categories
        }

    @staticmethod
    def get_large_files(user, category=None):
        """
        Returns discovery files (large files) or category-specific files.
        """
        DISCOVERY_THRESHOLD_BYTES = 50 * 1024 * 1024
        queryset = UserFile.objects.filter(owner=user, is_deleted=False).exclude(description='[SYSTEM_INTERNAL_SHARE]')
        
        if category and category != 'All':
            if category == 'Images':
                queryset = queryset.filter(mime_type__in=FileStorageService.IMAGE_TYPES)
            elif category == 'Documents':
                queryset = queryset.filter(mime_type__in=FileStorageService.DOC_TYPES)
            elif category == 'Media':
                queryset = queryset.filter(mime_type__in=FileStorageService.MEDIA_TYPES)
            elif category == 'Others':
                queryset = queryset.exclude(mime_type__in=FileStorageService.IMAGE_TYPES + FileStorageService.DOC_TYPES + FileStorageService.MEDIA_TYPES)
        else:
            queryset = queryset.filter(file_size_bytes__gt=DISCOVERY_THRESHOLD_BYTES)

        return queryset.order_by('-file_size_bytes')