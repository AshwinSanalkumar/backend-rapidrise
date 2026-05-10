from django.urls import path
from .views import (
    PublicFileView, RegisterView, FileUploadView, FileListView, FolderDeleteView, 
    CreateSharedLinkView, RevokeSharedLinkView, ListSharedLinksView, FolderUpdateView, 
    FolderContentUploadView, FolderContentDeleteView, TrashView, RestoreFileView, 
    RestoreAllFilesView, EmptyTrashView, FavoritesView, SoftDeleteFile, FileDetailView, 
    FileUpdateView, CookieTokenObtainPairView, CookieTokenRefreshView, LogoutView, 
    FolderCreateView, FolderListView, FolderContentView, HardDeleteView, UploadHistoryView, 
    RecentFilesView, UserDetailView, DuplicateFilesView, CleanupDuplicatesView, StorageStatsView, StorageTrendsView, LargeFilesView,
    WorkstationListView, WorkstationDetailView, UserSearchView, 
    WorkstationInviteView, WorkstationInviteRespondView, WorkstationExportView,
    WorkstationVersionsView, WorkstationVersionRestoreView, WorkstationVersionDeleteView,
    ForgotPasswordView, ResetPasswordView, ChangePasswordView,
    CreateFileRequestView, SentRequestsView, ReceivedRequestsView, DeclineRequestView, FulfillRequestView, ImportRequestFileView
)

urlpatterns = [
    # Auth
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('login/', CookieTokenObtainPairView.as_view(), name='login'),
    path('refresh/', CookieTokenRefreshView.as_view(), name='refresh'), 
    path('logout/', LogoutView.as_view(), name='logout'),
    path('user/', UserDetailView.as_view(), name='user-detail'),
    path('user/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/<uidb64>/<token>/", ResetPasswordView.as_view(), name="reset-password"),

    # File Requests
    path('requests/send/', CreateFileRequestView.as_view(), name='create-file-request'),
    path('requests/sent/', SentRequestsView.as_view(), name='sent-requests'),
    path('requests/received/', ReceivedRequestsView.as_view(), name='received-requests'),
    path('requests/<uuid:request_id>/decline/', DeclineRequestView.as_view(), name='decline-request'),
    path('requests/<uuid:request_id>/fulfill/', FulfillRequestView.as_view(), name='fulfill-request'),
    path('requests/<uuid:request_id>/import/', ImportRequestFileView.as_view(), name='import-request-file'),

    # Files
    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('files/view/<str:file_id>/', FileDetailView.as_view(), name='file-detail-view'),
    path('files/favorite/<str:file_id>/', FavoritesView.as_view(), name='add-favorites'),
    path('files/list/', FileListView.as_view(), name='file-list'),
    path('files/recents/', RecentFilesView.as_view(), name='file-recents'),
    path('files/update/<str:file_id>/', FileUpdateView.as_view(), name='file-update'),
    path('files/history/', UploadHistoryView.as_view(), name='file-history'),
    path('files/delete/<str:file_id>/', SoftDeleteFile.as_view(), name='soft-delete'),
    path('files/restore/<str:file_id>/', RestoreFileView.as_view(), name='restore-file'),

    # Folders
    path('assets/list/', FolderListView.as_view(), name='folder-list'),
    path('assets/create/', FolderCreateView.as_view(), name='folder-create'),
    path('assets/update/<uuid:folder_id>/', FolderUpdateView.as_view(), name='folder-update'),
    path('assets/delete/<uuid:folder_id>/', FolderDeleteView.as_view(), name='folder-delete'),
    path('assets/view/<uuid:folder_id>/', FolderContentView.as_view(), name='folder-view'),
    path('assets/view/<uuid:folder_id>/upload/', FolderContentUploadView.as_view(), name='folder-upload'),
    path('assets/view/<uuid:folder_id>/files/<uuid:file_id>/remove/', FolderContentDeleteView.as_view(), name='folder-file-remove'),

    # Trash
    path('trash/', TrashView.as_view(), name='trash'),
    path('trash/delete/<uuid:file_id>/', HardDeleteView.as_view(), name='hard-delete'),
    path('trash/restore-all/', RestoreAllFilesView.as_view(), name='restore-all'),
    path('trash/empty/', EmptyTrashView.as_view(), name='empty-trash'),

    # Sharing
    path('files/<str:file_id>/share/', CreateSharedLinkView.as_view(), name='generate-share-link'),
    path('files/shared-links/', ListSharedLinksView.as_view(), name='list-shared-links'),
    path('files/share/revoke/<str:token>/', RevokeSharedLinkView.as_view(), name='revoke-share-link'),
    path('file/shared/<str:token>/', PublicFileView.as_view(), name='shared-file'),
    
    # Storage
    path('storage/duplicates/', DuplicateFilesView.as_view(), name='duplicate-files'),
    path('storage/cleanup-duplicates/', CleanupDuplicatesView.as_view(), name='cleanup-duplicates'),
    path('storage/stats/', StorageStatsView.as_view(), name='storage-stats'),
    path('storage/trends/', StorageTrendsView.as_view(), name='storage-trends'),
    path('storage/large-files/', LargeFilesView.as_view(), name='large-files'),

    # Workstations
    path('workstations/', WorkstationListView.as_view(), name='workstation-list'),
    path('workstations/<uuid:workstation_id>/', WorkstationDetailView.as_view(), name='workstation-detail'),
    path('workstations/search-users/', UserSearchView.as_view(), name='user-search'),
    path('workstations/invites/', WorkstationInviteView.as_view(), name='workstation-invites'),
    path('workstations/invites/<int:invite_id>/respond/', WorkstationInviteRespondView.as_view(), name='workstation-invite-respond'),
    path('workstations/<uuid:workstation_id>/export/', WorkstationExportView.as_view(), name='workstation-export'),
    path('workstations/<uuid:workstation_id>/versions/', WorkstationVersionsView.as_view(), name='workstation-versions'),
    path('workstations/<uuid:workstation_id>/versions/<uuid:version_id>/restore/', WorkstationVersionRestoreView.as_view(), name='workstation-version-restore'),
    path('workstations/<uuid:workstation_id>/versions/<uuid:version_id>/delete/', WorkstationVersionDeleteView.as_view(), name='workstation-version-delete'),
]
