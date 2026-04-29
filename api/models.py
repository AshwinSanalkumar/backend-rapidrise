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
    message = models.TextField(null=True, blank=True)
    expires_at = models.DateTimeField() 
    created_at = models.DateTimeField(auto_now_add=True)
    
    @property
    def is_expired(self):
        """Simple, direct security check."""
        return timezone.now() > self.expires_at
    
    class Meta:
        db_table = "SharedLink"