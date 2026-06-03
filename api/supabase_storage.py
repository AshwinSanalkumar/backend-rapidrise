from supabase import create_client
from django.conf import settings

supabase = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY
)


class SupabaseStorageService:

    @staticmethod
    def upload_file(file_obj, file_name):
        response = (
            supabase.storage
            .from_(settings.SUPABASE_BUCKET)
            .upload(
                path=file_name,
                file=file_obj.read(),
                file_options={
                    "content-type": file_obj.content_type
                }
            )
        )

        return response

    @staticmethod
    def get_public_url(file_name):
        return supabase.storage.from_(settings.SUPABASE_BUCKET).get_public_url(file_name)

    @staticmethod
    def download_file(file_name):
        return supabase.storage.from_(settings.SUPABASE_BUCKET).download(file_name)

    @staticmethod
    def create_signed_url(file_name, expires_in=3600):
        # Using the bucket from settings
        response = supabase.storage.from_(settings.SUPABASE_BUCKET).create_signed_url(
            path=file_name,
            expires_in=expires_in
        )
        # Handle response format (it usually contains 'signedURL' or 'signed_url' depending on client version)
        # In current python-supabase it's usually a string or a dict with 'signedURL'
        return response.get('signedURL') if isinstance(response, dict) else response