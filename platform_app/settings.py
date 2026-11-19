"""Local Django settings. Read the signing secret from the environment; the marked fallback is development-only and DEBUG defaults to False."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Development fallback only. Set DJANGO_SECRET_KEY before any deployment.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or 'INSECURE-DEVELOPMENT-ONLY-DO-NOT-DEPLOY'
DEBUG = False
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
ROOT_URLCONF = 'platform_app.urls'
INSTALLED_APPS = []
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True}]
DEFAULT_CHARSET = 'utf-8'
LANGUAGE_CODE = 'en-us'
