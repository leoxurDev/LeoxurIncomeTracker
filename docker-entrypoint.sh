#!/bin/sh
set -e

echo "=== Leoxur Financial Telemetry Container Startup ==="

# 1. Wait for database if external DB is configured
python3 wait_for_db.py

# 2. Run Database Migrations
echo "Applying database migrations..."
python3 manage.py migrate --noinput

# 3. Collect Static Files
echo "Collecting static assets..."
python3 manage.py collectstatic --noinput

# 4. Ensure logs and data directories exist
mkdir -p /app/logs /app/staticfiles

# 5. Optional Superuser Creation on Initial Launch
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "Verifying default administrator user ($DJANGO_SUPERUSER_USERNAME)..."
    python3 manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
username = '$DJANGO_SUPERUSER_USERNAME'
email = '${DJANGO_SUPERUSER_EMAIL:-admin@example.com}'
password = '$DJANGO_SUPERUSER_PASSWORD'
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print(f'Superuser \"{username}\" created successfully.')
else:
    print(f'Superuser \"{username}\" is verified.')
" || true
fi

echo "=== Initialization Complete. Launching Gunicorn WSGI Server ==="
exec gunicorn income_tracker.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile -

