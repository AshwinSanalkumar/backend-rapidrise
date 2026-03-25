from django.urls import path
from .views import RegisterView, FileUploadView, FileListView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # Using 'register/' as the endpoint
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('login/',TokenObtainPairView.as_view(),name='login'),
    path('refresh/',TokenRefreshView.as_view(),name='login'), 

    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('files/list/', FileListView.as_view(), name='file-list'),
]