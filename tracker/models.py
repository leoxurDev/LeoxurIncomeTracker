from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class Profile(models.Model):
    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
    ]
    CURRENCY_CHOICES = [
        ('$', 'USD ($)'),
        ('€', 'EUR (€)'),
        ('₹', 'INR (₹)'),
        ('£', 'GBP (£)'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default='dark')
    currency = models.CharField(max_length=5, choices=CURRENCY_CHOICES, default='$')
    
    # SMTP (Outgoing Mail) User Custom Credentials
    smtp_host = models.CharField(max_length=100, default='smtp.gmail.com')
    smtp_port = models.IntegerField(default=587)
    smtp_user = models.CharField(max_length=150, blank=True)
    smtp_password = models.CharField(max_length=150, blank=True)
    
    # IMAP (Incoming Mail) User Custom Credentials
    imap_host = models.CharField(max_length=100, default='imap.gmail.com')
    imap_port = models.IntegerField(default=993)
    imap_user = models.CharField(max_length=150, blank=True)
    imap_password = models.CharField(max_length=150, blank=True)
    auto_fetch_emails = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"

class Category(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=50)
    is_income = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('user', 'name', 'is_income')
        verbose_name_plural = 'categories'
        ordering = ['name']
        
    def __str__(self):
        type_str = "Income" if self.is_income else "Expense"
        return f"{self.name} ({type_str})"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
        # Seed default categories for this user so they are instantly functional
        defaults = [
            ('Salary', True),
            ('Freelance', True),
            ('Investment', True),
            ('Food', False),
            ('Rent', False),
            ('Utilities', False),
            ('Entertainment', False),
            ('Travel', False),
            ('Other', False),
        ]
        for name, is_income in defaults:
            Category.objects.get_or_create(user=instance, name=name, is_income=is_income)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()

class Transaction(models.Model):
    TYPE_CHOICES = [
        ('IN', 'Income (In)'),
        ('OUT', 'Expense (Out)'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    category = models.CharField(max_length=50)  # No choices restriction to support custom categories
    date = models.DateField()
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.transaction_type} - {self.category}: {self.amount} ({self.date})"

class Budget(models.Model):
    PERIOD_CHOICES = [
        ('MONTHLY', 'Monthly'),
        ('YEARLY', 'Yearly'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budgets')
    category = models.CharField(max_length=50)  # No choices restriction to support custom categories
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period = models.CharField(max_length=10, choices=PERIOD_CHOICES, default='MONTHLY')
    month = models.IntegerField(null=True, blank=True)  # 1 to 12
    year = models.IntegerField()
    
    class Meta:
        unique_together = ('user', 'category', 'period', 'month', 'year')

    def __str__(self):
        period_str = f"{self.year}-{self.month:02d}" if self.period == 'MONTHLY' else f"{self.year}"
        return f"{self.category} Budget ({period_str}): {self.amount}"

class Reminder(models.Model):
    RECURRENCE_CHOICES = [
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('YEARLY', 'Yearly'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reminders')
    title = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField()
    is_recurring = models.BooleanField(default=False)
    recurrence_period = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, blank=True, null=True)
    is_paid = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['due_date']

    def __str__(self):
        status = "Paid" if self.is_paid else "Pending"
        return f"{self.title} ({status}) - Due: {self.due_date}"


class ProcessedEmail(models.Model):
    message_id = models.CharField(max_length=255, unique=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.message_id
