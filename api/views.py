import logging
import threading
import os
import zipfile
from io import BytesIO
from uuid import UUID
from datetime import timedelta
from docx import Document
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import models
from django.shortcuts import get_object_or_404
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils import timezone
from django.http import FileResponse, HttpResponse
from django.conf import settings
from django.template.loader import render_to_string
from .models import User, UserFile, UserFolder, SharedLink, Workstation, WorkstationInvite, WorkstationMember, ChunkedUpload
from .serializers import (
    RegistrationSerializer, UserFileSerializer, FolderSerializer, 
    SharedLinkSerializer, UserSerializer, WorkstationSerializer,
    WorkstationInviteSerializer, UserSearchSerializer, WorkstationVersionSerializer,
    PasswordValidationSerializer, ChunkedUploadSerializer, FileRequestSerializer
)
from .auth_service import AuthenticationService
from .file_service import FileStorageService
from .folder_service import FolderService
from .fileShare_service import FileShareService
from .workstation_service import WorkstationService
from .request_service import RequestService
from .supabase_storage import SupabaseStorageService
from django.core.mail import EmailMessage

logger = logging.getLogger('users')

# api/views.py
from rest_framework.views import APIView
from rest_framework.response import Response

from .email_service import BrevoEmailService


class TestMailView(APIView):
    permission_classes = []

    def get(self, request):

        result = BrevoEmailService.send_email(
            subject="Brevo API Test",
            html_content="<h1>Hello from NexusShare</h1>",
            recipients=["ashwindev25@gmail.com"]
        )

        return Response(result)
    
class StandardPagination(PageNumberPagination):
    page_size = 8
    page_size_query_param = 'page_size'
    max_page_size = 100

#AUTH VIEWS
class RegisterView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny] 
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = AuthenticationService.register_user(**serializer.validated_data)
            
            return Response(
                {"message": "user registered sucessfully", "user": {
                    "id":user.id,
                    "email":user.email
                    }},
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
class CookieTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')
        if email and password:
            user = User.objects.filter(email__iexact=email).first()
            if user and not user.is_active and user.check_password(password):
                return Response({
                    "code": "requires_reactivation",
                    "email": user.email,
                    "message": "Your account has been disabled. To reactivate, verify your email with an OTP."
                }, status=status.HTTP_403_FORBIDDEN)

        # Let SimpleJWT do the heavy lifting of validation
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Apply your decoupled service logic
            response = AuthenticationService.token_service(response, request.data)
            logger.info(f"ACTION PERFORMED: User logged in: {email}")
        return response
    
class SendReactivationOTPView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        success, message = AuthenticationService.send_reactivation_otp(email)
        if not success:
            return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": message}, status=status.HTTP_200_OK)

class VerifyReactivationOTPView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp')
        if not email or not otp:
            return Response({"error": "Email and OTP are required."}, status=status.HTTP_400_BAD_REQUEST)
        
        success, message = AuthenticationService.verify_reactivation_otp(email, otp)
        if not success:
            return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": message}, status=status.HTTP_200_OK)
        
class CookieTokenRefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get('refresh_token')

        if not refresh_token:
            return Response(
                {'error': 'No refresh token'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            old_refresh = RefreshToken(refresh_token)

            # Get user from token
            user_id = old_refresh.payload.get('user_id')

            user = User.objects.get(id=user_id)

            # Blacklist old refresh token
            if settings.SIMPLE_JWT.get('BLACKLIST_AFTER_ROTATION', False):
                try:
                    old_refresh.blacklist()
                except AttributeError:
                    pass

            # Create fresh tokens
            new_refresh = RefreshToken.for_user(user)
            new_access = new_refresh.access_token

            response = Response({
                'message': 'Token refreshed'
            })

            response.set_cookie(
                key='access_token',
                value=str(new_access),
                httponly=True,
                secure=True,
                samesite='None',
                max_age=int(
                    settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()
                ),
            )

            response.set_cookie(
                key='refresh_token',
                value=str(new_refresh),
                httponly=True,
                secure=True,
                samesite='None',
                max_age=int(
                    settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()
                ),
            )

            return response

        except Exception:
            return Response(
                {'error': 'Invalid refresh token'},
                status=status.HTTP_401_UNAUTHORIZED
            )
    
class LogoutView(APIView):
    def post(self, request):
        refresh_token = request.COOKIES.get('refresh_token')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                # Token might already be blacklisted or invalid
                pass
                
        response = Response({'message': 'Logged out'})
        response.delete_cookie(
            key="access_token",
            path="/",
            samesite="None",
        )

        response.delete_cookie(
            key="refresh_token",
            path="/",
            samesite="None",
        )
        
        user_email = "Unknown"
        if request.user and request.user.is_authenticated:
            user_email = request.user.email
            
        logger.info(f"ACTION PERFORMED: User logged out: {user_email}")
        return response

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
        
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get('currentPass')
        new_password = request.data.get('newPass')

        serializer = PasswordValidationSerializer(data={'password': new_password})
        serializer.is_valid(raise_exception=True)

        try:
            AuthenticationService.change_password(request.user, current_password, new_password)
            return Response({"message": "Password updated successfully."}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ForgotPasswordView(APIView):

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):

        email = request.data.get("email")

        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        AuthenticationService.send_reset_email(email)

        return Response(
            {
                "message":
                "If an account exists, a reset link has been sent."
            },
            status=status.HTTP_200_OK
        )


class ResetPasswordView(APIView):

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, uidb64, token):

        password = request.data.get("password")

        serializer = PasswordValidationSerializer(data={'password': password})
        serializer.is_valid(raise_exception=True)

        success, message = (
            AuthenticationService.reset_password(
                uidb64,
                token,
                password
            )
        )

        if not success:
            return Response(
                {"error": message},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"message": message},
            status=status.HTTP_200_OK
        )

class DeactivateAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        password = request.data.get('password')

        if not password:
            return Response(
                {"error": "Password is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user

        if not user.check_password(password):
            return Response(
                {"error": "Incorrect password."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_active = False
        user.disabled_at = timezone.now()
        user.save()

        deletion_date = (
            user.disabled_at + timedelta(days=30)
        ).strftime('%B %d, %Y')

        context = {
            "first_name": user.first_name,
            "deletion_date": deletion_date,
            "frontend_url": settings.FRONTEND_URL
        }

        def send_async():
            try:
                html_body = render_to_string(
                    "emails/deactivate_success.html",
                    context
                )

                BrevoEmailService.send_email(
                    subject="NexusShare — Account Deactivated",
                    html_content=html_body,
                    recipients=[user.email]
                )

            except Exception as e:
                logger.error(
                    f"Failed to send deactivation email to {user.email}: {str(e)}"
                )

        threading.Thread(
            target=send_async,
            daemon=True
        ).start()

        response = Response(
            {"message": "Account deactivated successfully."},
            status=status.HTTP_200_OK
        )

        response.delete_cookie(
            key="access_token",
            path="/",
            samesite="None",
        )

        response.delete_cookie(
            key="refresh_token",
            path="/",
            samesite="None",
)

        return response

#---------------------------------------------------------------------------------------------
#FILE MANAGEMENT VIEWS
        
class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    """
    api: api/files/upload/
    View used file Upload
    """
    def post(self, request):
        file_obj = request.FILES.get('file')
        display_name=request.data.get('display_name')
        description=request.data.get('description')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            new_file = FileStorageService.process_and_store_file(
                user=request.user, 
                file_obj=file_obj,
                display_name=display_name,
                description=description
            ) 
            serializer = UserFileSerializer(new_file)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            # Extract just the message string from the ValidationError detail
            msg = e.detail[0] if isinstance(e.detail, list) else e.detail
            return Response({"error": str(msg)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
class FileListView(APIView):
    permission_classes = [IsAuthenticated]
    """
    api: api/files/list/
    View used to list files
    """
    def get(self, request):
        search_term = request.query_params.get('search')
        favorites_only = request.query_params.get('favorites') == 'true'
        files = FileStorageService.get_user_files(request.user, search_term, favorites_only)
        
        paginator = StandardPagination()
        page = paginator.paginate_queryset(files, request)
        if page is not None:
            serializer = UserFileSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = UserFileSerializer(files, many=True)
        return Response(serializer.data)
    

class FileDetailView(APIView):
    permission_classes = [IsAuthenticated]
    @xframe_options_exempt
    def get(self, request, file_id):
        """
        GET api/files/<file_id>/
        Returns metadata for a specific file owned by the user.
        Also stamps last_accessed_at so the Recents feed stays accurate.
        """
        try:
            file_uuid = UUID(file_id)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid file ID format. Expected a UUID."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_file = get_object_or_404(UserFile, pk=file_uuid, owner=request.user)

        # Stamp access time (only update that one column for efficiency)
        UserFile.objects.filter(pk=file_uuid).update(last_accessed_at=timezone.now())
        user_file.refresh_from_db()

        serializer = UserFileSerializer(user_file)
        return Response(serializer.data, status=status.HTTP_200_OK)

class FileUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    """
    api: api/products/update/<product id>
    View used to update a Particular product
    """
    def put(self, request, file_id):
        try:
            file_uuid = UUID(file_id)
        except ValueError:
            return Response(
                {"error": "Invalid file ID format."},
                status=status.HTTP_400_BAD_REQUEST
            )
        file = get_object_or_404(UserFile, pk=file_uuid, owner=request.user)
        serializer = UserFileSerializer(UserFile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_file = FileStorageService.update_file(
            file=file,
            data=serializer.validated_data,
        )
        return Response(UserFileSerializer(updated_file).data)

class FavoritesView(APIView):    
    def patch(self,request, file_id):
        try:
            file_uuid = UUID(file_id)
        except ValueError:
            return Response(
                {"error": "Invalid file ID format."},
                status=status.HTTP_400_BAD_REQUEST
            )
        file_obj = get_object_or_404(UserFile, id=file_uuid, owner=request.user)
        updated_file = FileStorageService.toggle_file_favorite(request.user, file_obj)
        return Response({
            "status": "success",
            "is_favorite": updated_file.is_favorite,
            "message": "File marked as favorite" if updated_file.is_favorite else "File removed from favorites"
        }, status=status.HTTP_200_OK)
    

class RecentFilesView(APIView):
    permission_classes = [IsAuthenticated]
    """
    api: api/files/recents/
    Returns the user's files that have been accessed at least once,
    ordered by last_accessed_at descending (most recently opened first).
    Falls back to uploaded_at for files never explicitly accessed.
    """
    def get(self, request):
        files = UserFile.objects.filter(
            owner=request.user,
            is_deleted=False,
            last_accessed_at__isnull=False   # only files that have been opened
        ).order_by('-last_accessed_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(files, request)
        if page is not None:
            serializer = UserFileSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = UserFileSerializer(files, many=True)
        return Response(serializer.data)

class ClearRecentFilesView(APIView):
    permission_classes = [IsAuthenticated]
    """
    api: api/files/recents/clear/
    Clears the recent history by nullifying last_accessed_at for all user files.
    """
    def delete(self, request):
        UserFile.objects.filter(owner=request.user).update(last_accessed_at=None)
        return Response({"status": "success", "message": "Activity history cleared."})

class UploadHistoryView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            year = int(request.query_params.get('year',timezone.now().year))
            month = int(request.query_params.get('month', timezone.now().month))
            
            # Returns history + stats in one efficient call
            response_data = FileStorageService.get_upload_history(request.user, year, month)
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    

class SoftDeleteFile(APIView):    
    def delete(self,request, file_id):
        try:
            file_uuid = UUID(file_id)
        except ValueError:
            return Response(
                {"error": "Invalid file ID format."},
                status=status.HTTP_400_BAD_REQUEST
            )
        file_obj = get_object_or_404(UserFile, id=file_uuid, owner=request.user)
        soft_delete_file = FileStorageService.soft_delete_file(request.user, file_obj)
        return Response({
            "status": "success",
            "is_deleted": soft_delete_file.is_deleted,
            "message": "File moved to trash"
        }, status=status.HTTP_200_OK)
    
class RestoreFileView(APIView):    
    def post(self,request, file_id):
        try:
            file_uuid = UUID(file_id)
        except ValueError:
            return Response(
                {"error": "Invalid file ID format."},
                status=status.HTTP_400_BAD_REQUEST
            )
        file_obj = get_object_or_404(UserFile, id=file_uuid, owner=request.user)
        soft_delete_file = FileStorageService.restore_file(request.user, file_obj)
        return Response({
            "status": "success",
            "is_deleted": soft_delete_file.is_deleted,
            "message": "File Restored Sucessfully"
        }, status=status.HTTP_200_OK)
    
class TrashView(APIView):
    def get(self,request):
        files = UserFile.objects.filter(owner=request.user, is_deleted=True).order_by('-deleted_at')
        
        paginator = StandardPagination()
        page = paginator.paginate_queryset(files, request)
        if page is not None:
            serializer = UserFileSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = UserFileSerializer(files, many=True)
        return Response(serializer.data)

class HardDeleteView(APIView):
    def delete(self,request,file_id):
        file_obj = get_object_or_404(UserFile, id=file_id, owner=request.user,is_deleted=True)
        FileStorageService.hard_delete_file(file_obj)
        return Response({
            "status": "success",
            "message": "File permanently deleted" 
        }, status=status.HTTP_200_OK)
    

class RestoreAllFilesView(APIView):
    def post(self, request):
        count = FileStorageService.restore_all_files(request.user)
        return Response({
            "status": "success",
            "message": f"{count} files restored"
        }, status=status.HTTP_200_OK)

class EmptyTrashView(APIView):
    def delete(self, request):
        count = FileStorageService.empty_trash(request.user)
        return Response({
            "status": "success",
            "message": f"Trash emptied: {count} items removed"
        }, status=status.HTTP_200_OK)

    
#---------------------------------------------------------------------------------------------    
#FOlDER MANAGEMENT

class FolderListView(APIView):
    """GET /assets/list/ and POST /assets/create/"""
    def get(self, request):
        search_term = request.query_params.get('search')
        folders = FolderService.get_user_folders(request.user, search_term)
        if not folders.exists() and not search_term:
            return Response({
                "message": "You haven't created any folders yet.",
                "folders": []
            }, status=status.HTTP_200_OK)
            
        paginator = StandardPagination()
        page = paginator.paginate_queryset(folders, request)
        if page is not None:
            serializer = FolderSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = FolderSerializer(folders, many=True)
        return Response(serializer.data)
    
class FolderCreateView(APIView):
    def post(self, request):
        name = request.data.get('name')
        if not name:
            return Response({"error": "Folder name is required"}, status=status.HTTP_400_BAD_REQUEST)
        folder = FolderService.create_folder(request.user, name)
        return Response(FolderSerializer(folder).data, status=status.HTTP_201_CREATED)

class FolderUpdateView(APIView):
    """PUT /assets/update/<id>/ and DELETE /assets/delete/<id>/"""
    def put(self, request, folder_id):
        name = request.data.get('name')
        folder = FolderService.update_folder(request.user, folder_id, name)
        return Response(FolderSerializer(folder).data)

class FolderDeleteView(APIView):
    def delete(self,request,folder_id):
        FolderService.delete_folder(request.user, folder_id)
        return Response({
            "status": "success",
            "message": "Folder deleted successfully"
        }, status=status.HTTP_200_OK)

         
class FolderContentView(APIView):
    """GET /assets/view/<id>/ and POST /assets/view/<id>/upload/"""
    def get(self, request, folder_id):
        folder = get_object_or_404(UserFolder, id=folder_id, owner=request.user)
        files = UserFile.objects.filter(folders=folder, is_deleted=False) # These are the files currently 'mapped' to this folder
        
        paginator = StandardPagination()
        page = paginator.paginate_queryset(files, request)
        if page is not None:
            serializer = UserFileSerializer(page, many=True)
            return paginator.get_paginated_response({
                "id": folder.id,
                "name": folder.name,
                "files": serializer.data
            })
            
        return Response({
            "id": folder.id,
            "name": folder.name,
            "files": UserFileSerializer(files, many=True).data
        })

class FolderContentUploadView(APIView):
    def post(self, request, folder_id):
            folder = get_object_or_404(UserFolder, id=folder_id, owner=request.user)
            file_ids = request.data.get('file_ids', [])
            if not file_ids:
                return Response({"error": "No file IDs provided."}, status=status.HTTP_400_BAD_REQUEST)
            updated_files = FolderService.map_existing_files(request.user, folder, file_ids)
            serializer = UserFileSerializer(updated_files, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

class FolderContentDeleteView(APIView):
    def delete(self, request, folder_id, file_id):
            folder = get_object_or_404(UserFolder, id=folder_id, owner=request.user)
            file_to_remove = get_object_or_404(UserFile, id=file_id, owner=request.user)
            folder.files.remove(file_to_remove)
            return Response(status=status.HTTP_204_NO_CONTENT)    
    
#---------------------------------------------------------------------------------------------        
#FILE SHARE VIEWS

class BulkShareView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        result, error = FileShareService.bulk_share_files(
            user=request.user,
            file_ids=request.data.get('file_ids', []),
            request=request,
            data=request.data
        )

        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(result, status=status.HTTP_201_CREATED)

class CreateSharedLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, file_id):
        result, error = FileShareService.share_file_via_email(
            file_id=file_id,
            user=request.user,
            request=request,
            data=request.data
        )

        if error:
            return Response({"error": error}, status=status.HTTP_404_NOT_FOUND)

        return Response(result, status=status.HTTP_201_CREATED)

class ListSharedLinksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search_term = request.query_params.get('search')
        status_filter = request.query_params.get('status')
        file_id = request.query_params.get('file_id')
        shares = FileShareService.list_user_shares(request.user, search_term, status_filter, file_id)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(shares, request)
        if page is not None:
            serializer = SharedLinkSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = SharedLinkSerializer(shares, many=True)
        return Response(serializer.data)

class RevokeSharedLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        success, message = FileShareService.revoke_shared_link(token, request.user)
        if not success:
            return Response({"error": message}, status=status.HTTP_404_NOT_FOUND)
        return Response({"message": message}, status=status.HTTP_200_OK)

    
class PublicFileView(APIView):
    permission_classes = [AllowAny]
    """
    api: api/file/view/<token>/
    View used to access and view the file using a secure link.
    """
    def get(self, request, token):
        is_metadata = request.query_params.get('metadata') == 'true'
        is_download = request.query_params.get('download') == 'true'
        
        increment_type = 'download' if is_download else 'access'
        
        file_obj, shared_link, error = FileShareService.get_file_from_token(token, increment_type=increment_type)
        if error:
            # Return semantically correct HTTP codes so frontend can show the right screen
            if 'expired' in error.lower():
                return Response({"error": error}, status=status.HTTP_410_GONE)
            elif 'revoked' in error.lower():
                return Response({"error": error}, status=status.HTTP_403_FORBIDDEN)
            elif any(msg in error for msg in ["already been used", "limit reached", "disabled", "preview only"]):
                return Response({"error": error}, status=status.HTTP_403_FORBIDDEN)
            elif "format" in error:
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"error": error}, status=status.HTTP_404_NOT_FOUND)
        
        if is_metadata:
            headers = FileShareService.get_public_tracking_headers(shared_link)
            # Use Supabase to get a signed URL for preview
            preview_url = SupabaseStorageService.create_signed_url(file_obj.content.name)
            
            return Response({
                'name': file_obj.filename,
                'size': file_obj.file_size_bytes, # Use dedicated size field
                'type': file_obj.mime_type,
                'preview': preview_url
            }, headers=headers)

        if is_download:
            from django.http import FileResponse
            # Serving the file directly from Supabase
            # Since content stores the supabase path
            file_data = SupabaseStorageService.download_file(file_obj.content.name)
            response = FileResponse(BytesIO(file_data), content_type=file_obj.mime_type)
            response['Content-Disposition'] = f'attachment; filename="{file_obj.filename}"'
            
            # Add tracking headers so frontend can update the UI
            tracking_headers = FileShareService.get_public_tracking_headers(shared_link)
            for key, value in tracking_headers.items():
                response[key] = value
            return response

        from django.shortcuts import redirect
        # For preview redirect, also use Supabase signed URL
        return redirect(SupabaseStorageService.create_signed_url(file_obj.content.name))


class DuplicateFilesView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List all duplicate groups for the current user."""
        duplicates = FileStorageService.get_duplicate_groups(request.user)
        return Response(duplicates, status=status.HTTP_200_OK)

    def delete(self, request):
        """
        Resolve duplicates by deleting specific file IDs.
        Expected format: {'file_ids': [uuid, uuid, ...]}
        """
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({"error": "No file IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        deleted_count = 0
        for fid in file_ids:
            try:
                # Use existing service method for hard deletion (decrements quota)
                file_obj = get_object_or_404(UserFile, id=fid, owner=request.user)
                FileStorageService.hard_delete_file(file_obj)
                deleted_count += 1
            except Exception:
                continue
        return Response({
            "status": "success",
            "message": f"Successfully removed {deleted_count} duplicates",
            "deleted_count": deleted_count
        }, status=status.HTTP_200_OK)

class StorageStatsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Returns storage distribution statistics."""
        stats = FileStorageService.get_storage_stats(request.user)
        return Response(stats, status=status.HTTP_200_OK)

class LargeFilesView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Returns a list of large files, optionally filtered by category."""
        category = request.query_params.get('category')
        files = FileStorageService.get_large_files(request.user, category=category)
        
        paginator = StandardPagination()
        paginator.page_size = 5
        page = paginator.paginate_queryset(files, request)
        if page is not None:
             serializer = UserFileSerializer(page, many=True)
             return paginator.get_paginated_response(serializer.data)

        # We can reuse UserFileSerializer here
        serializer = UserFileSerializer(files, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class StorageTrendsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Returns historical storage usage snapshots and activity trends."""
        trends = FileStorageService.get_storage_snapshots(request.user)
        activity = FileStorageService.get_activity_snapshots(request.user)
        return Response({
            "monthly": trends,
            "daily": activity['daily'],
            "weekly": activity['weekly']
        }, status=status.HTTP_200_OK)

class CleanupDuplicatesView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Batch cleanup all duplicates, keeping only originals."""
        count = FileStorageService.cleanup_duplicates(request.user)
        return Response({
            "message": f"Successfully removed {count} duplicate instances.",
            "deleted_count": count
        }, status=status.HTTP_200_OK)



# ---------------------------------------------------------------------------------------------
# WORKSTATION VIEWS

class WorkstationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        paginator = StandardPagination()
        workstations = WorkstationService.get_user_workstations(request.user)
        result_page = paginator.paginate_queryset(workstations, request)
        serializer = WorkstationSerializer(result_page, many=True)
        
        response = paginator.get_paginated_response(serializer.data)
        # Add a custom field to track the total workstations owned by this user
        response.data['owned_count'] = Workstation.objects.filter(owner=request.user).count()
        return response

    def post(self, request):
        workstation = WorkstationService.create_workstation(request.user, request.data)
        return Response(WorkstationSerializer(workstation).data, status=status.HTTP_201_CREATED)

class WorkstationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workstation_id):
        workstation = WorkstationService.get_workstation_detail(request.user, workstation_id)
        serializer = WorkstationSerializer(workstation)
        return Response(serializer.data)

    def put(self, request, workstation_id):
        workstation = WorkstationService.update_workstation(request.user, workstation_id, request.data)
        return Response(WorkstationSerializer(workstation).data)

    def delete(self, request, workstation_id):
        WorkstationService.delete_workstation(request.user, workstation_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

class UserSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get('q', '')
        users = WorkstationService.search_users(request.user, query)
        serializer = UserSearchSerializer(users, many=True)
        return Response(serializer.data)

class WorkstationInviteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        invites = WorkstationService.get_pending_invites(request.user)
        serializer = WorkstationInviteSerializer(invites, many=True)
        return Response(serializer.data)

    def post(self, request):
        try:
            invite = WorkstationService.send_invite(
                request.user, 
                request.data.get('workstation'),
                request.data.get('invitee'),
                request.data.get('role', 'EDITOR')
            )
            return Response(WorkstationInviteSerializer(invite).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WorkstationInviteRespondView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, invite_id):
        try:
            result = WorkstationService.respond_to_invite(
                request.user, 
                invite_id, 
                request.data.get('action')
            )
            return Response(result)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ChunkedUploadInitView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        filename = request.data.get('filename')
        total_size = request.data.get('total_size')
        if not filename or not total_size:
            return Response({"error": "filename and total_size are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            chunked_upload = FileStorageService.init_chunked_upload(request.user, filename, int(total_size))
            return Response(ChunkedUploadSerializer(chunked_upload).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ChunkedUploadChunkView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        upload_id = request.data.get('upload_id')
        offset = request.data.get('offset')
        chunk_file = request.FILES.get('chunk')
        
        if not all([upload_id, offset, chunk_file]):
            return Response({"error": "upload_id, offset, and chunk are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        chunked_upload = get_object_or_404(ChunkedUpload, upload_id=upload_id, user=request.user)
        
        try:
            FileStorageService.save_chunk(chunked_upload, chunk_file, int(offset))
            return Response(ChunkedUploadSerializer(chunked_upload).data)
        except ValidationError as e:
            return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ChunkedUploadCompleteView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        upload_id = request.data.get('upload_id')
        display_name = request.data.get('display_name')
        description = request.data.get('description')
        
        if not upload_id:
            return Response({"error": "upload_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        chunked_upload = get_object_or_404(ChunkedUpload, upload_id=upload_id, user=request.user)
        
        try:
            user_file = FileStorageService.finalize_chunked_upload(chunked_upload, display_name, description)
            return Response(UserFileSerializer(user_file).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ChunkedUploadStatusView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, upload_id):
        chunked_upload = get_object_or_404(ChunkedUpload, upload_id=upload_id, user=request.user)
        return Response(ChunkedUploadSerializer(chunked_upload).data)

    def delete(self, request, upload_id):
        chunked_upload = get_object_or_404(ChunkedUpload, upload_id=upload_id, user=request.user)
        if os.path.exists(chunked_upload.file_path):
            os.remove(chunked_upload.file_path)
        chunked_upload.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ChunkedUploadListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        active_uploads = ChunkedUpload.objects.filter(user=request.user, status='uploading')
        return Response(ChunkedUploadSerializer(active_uploads, many=True).data)

class WorkstationVersionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workstation_id):
        try:
            versions = WorkstationService.get_versions(request.user, workstation_id)
            serializer = WorkstationVersionSerializer(versions, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WorkstationVersionRestoreView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, workstation_id, version_id):
        try:
            workstation = WorkstationService.restore_version(request.user, workstation_id, version_id)
            serializer = WorkstationSerializer(workstation)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WorkstationVersionDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, workstation_id, version_id):
        try:
            workstation, rolled_back = WorkstationService.delete_version(request.user, workstation_id, version_id)
            return Response({
                "rolled_back": rolled_back,
                "workstation": WorkstationSerializer(workstation).data
            }, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WorkstationMemberView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, workstation_id, member_id):
        """Update a member's role. Owner only."""
        new_role = request.data.get('role')
        if not new_role:
            return Response({"error": "role is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            member = WorkstationService.update_member_role(request.user, workstation_id, member_id, new_role)
            return Response({
                "id": member.id,
                "role": member.role,
                "message": "Role updated successfully"
            }, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, workstation_id, member_id):
        """Remove a collaborator. Owner only."""
        try:
            WorkstationService.remove_member(request.user, workstation_id, member_id)
            return Response({"message": "Member removed"}, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

# ---------------------------------------------------------------------------------------------
# EXPORT VIEWS

class WorkstationExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workstation_id):
        format_type = request.query_params.get('format', 'pdf').lower()
        workstation = get_object_or_404(Workstation, id=workstation_id)
        
        # Check permissions
        if not WorkstationMember.objects.filter(workstation=workstation, user=request.user).exists():
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        if format_type == 'docx':
            return self.export_docx(workstation)
        else:
            return Response({"error": "PDF export is handled on the frontend"}, status=status.HTTP_400_BAD_REQUEST)

    def export_docx(self, workstation):
        document = Document()
        document.add_heading(workstation.title, 0)
        
        if workstation.description:
            document.add_paragraph(workstation.description)

        # Add content - basic text area content
        document.add_paragraph(workstation.content)

        buffer = BytesIO()
        document.save(buffer)
        buffer.seek(0)

        response = HttpResponse(buffer.read(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'attachment; filename="{workstation.title}.docx"'
        return response


# FILE REQUEST VIEWS

class CreateFileRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        email = request.data.get('email')
        note = request.data.get('note', '')

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            file_request = RequestService.create_request(request.user, email, note)
            serializer = FileRequestSerializer(file_request)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            error_status = status.HTTP_404_NOT_FOUND if "not found" in str(e) else status.HTTP_400_BAD_REQUEST
            return Response({"error": str(e)}, status=error_status)


class SentRequestsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        requests_list = RequestService.get_sent_requests(request.user)
        serializer = FileRequestSerializer(requests_list, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ReceivedRequestsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        requests_list = RequestService.get_received_requests(request.user)
        serializer = FileRequestSerializer(requests_list, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DeclineRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, request_id):
        try:
            RequestService.decline_request(request.user, request_id)
            return Response({"message": "Request declined."}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class DeleteRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, request_id):
        try:
            RequestService.delete_request(request.user, request_id)
            return Response({"message": "Request deleted."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FulfillRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, request_id):
        file_objs = request.FILES.getlist('files')
        
        try:
            file_request = RequestService.fulfill_request(request.user, request_id, file_objs)
            serializer = FileRequestSerializer(file_request)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ImportRequestFileView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, request_id):
        file_id = request.data.get('file_id')
        if not file_id:
            return Response({"error": "file_id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            imported_file = RequestService.import_request_file(request.user, request_id, file_id)
            serializer = UserFileSerializer(imported_file)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            error_status = status.HTTP_404_NOT_FOUND if "not found" in str(e) else status.HTTP_400_BAD_REQUEST
            return Response({"error": str(e)}, status=error_status)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)