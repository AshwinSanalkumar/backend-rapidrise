from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import RegistrationSerializer,UserFileSerializer
from .auth_service import AuthenticationService
from .file_service import FileStorageService
from rest_framework.permissions import  IsAuthenticated, AllowAny
from .models import UserFile
from uuid import UUID
from django.shortcuts import get_object_or_404
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.views.decorators.clickjacking import xframe_options_exempt

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
        files = UserFile.objects.filter(owner=request.user)
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


    


        
# views.py — Logout
