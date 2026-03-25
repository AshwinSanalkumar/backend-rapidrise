from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import RegistrationSerializer,UserFileSerializer
from .auth_service import register_user
from .file_service import FileStorageService
from rest_framework.permissions import  IsAuthenticated
from .models import UserFile
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken

class RegisterView(APIView):
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = register_user(**serializer.validated_data)
            
            return Response(
                {"message": "user registered sucessfully", "user": {
                    "id":user.id,
                    "email":user.email
                    }},
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    """
    api: api/files/upload/
    View used file Upload
    """
    def post(self, request):
        file_obj = request.FILES.get('file')
        display_name=request.data.get('display_name')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            new_file = FileStorageService.process_and_store_file(
                user=request.user, 
                file_obj=file_obj,
                display_name=display_name 
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
    

# views.py
class CookieTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            access_token = response.data['access']
            refresh_token = response.data['refresh']

            # Set httpOnly cookies
            response.set_cookie(
                key='access_token',
                value=access_token,
                httponly=True,
                secure=True,        # HTTPS only — set False in local dev
                samesite='Lax',
                max_age=300,        # 5 min — match SimpleJWT ACCESS_TOKEN_LIFETIME
            )
            response.set_cookie(
                key='refresh_token',
                value=refresh_token,
                httponly=True,
                secure=True,
                samesite='Lax',
                max_age=86400,      # 1 day — match REFRESH_TOKEN_LIFETIME
            )

            # Don't expose tokens in response body
            del response.data['access']
            del response.data['refresh']

        return response
    
# views.py
class CookieTokenRefreshView(APIView):
    def post(self, request):
        refresh_token = request.COOKIES.get('refresh_token')

        if not refresh_token:
            return Response({'error': 'No refresh token'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            token = RefreshToken(refresh_token)
            access_token = str(token.access_token)

            response = Response({'message': 'Token refreshed'})
            response.set_cookie(
                key='access_token',
                value=access_token,
                httponly=True,
                secure=True,
                samesite='Lax',
                max_age=300,
            )
            return response
        except Exception:
            return Response({'error': 'Invalid refresh token'}, status=status.HTTP_401_UNAUTHORIZED)
        
# views.py — Logout
class LogoutView(APIView):
    def post(self, request):
        response = Response({'message': 'Logged out'})
        response.delete_cookie('access_token')
        response.delete_cookie('refresh_token')
        return response