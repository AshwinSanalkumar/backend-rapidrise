from django.urls import path
from .views import RegisterView, FileUploadView, FileListView ,FileDetailView,FileUpdateView,CookieTokenObtainPairView,CookieTokenRefreshView, LogoutView


urlpatterns = [
    # Using 'register/' as the endpoint
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('login/',CookieTokenObtainPairView.as_view(),name='login'),
    path('refresh/',CookieTokenRefreshView.as_view(),name='login'), 
    path('logout/', LogoutView.as_view(),name="login"),

    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('files/view/<str:file_id>/', FileDetailView.as_view(), name='file-detail-view'),
    path('files/list/', FileListView.as_view(), name='file-list'),
    path('files/update/<str:file_id>/', FileUpdateView.as_view(), name='product-update'),
]