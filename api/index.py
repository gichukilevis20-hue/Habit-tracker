import os
import sys
import django

# Add the project directory to the Python path
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'habittracker.settings')
django.setup()

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()

def handler(request):
    """Vercel serverless function handler"""
    return app(request.environ, request.start_response)
