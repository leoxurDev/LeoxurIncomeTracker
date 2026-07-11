from django.contrib import admin
from .models import Profile, Category, Transaction, Budget, Reminder

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme', 'currency')
    list_filter = ('theme', 'currency')
    search_fields = ('user__username', 'user__email')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'is_income')
    list_filter = ('is_income', 'user')
    search_fields = ('name', 'user__username')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'amount', 'transaction_type', 'category', 'date', 'description')
    list_filter = ('transaction_type', 'category', 'date', 'user')
    search_fields = ('description', 'category', 'user__username')
    date_hierarchy = 'date'

@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('user', 'category', 'amount', 'period', 'month', 'year')
    list_filter = ('period', 'month', 'year', 'category', 'user')
    search_fields = ('category', 'user__username')

@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'amount', 'due_date', 'is_recurring', 'recurrence_period', 'is_paid')
    list_filter = ('is_recurring', 'recurrence_period', 'is_paid', 'due_date', 'user')
    search_fields = ('title', 'user__username')
