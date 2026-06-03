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