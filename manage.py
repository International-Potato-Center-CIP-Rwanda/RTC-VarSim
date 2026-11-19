"""Django command entry point. Start the visible local server with runserver; this file does not prepare research data."""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_app.settings')
from django.core.management import execute_from_command_line
execute_from_command_line(sys.argv)
