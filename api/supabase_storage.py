import logging
from supabase import create_client
from django.conf import settings

supabase = None
if hasattr(settings, 'SUPABASE_URL') and hasattr(settings, 'SUPABASE_KEY') and settings.SUPABASE_URL and settings.SUPABASE_KEY:
    supabase = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_KEY
    )

logger = logging.getLogger('files')


class SupabaseStorageService:

    @staticmethod
    def upload_file(file_obj, file_name, mime_type=None):
        if not supabase:
            logger.error("Supabase client not initialized")
            return None

        # Fallback for content_type
        if not mime_type:
            import mimetypes
            mime_type = getattr(file_obj, 'content_type', None)
            if not mime_type:
                mime_type, _ = mimetypes.guess_type(file_name)
            if not mime_type:
                mime_type = 'application/octet-stream'

        response = (
            supabase.storage
            .from_(settings.SUPABASE_BUCKET)
            .upload(
                path=file_name,
                file=file_obj.read(),
                file_options={
                    "content-type": mime_type
                }
            )
        )
        return response

    @staticmethod
    def get_public_url(file_name):
        if not supabase:
            return None
        return supabase.storage.from_(settings.SUPABASE_BUCKET).get_public_url(file_name)

    @staticmethod
    def download_file(file_name):
        if not supabase:
            logger.error("Supabase client not initialized")
            return None
        return supabase.storage.from_(settings.SUPABASE_BUCKET).download(file_name)

    @staticmethod
    def create_signed_url(file_name, expires_in=3600):
        if not supabase:
            return None
        try:
            # Using the bucket from settings
            response = supabase.storage.from_(settings.SUPABASE_BUCKET).create_signed_url(
                path=file_name,
                expires_in=expires_in
            )
            # Handle response format (it usually contains 'signedURL' or 'signed_url')
            if isinstance(response, dict):
                if 'error' in response:
                    logger.error(f"Supabase signed URL error for {file_name}: {response['error']}")
                    return None
                return response.get('signedURL') or response.get('signed_url')
            return response
        except Exception as e:
            logger.error(f"Exception generating Supabase signed URL for {file_name}: {str(e)}")
            return None