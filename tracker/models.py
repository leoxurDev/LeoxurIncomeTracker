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
    # AI Copilot & Agent Configurations
    AI_MODE_CHOICES = [
        ('cloud', 'Cloud AI (LLM / Agent Mode)'),
        ('local', 'Local Engine (Deterministic & Offline)'),
    ]
    AI_PROVIDER_CHOICES = [
        ('gemini', 'Google Gemini AI'),
        ('groq', 'Groq (Ultra-Fast Llama 3)'),
        ('openai', 'OpenAI (ChatGPT / GPT-4o)'),
        ('anthropic', 'Anthropic Claude'),
        ('openrouter', 'OpenRouter'),
        ('custom', 'Custom OpenAI-Compatible API'),
    ]
    ai_mode = models.CharField(max_length=20, choices=AI_MODE_CHOICES, default='cloud')
    ai_provider = models.CharField(max_length=30, choices=AI_PROVIDER_CHOICES, default='gemini')
    ai_api_key = models.CharField(max_length=255, blank=True, default='')
    gemini_api_key = models.CharField(max_length=255, blank=True, default='')
    ai_model = models.CharField(max_length=100, blank=True, default='')
    ai_custom_endpoint = models.CharField(max_length=255, blank=True, default='')

    def get_saved_ai_key(self):
        return (self.ai_api_key.strip() or self.gemini_api_key.strip())

    def get_active_ai_key(self):
        if getattr(self, 'ai_mode', 'cloud') == 'local':
            return ''
        return self.get_saved_ai_key()

    def get_effective_ai_model(self):
        if self.ai_model and self.ai_model.strip():
            m = self.ai_model.strip()
            # Automatically upgrade deprecated Gemini model names
            if m not in ('gemini-1.5-flash', 'gemini-2.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash'):
                return m
        defaults = {
            'gemini': 'gemini-3.5-flash-lite',
            'groq': 'llama-3.3-70b-versatile',
            'openai': 'gpt-4o-mini',
            'anthropic': 'claude-3-5-sonnet-20241022',
            'openrouter': 'google/gemini-2.0-flash-exp:free',
            'custom': 'default',
        }
        return defaults.get(self.ai_provider, 'gemini-3.5-flash-lite')

    def get_ai_provider_display_name(self):
        return dict(self.AI_PROVIDER_CHOICES).get(self.ai_provider, self.ai_provider.title())

    
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


class MoneyWorkflow(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='money_workflows')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    trigger_type = models.CharField(max_length=50, default='inflow_salary')
    is_active = models.BooleanField(default=True)
    canvas_state = models.JSONField(default=dict, blank=True)
    execution_count = models.IntegerField(default=0)
    last_executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.user.username})"

