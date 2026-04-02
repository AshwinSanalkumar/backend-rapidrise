from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.conf import settings
import uuid

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

    USERNAME_FIELD='email'
    REQUIRED_FIELDS = ["first_name", "last_name"]

def file_storage_path(instance, filename):
    return f'user_{instance.owner.id}/files/{filename}'

class UserFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name=models.CharField(max_length=255,null=True)
    is_favorite=models.BooleanField(default=False)
    content = models.FileField(upload_to=file_storage_path)
    file_size_bytes = models.BigIntegerField()
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, editable=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description=models.CharField(max_length=250, null=True)
    
    class Meta:
        db_table = "Files"