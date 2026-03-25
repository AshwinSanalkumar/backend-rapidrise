from .models import User
from django.core.exceptions import ValidationError

def register_user(email, password, first_name, last_name, dob):
    if User.objects.filter(email=email).exists():
        raise ValidationError("Email already registered.")
    return User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        dob=dob
    )