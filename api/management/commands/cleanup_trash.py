from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from api.models import UserFile
from api.file_service import FileStorageService
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Hard deletes files in trash that were soft deleted more than 30 days ago'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting trash cleanup process...")
        threshold_date = timezone.now() - timedelta(days=30)
        
        # We find files that are deleted AND their deleted_at is older than 30 days
        queryset = UserFile.objects.filter(
            is_deleted=True,
            deleted_at__lt=threshold_date
        )

        deleted_count = 0
        
        # Using iterator with chunk_size=500 for large datasets as requested
        for file_obj in queryset.iterator(chunk_size=500):
            try:
                # Keep all actual deletion logic in FileStorageService.hard_delete_file()
                FileStorageService.hard_delete_file(file_obj)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Error hard deleting file {file_obj.id}: {str(e)}")
                self.stderr.write(self.style.ERROR(f"Error deleting file {file_obj.id}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully permanently deleted {deleted_count} files from trash."))
