from rest_framework import serializers
from .models import User
import re
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

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
    
    def validate_email(self, value):
        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data["message"] = "Login successful"
        data["email"] = self.user.email
        data["user_id"] = str(self.user.id)
        return data