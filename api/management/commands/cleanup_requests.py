from django.core.management.base import BaseCommand
from django.utils import timezone
from api.models import FileRequest
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Permanently deletes expired file requests'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting expired file request cleanup...")
        
        now = timezone.now()
        
        expired_requests = FileRequest.objects.filter(
            expires_at__lte=now
        )

        total_count = expired_requests.count()
        self.stdout.write(f"Found {total_count} expired requests.")

        if total_count > 0:
            try:
                expired_requests.delete()
                self.stdout.write(self.style.SUCCESS(f"Successfully deleted {total_count} expired requests."))
            except Exception as e:
                logger.error(f"Error deleting expired requests: {str(e)}")
                self.stderr.write(self.style.ERROR(f"Error during cleanup: {str(e)}"))
        else:
            self.stdout.write("No expired requests to cleanup.")

        self.stdout.write(self.style.SUCCESS("Request cleanup process finished."))
