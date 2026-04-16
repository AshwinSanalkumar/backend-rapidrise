# SERVICES FRO FILE UPLOAD DOWNLOAD.
from rest_framework.exceptions import ValidationError
from django.conf import settings
from .models import UserFile


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