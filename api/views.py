from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import (
    RegistrationSerializer, UserFileSerializer, FolderSerializer, 
    SharedLinkSerializer, UserSerializer, WorkstationSerializer,
    WorkstationInviteSerializer, UserSearchSerializer, WorkstationVersionSerializer,
    PasswordValidationSerializer
)
from .auth_service import AuthenticationService
from .file_service import FileStorageService
from .folder_service import FolderService
from .fileShare_service import FileShareService
from rest_framework.permissions import  IsAuthenticated, AllowAny
from django.db import models
from .models import User, UserFile, UserFolder, SharedLink, Workstation, WorkstationInvite, WorkstationMember
from uuid import UUID
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils import timezone
from django.http import FileResponse
from rest_framework.pagination import PageNumberPagination


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
        # Let SimpleJWT do the heavy lifting of validation
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Apply your decoupled service logic
            response = AuthenticationService.token_service(response, request.data)
        return response
    
class CookieTokenRefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny] 
    
    def post(self, request):
        refresh_token = request.COOKIES.get('refresh_token')
        if not refresh_token:
            print("ERROR: No refresh_token cookie found in request")
            return Response({'error': 'No refresh token'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            token = RefreshToken(refresh_token)
            access_token = str(token.access_token)

            response = Response({'message': 'Token refreshed'})
            
            # Set Access Token Cookie
            response.set_cookie(
                key='access_token',
                value=access_token,
                httponly=True,
                secure=False, # Set to True in production (HTTPS)
                samesite='Lax',
                max_age=300,
            )
            return response
        except Exception as e:
            return Response({'error': 'Invalid refresh token'}, status=status.HTTP_401_UNAUTHORIZED)
    
class LogoutView(APIView):
    def post(self, request):
        response = Response({'message': 'Logged out'})
        response.delete_cookie('access_token')
        response.delete_cookie('refresh_token')
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
        folders = FolderService.get_user_folders(request.user)
        if not folders.exists():
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
import zipfile
from io import BytesIO
from django.core.files.base import ContentFile
from django.utils import timezone

class BulkShareView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({"error": "No files provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fid in file_ids:
                try:
                    f = UserFile.objects.get(id=fid, owner=request.user)
                    zf.writestr(f.filename, f.content.read())
                except Exception:
                    continue
        buffer.seek(0)

        zip_name = f"Shared_Batch_{timezone.now().strftime('%Y%m%d%H%M%S')}.zip"
        zip_obj = ContentFile(buffer.read(), name=zip_name)
        zip_obj.content_type = 'application/zip'
        
        new_file = FileStorageService.process_and_store_file(
            user=request.user,
            file_obj=zip_obj,
            display_name=f"Bulk Shared Archive ({len(file_ids)} files)",
            description="[SYSTEM_INTERNAL_SHARE]",
            consume_quota=False
        )
        
        result, error = FileShareService.share_file_via_email(
            file_id=str(new_file.id),
            user=request.user,
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
        file_obj, error = FileShareService.get_file_from_token(token)
        if error:
            error_status = status.HTTP_404_NOT_FOUND
            if "already been used" in error:
                error_status = status.HTTP_410_GONE
            elif "format" in error:
                error_status = status.HTTP_400_BAD_REQUEST   
            return Response({"error": error}, status=error_status)
        
        file_handle = file_obj.content.open('rb')
        response = FileResponse(file_handle, content_type=file_obj.mime_type)
        response['Content-Disposition'] = f'inline; filename="{file_obj.filename}"'
        
        return response

    def head(self, request, token):
        file_obj, error = FileShareService.get_file_from_token(token)
        if error:
            return Response({"error": error}, status=status.HTTP_404_NOT_FOUND)
        
        from django.http import HttpResponse
        response = HttpResponse(content_type=file_obj.mime_type)
        response['Content-Length'] = file_obj.content.size
        response['Content-Disposition'] = f'inline; filename="{file_obj.filename}"'
        return response

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


from .workstation_service import WorkstationService

# ---------------------------------------------------------------------------------------------
# WORKSTATION VIEWS

class WorkstationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        paginator = PageNumberPagination()
        paginator.page_size = 5
        workstations = WorkstationService.get_user_workstations(request.user)
        result_page = paginator.paginate_queryset(workstations, request)
        serializer = WorkstationSerializer(result_page, many=True)
        return paginator.get_paginated_response(serializer.data)

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

from io import BytesIO
from django.http import HttpResponse
from docx import Document

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


# ---------------------------------------------------------------------------------------------
# FILE REQUEST VIEWS

from .serializers import FileRequestSerializer
from .request_service import RequestService

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