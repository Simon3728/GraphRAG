from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
import json

@login_required
def chatbot_view(request):
    """Main chatbot interface"""
    return render(request, 'chatbot/chatbot.html')

@login_required
@csrf_exempt
def chat_response(request):
    """Handle chat messages via AJAX"""
    if request.method == 'POST':
        data = json.loads(request.body)
        user_message = data.get('message', '')
        
        # Simple chatbot logic (replace with your AI/logic)
        bot_response = generate_bot_response(user_message)
        
        return JsonResponse({
            'response': bot_response,
            'status': 'success'
        })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

def generate_bot_response(message):
    """Simple chatbot logic - replace with your implementation"""
    message_lower = message.lower()
    
    if 'hello' in message_lower or 'hi' in message_lower:
        return "Hello! How can I help you today?"
    elif 'help' in message_lower:
        return "I'm here to assist you. What do you need help with?"
    elif 'bye' in message_lower:
        return "Goodbye! Have a great day!"
    else:
        return f"I received your message: '{message}'. How can I help you with that?"