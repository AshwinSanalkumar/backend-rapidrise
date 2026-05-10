from django.shortcuts import get_object_or_404
from .models import FileRequest, User, UserFile
from .file_service import FileStorageService
from uuid import uuid4

class RequestService:
    @staticmethod
    def create_request(user, email, note=''):
        try:
            recipient = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise ValueError("User not found.")

        file_request = FileRequest.objects.create(
            sender=user,
            recipient=recipient,
            note=note,
            status='pending'
        )
        return file_request

    @staticmethod
    def get_sent_requests(user):
        return FileRequest.objects.filter(sender=user)

    @staticmethod
    def get_received_requests(user):
        return FileRequest.objects.filter(recipient=user)

    @staticmethod
    def decline_request(user, request_id):
        file_request = get_object_or_404(FileRequest, id=request_id, recipient=user)
        if file_request.status != 'pending':
            raise ValueError("Only pending requests can be declined.")
        
        file_request.status = 'declined'
        file_request.save()
        return file_request

    @staticmethod
    def fulfill_request(user, request_id, file_obj):
        file_request = get_object_or_404(FileRequest, id=request_id, recipient=user)
        
        if file_request.status != 'pending':
            raise ValueError("Request is already processed.")

        if not file_obj:
            raise ValueError("No file uploaded.")

        # Process and store the file normally for the recipient
        new_file = FileStorageService.process_and_store_file(
            user=user, 
            file_obj=file_obj,
            display_name=file_obj.name,
            description=f"Fulfilled request for {file_request.sender.email}"
        )

        file_request.files.add(new_file)
        file_request.status = 'fulfilled'
        file_request.save()

        return file_request

    @staticmethod
    def import_request_file(user, request_id, file_id):
        file_request = get_object_or_404(FileRequest, id=request_id, sender=user)
        
        try:
            original_file = file_request.files.get(id=file_id)
        except UserFile.DoesNotExist:
            raise ValueError("File not found in this request.")

        # Recreate an instance of UserFile tied to sender
        imported_file = UserFile.objects.create(
            id=uuid4(),
            owner=user,
            display_name=f"Imported - {original_file.display_name or original_file.filename}",
            content=original_file.content,  # Re-use the existing file field reference
            file_size_bytes=original_file.file_size_bytes,
            filename=original_file.filename,
            mime_type=original_file.mime_type,
            checksum=original_file.checksum,
            description=f"Imported from {file_request.recipient.email}'s request"
        )
        return imported_file
