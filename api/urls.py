from django.urls import path
from .views import RegisterView, FileUploadView, FileListView,FolderDeleteView,FolderUpdateView ,FolderContentUploadView,FolderContentDeleteView ,TrashView,RestoreFileView,FavoritesView,SoftDeleteFile,FileDetailView,FileUpdateView,CookieTokenObtainPairView,CookieTokenRefreshView, LogoutView, FolderCreateView,FolderListView,FolderContentView,HardDeleteView


urlpatterns = [
    # Using 'register/' as the endpoint
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('login/',CookieTokenObtainPairView.as_view(),name='login'),
    path('refresh/',CookieTokenRefreshView.as_view(),name='login'), 
    path('logout/', LogoutView.as_view(),name="login"),

    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('files/view/<str:file_id>/', FileDetailView.as_view(), name='file-detail-view'),
    path('files/favorite/<str:file_id>/', FavoritesView.as_view(), name='add-favorites'),
    path('files/list/', FileListView.as_view(), name='file-list'),
    path('files/update/<str:file_id>/', FileUpdateView.as_view(), name='product-update'),

    path('files/delete/<str:file_id>/', SoftDeleteFile.as_view(), name='soft-delete'),
    path('files/restore/<str:file_id>/', RestoreFileView.as_view(), name='restore-file'),

    path('assets/list/', FolderListView.as_view(), name='folder-list'),
    path('assets/create/', FolderCreateView.as_view(), name='folder-create'),
    path('assets/update/<uuid:folder_id>/', FolderUpdateView.as_view(), name='folder-update'),
    path('assets/delete/<uuid:folder_id>/', FolderDeleteView.as_view(), name='folder-delete'),
    path('assets/view/<uuid:folder_id>/', FolderContentView.as_view(), name='folder-view'),
    path('assets/view/<uuid:folder_id>/upload/', FolderContentUploadView.as_view(), name='folder-upload'),
    path('assets/view/<uuid:folder_id>/files/<uuid:file_id>/remove/', FolderContentDeleteView.as_view(), name='folder-file-remove'),

    path('trash/', TrashView.as_view(), name='trash'),
    path('trash/delete/<uuid:file_id>/',HardDeleteView.as_view(),name='hard-delete'),
]
