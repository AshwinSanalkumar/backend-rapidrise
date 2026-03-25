from django.urls import path
from .views import RegisterView 
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # Using 'register/' as the endpoint
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('login/',TokenObtainPairView.as_view(),name='login'),
    path('refresh/',TokenRefreshView.as_view(),name='login'), 

]