import os
import sys
import django
from decimal import Decimal
from datetime import date, timedelta

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'income_tracker.settings')
django.setup()

from django.contrib.auth.models import User
from tracker.models import Profile, Transaction, Budget, Reminder
from tracker.views import seed_user_demo_data

def run():
    print("🚀 Initializing Leoxur Financial Core Seeder...")
    
    # 1. Create or get target default user
    username = 'admin'
    email = 'admin@leoxur.fi'
    password = 'admin123'
    
    user, created = User.objects.get_or_create(username=username, email=email)
    if created:
        user.set_password(password)
        user.save()
        print(f"✅ User node '{username}' successfully deployed with default key '{password}'.")
    else:
        print(f"ℹ️ User node '{username}' already exists. Re-seeding telemetry...")

    # Clear old data for this user to avoid overlapping records
    Transaction.objects.filter(user=user).delete()
    Budget.objects.filter(user=user).delete()
    Reminder.objects.filter(user=user).delete()
    print("🧹 Cleared old transactions, budgets, and reminders.")

    # 2. Seed data
    seed_user_demo_data(user)
    print("📊 Rich demo telemetry data injected successfully!")
    print("\n🎉 Seeding complete. Start the local server with:")
    print("   python3 manage.py runserver")
    print(f"   Log in using Username: '{username}' | Password: '{password}'")

if __name__ == '__main__':
    run()
