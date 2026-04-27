from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import RegistrationSerializer,UserFileSerializer, FolderSerializer, SharedLinkSerializer
from .auth_service import AuthenticationService
from .file_service import FileStorageService
from .folder_service import FolderService
from .fileShare_service import FileShareService
from rest_framework.permissions import  IsAuthenticated, AllowAny
from .models import UserFile,UserFolder,SharedLink
from uuid import UUID
from django.shortcuts import get_object_or_404
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils import timezone
from django.http import FileResponse
from rest_framework.pagination import PageNumberPagination

class StandardPagination(PageNumberPagination):
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
        """
        try:
            # Ensure the ID is a valid UUID before hitting the database
            file_uuid = UUID(file_id)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid file ID format. Expected a UUID."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Security: owner=request.user prevents users from seeing each other's metadata
        user_file = get_object_or_404(UserFile, pk=file_uuid, owner=request.user)
        
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
        soft_delete_file = FolderService.delete_folder(request.user, folder_id)
        return Response({
            "status": "success",
            "message": "File Restored Sucessfully"
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