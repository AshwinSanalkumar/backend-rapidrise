from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.conf import settings
import uuid
from django.utils import timezone

class UserManager(BaseUserManager):
    def create_user(self,email,password=None,**extra_fields):
        if not email:
            raise ValueError("The email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email,**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_admin", True)
        extra_fields.setdefault("is_active", True)
        return self.create_user(email, password, **extra_fields)
    
class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    dob = models.DateField()
    objects = UserManager()
    storage_limit_bytes = models.BigIntegerField(default=1024*1024*1024) 
    consumed_storage = models.BigIntegerField(default=0)
    disabled_at = models.DateTimeField(null=True, blank=True)
    activation_otp = models.CharField(max_length=6, null=True, blank=True)
    activation_otp_created_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD='email'
    REQUIRED_FIELDS = ["first_name", "last_name"]

def file_storage_path(instance, filename):
    return f'user_{instance.owner.id}/files/{filename}'

class UserFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    folders = models.ManyToManyField('UserFolder', related_name='files', blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name=models.CharField(max_length=255,null=True)
    is_favorite=models.BooleanField(default=False)
    content = models.FileField(upload_to=file_storage_path)
    file_size_bytes = models.BigIntegerField()
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, editable=False)
    checksum = models.CharField(max_length=64, null=True, blank=True, db_index=True, help_text="SHA-256 hex digest of the file content")
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    description=models.CharField(max_length=250, null=True)
    is_deleted=models.BooleanField(default=False)
    deleted_at=models.DateTimeField(null=True, blank=True)
    last_accessed_at=models.DateTimeField(null=True, blank=True, db_index=True, help_text="Timestamp of the last time the owner opened/viewed this file")
    
    class Meta:
        db_table = "Files"
        indexes = [
            models.Index(fields=['is_deleted', 'deleted_at']),
        ]

class UserFolder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    color_class = models.CharField(max_length=50, default="bg-primary") # For your premium UI
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
class SharedLink(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    file = models.ForeignKey(UserFile, on_delete=models.CASCADE, related_name='shares')
    receipient_email = models.EmailField(null=True)
    is_revoked = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True)
    is_accessed = models.BooleanField(default=False)
    download_count = models.IntegerField(default=0)
    download_limit = models.IntegerField(default=5, help_text="Max downloads allowed. 0 means preview only.")
    message = models.TextField(null=True, blank=True)
    expires_at = models.DateTimeField() 
    created_at = models.DateTimeField(auto_now_add=True)
    
    @property
    def is_expired(self):
        """Simple, direct security check."""
        return timezone.now() > self.expires_at
    
    class Meta:
        db_table = "SharedLink"

class Workstation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_workstations')
    content = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "Workstations"

class WorkstationMember(models.Model):
    ROLE_CHOICES = [
        ('OWNER', 'Owner'),
        ('EDITOR', 'Editor'),
        ('VIEWER', 'Viewer'),
    ]
    workstation = models.ForeignKey(Workstation, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workstation_memberships')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='EDITOR')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('workstation', 'user')
        db_table = "WorkstationMembers"

class WorkstationInvite(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
    ]
    workstation = models.ForeignKey(Workstation, on_delete=models.CASCADE, related_name='invites')
    inviter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_invites')
    invitee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_invites')
    role = models.CharField(max_length=10, choices=WorkstationMember.ROLE_CHOICES, default='EDITOR')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "WorkstationInvites"

class WorkstationVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workstation = models.ForeignKey(Workstation, on_delete=models.CASCADE, related_name='versions')
    content = models.TextField(blank=True, default="")
    saved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='workstation_versions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "WorkstationVersions"

class ChunkedUpload(models.Model):
    upload_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    filename = models.CharField(max_length=255)
    total_size = models.BigIntegerField()
    current_size = models.BigIntegerField(default=0)
    file_path = models.CharField(max_length=500) # Temporary path on server
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, default='uploading') # uploading, completed, cancelled

    class Meta:
        db_table = "ChunkedUploads"
        ordering = ['-updated_at']

def default_file_request_expiry():
    from datetime import timedelta
    from django.utils import timezone
    return timezone.now() + timedelta(hours=24)

class FileRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_file_requests')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_file_requests')
    note = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('fulfilled', 'Fulfilled'), ('declined', 'Declined')], default='pending')
    files = models.ManyToManyField(UserFile, related_name='file_requests', blank=True)
    expires_at = models.DateTimeField(default=default_file_request_expiry)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "FileRequests"
        ordering = ['-created_at']