from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Main Dashboard
    path('', views.dashboard_view, name='dashboard'),
    
    # User Authentication
    path('signup/', views.signup_view, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='tracker/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # Settings Management
    path('settings/toggle-theme/', views.toggle_theme, name='toggle_theme'),
    path('settings/update-currency/', views.update_currency, name='update_currency'),
    path('settings/update-email/', views.update_email_settings, name='update_email_settings'),
    path('settings/test-report/', views.test_email_report, name='test_email_report'),
    path('settings/test-alert/', views.test_email_alert, name='test_email_alert'),
    path('settings/test-reminder/', views.test_email_reminder, name='test_email_reminder'),
    path('settings/sync-now/', views.sync_emails_now, name='sync_emails_now'),
    
    # Transaction Management
    path('transaction/add/', views.add_transaction, name='add_transaction'),
    path('transaction/edit/<int:pk>/', views.edit_transaction, name='edit_transaction'),
    path('transaction/delete/<int:pk>/', views.delete_transaction, name='delete_transaction'),
    path('transaction/delete-bulk/', views.delete_transaction_bulk, name='delete_transaction_bulk'),
    
    # Category Management
    path('category/add/', views.add_category, name='add_category'),
    
    # Budget Management
    path('budget/set/', views.set_budget, name='set_budget'),
    path('budget/delete-category/<str:category>/', views.delete_budget_category, name='delete_budget_category'),
    
    # Reminder Management
    path('reminder/add/', views.add_reminder, name='add_reminder'),
    path('reminder/edit/<int:pk>/', views.edit_reminder, name='edit_reminder'),
    path('reminder/delete/<int:pk>/', views.delete_reminder, name='delete_reminder'),
    path('reminder/pay/<int:pk>/', views.pay_reminder, name='pay_reminder'),
    
    # Data Exports
    path('export/csv/', views.export_csv_view, name='export_csv'),
    path('export/excel/', views.export_excel_view, name='export_excel'),
    path('export/pdf/', views.export_pdf_view, name='export_pdf'),
    path('export/download-template/', views.download_template, name='download_template'),
    path('export/import-transactions/', views.import_transactions, name='import_transactions'),
    
    # API for Analytics Charts and Savings Analyst
    path('api/analytics-data/', views.analytics_data_api, name='analytics_data'),
    path('api/savings-analyst/', views.savings_analyst_chat, name='savings_analyst_chat'),
]
