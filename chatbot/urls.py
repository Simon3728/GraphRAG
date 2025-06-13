from django.urls import path
from . import views

app_name = 'chatbot'
urlpatterns = [
    path('', views.chatbot_view, name='chatbot'),
    path('chat/', views.chat_response, name='chat_response'),
]