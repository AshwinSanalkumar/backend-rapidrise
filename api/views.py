from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import RegistrationSerializer,UserFileSerializer
from .auth_service import register_user
from .file_service import FileStorageService
from rest_framework.permissions import  IsAuthenticated
from .models import UserFile

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