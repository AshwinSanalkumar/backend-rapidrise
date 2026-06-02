import logging
from django.db.models import Count, Sum, Q, Value
from django.shortcuts import get_object_or_404
from .models import UserFolder, UserFile
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

logger = logging.getLogger('collections')

class FolderService:
    @staticmethod
    def get_user_folders(user, search_term=None):
        """Fetches folders with file counts and sizes, excluding deleted files."""
        active_files = Q(files__is_deleted=False)
        query = Q(owner=user)
        
        if search_term:
            query &= Q(name__icontains=search_term)

        return UserFolder.objects.filter(query).annotate(
            files_count=Count('files', filter=active_files),
            total_size=Coalesce(Sum('files__file_size_bytes', filter=active_files), 0)
        ).order_by('-created_at')

    @staticmethod
    def create_folder(user, name):
        if UserFolder.objects.filter(owner=user, name__iexact=name).exists():
            raise ValidationError(f"A folder named '{name}' already exists.")
        folder = UserFolder.objects.create(owner=user, name=name)
        logger.info(f"ACTION PERFORMED: Folder created: {name} (ID: {folder.id}) for user {user.email}")
        return folder

    @staticmethod
    def update_folder(user, folder_id, name):
        if UserFolder.objects.filter(owner=user, name__iexact=name).exclude(id=folder_id).exists():
            raise ValidationError(f"A folder named '{name}' already exists.")
        folder = get_object_or_404(UserFolder, id=folder_id, owner=user)
        folder.name = name
        folder.save()
        return folder

    @staticmethod
    def delete_folder(user, folder_id):
        folder = get_object_or_404(UserFolder, id=folder_id, owner=user)
        name = folder.name
        folder.delete()
        logger.info(f"ACTION PERFORMED: Folder deleted: {name} (ID: {folder_id})")
        return True
    
    @staticmethod
    def map_existing_files(user, folder, file_ids):
        files_to_map = UserFile.objects.filter(id__in=file_ids, owner=user)
        for file in files_to_map:
            file.folders.add(folder) # Adds to existing folders instead of replacing
        return files_to_map