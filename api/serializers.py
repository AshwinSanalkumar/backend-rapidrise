from rest_framework import serializers
import re
from datetime import date
from .models import (
    User, UserFile, UserFolder, SharedLink, Workstation, 
    WorkstationMember, WorkstationInvite, WorkstationVersion, 
    ChunkedUpload, FileRequest
)
from .supabase_storage import SupabaseStorageService

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'dob', 'date_joined', 'consumed_storage', 'storage_limit_bytes']
        read_only_fields = ['id', 'email', 'full_name', 'date_joined', 'consumed_storage', 'storage_limit_bytes']

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def validate_dob(self, value):
        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 15:
            raise serializers.ValidationError("You must be at least 15 years old.")
        return value

    def validate_first_name(self, value):
        if not re.match(r"^[a-zA-Z\s\-]+$", value):
            raise serializers.ValidationError("First name should only contain letters, spaces, or hyphens.")
        if len(value.strip()) < 2:
            raise serializers.ValidationError("First name must be at least 2 characters long.")
        return value.strip()

    def validate_last_name(self, value):
        if not re.match(r"^[a-zA-Z\s\-]+$", value):
            raise serializers.ValidationError("Last name should only contain letters, spaces, or hyphens.")
        if len(value.strip()) < 1: # Last name can be short, but not empty
            raise serializers.ValidationError("Last name cannot be empty.")
        return value.strip()

class RegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=255)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    dob = serializers.DateField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'password', 'confirm_password', 'email', 'first_name', 'last_name','dob']    

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Password fields must match."})
        data.pop('confirm_password')
        return data

    
    def validate_password(self, value):
        if not re.search(r"[a-z]", value):
            raise serializers.ValidationError("Password Must contain atleast One lower case ")
        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError("Password Must contain atleast One Uppercase")
        if not re.search(r"[!@#$%^&*()]", value):
            raise serializers.ValidationError("Password Must contain atleast One special char")
        if not re.search(r"[0-9]", value):
            raise serializers.ValidationError("Password Must contain atleast One Number")
        return value
    
    def normalize_email(self, email):
        email = email.lower().strip()

        local, domain = email.split("@")
        gmail_domains = ["gmail.com", "googlemail.com"]

        if domain in gmail_domains:
            local = local.split("+")[0]
            local = local.replace(".", "")

        return f"{local}@{domain}"

    def validate_email(self, value):
        value = value.lower().strip()
        regex = r'^[a-zA-Z0-9._+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$'
        if not re.match(regex, value):
            raise serializers.ValidationError(
                "Enter a valid email address."
            )
        blocked_symbols = ["#", "$", "%", "!", "&"]

        if any(symbol in value for symbol in blocked_symbols):
            raise serializers.ValidationError(
                "Email contains invalid characters."
            )

        normalized_email = self.normalize_email(value)
        existing_emails = User.objects.values_list('email', flat=True)

        for email in existing_emails:
            stored_normalized = self.normalize_email(email)

            if stored_normalized == normalized_email:
                raise serializers.ValidationError(
                    "Account already exists."
                )

        return normalized_email

    def validate_dob(self, value):
        today = date.today()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 15:
            raise serializers.ValidationError("You must be at least 15 years old to register.")
        return value

    def validate_first_name(self, value):
        if not re.match(r"^[a-zA-Z\s\-]+$", value):
            raise serializers.ValidationError("First name should only contain letters, spaces, or hyphens.")
        if len(value.strip()) < 2:
            raise serializers.ValidationError("First name must be at least 2 characters long.")
        return value.strip()

    def validate_last_name(self, value):
        if not re.match(r"^[a-zA-Z\s\-]+$", value):
            raise serializers.ValidationError("Last name should only contain letters, spaces, or hyphens.")
        if len(value.strip()) < 1:
            raise serializers.ValidationError("Last name cannot be empty.")
        return value.strip()

class PasswordValidationSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_password(self, value):
        if not re.search(r"[a-z]", value):
            raise serializers.ValidationError("Password Must contain atleast One lower case ")
        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError("Password Must contain atleast One Uppercase")
        if not re.search(r"[!@#$%^&*()]", value):
            raise serializers.ValidationError("Password Must contain atleast One special char")
        if not re.search(r"[0-9]", value):
            raise serializers.ValidationError("Password Must contain atleast One Number")
        return value

class UserFileSerializer(serializers.ModelSerializer):
    """
    File Serializer
    """
    size_readable = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()

    class Meta:
        model = UserFile
        fields = ['id', 'filename', 'display_name', 'description', 'is_favorite', 'is_deleted', 'deleted_at', 'file_size_bytes', 'size_readable', 'content', 'mime_type', 'uploaded_at', 'last_accessed_at']
        read_only_fields = ['id', 'file_size_bytes', 'mime_type', 'uploaded_at', 'deleted_at', 'last_accessed_at']

    def get_content(self, obj):
        # Return Supabase signed URL instead of local media path
        if obj.content:
            # content.name stores the supabase path
            return SupabaseStorageService.create_signed_url(obj.content.name)
        return None

    def get_size_readable(self, obj):
        num = float(obj.file_size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if num < 1024.0:
                return f"{num:.2f} {unit}"
            num /= 1024.0
        return f"{num:.2f} TB"

class FolderSerializer(serializers.ModelSerializer):
    # These fields come from the .annotate() in your Service/View
    files_count = serializers.IntegerField(read_only=True)
    total_size = serializers.IntegerField(read_only=True)

    class Meta:
        model = UserFolder
        fields = ['id', 'name', 'files_count', 'total_size', 'color_class']

class SharedLinkSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField(source='file.filename', read_only=True)
    display_name = serializers.CharField(source='file.display_name', read_only=True)
    file_size = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    def get_file_size(self, obj):
        num = float(obj.file.file_size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if num < 1024.0:
                return f"{num:.2f} {unit}"
            num /= 1024.0
        return f"{num:.2f} TB"

    class Meta:
        model = SharedLink
        fields = [
            'token', 'file', 'file_name', 'display_name', 'file_size',
            'receipient_email', 'is_accessed', 'download_count', 
            'download_limit', 'is_revoked', 'revoked_at', 'expires_at', 
            'created_at', 'is_expired', 'message'
        ]

class WorkstationMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkstationMember
        fields = ['id', 'user', 'user_email', 'user_name', 'role', 'joined_at']

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

class WorkstationInviteSerializer(serializers.ModelSerializer):
    workstation_title = serializers.CharField(source='workstation.title', read_only=True)
    inviter_name = serializers.SerializerMethodField()
    invitee_email = serializers.EmailField(source='invitee.email', read_only=True)

    class Meta:
        model = WorkstationInvite
        fields = ['id', 'workstation', 'workstation_title', 'inviter', 'inviter_name', 'invitee', 'invitee_email', 'role', 'status', 'created_at']
        read_only_fields = ['id', 'inviter', 'status', 'created_at']

    def get_inviter_name(self, obj):
        return f"{obj.inviter.first_name} {obj.inviter.last_name}"

class WorkstationSerializer(serializers.ModelSerializer):
    members = WorkstationMemberSerializer(many=True, read_only=True)
    owner_name = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Workstation
        fields = ['id', 'title', 'description', 'content', 'owner', 'owner_name', 'owner_email', 'members', 'member_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'owner', 'created_at', 'updated_at']

    def get_owner_name(self, obj):
        return f"{obj.owner.first_name} {obj.owner.last_name}"

    def get_member_count(self, obj):
        return obj.members.count()

class UserSearchSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name']

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

class WorkstationVersionSerializer(serializers.ModelSerializer):
    saved_by_name = serializers.SerializerMethodField()
    saved_by_email = serializers.EmailField(source='saved_by.email', read_only=True)

    class Meta:
        model = WorkstationVersion
        fields = ['id', 'workstation', 'content', 'saved_by', 'saved_by_name', 'saved_by_email', 'created_at']
        read_only_fields = ['id', 'workstation', 'saved_by', 'created_at']

    def get_saved_by_name(self, obj):
        if obj.saved_by:
            return f"{obj.saved_by.first_name} {obj.saved_by.last_name}"
        return "Unknown"


class FileRequestSerializer(serializers.ModelSerializer):
    sender_email = serializers.EmailField(source='sender.email', read_only=True)
    sender_name = serializers.SerializerMethodField()
    recipient_email = serializers.EmailField(source='recipient.email', read_only=True)
    files = UserFileSerializer(many=True, read_only=True)

    class Meta:
        model = FileRequest
        fields = ['id', 'sender', 'sender_email', 'sender_name', 'recipient', 'recipient_email', 'note', 'status', 'files', 'created_at', 'updated_at']
        read_only_fields = ['id', 'sender', 'status', 'created_at', 'updated_at']

    def get_sender_name(self, obj):
        return f"{obj.sender.first_name} {obj.sender.last_name}"

class ChunkedUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChunkedUpload
        fields = ['upload_id', 'filename', 'total_size', 'current_size', 'status', 'created_at']
        read_only_fields = ['upload_id', 'current_size', 'status', 'created_at']