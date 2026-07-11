from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from datetime import date
from tracker.models import Reminder
from tracker.views import send_user_mail, render_html_email

class Command(BaseCommand):
    help = 'Sends email alert notifications for bill reminders due today.'

    def handle(self, *args, **options):
        today = date.today()
        # Find unpaid reminders due today
        due_reminders = Reminder.objects.filter(due_date=today, is_paid=False)
        
        if not due_reminders.exists():
            self.stdout.write("No bill reminders due today.")
            return

        self.stdout.write(f"Found {due_reminders.count()} bill reminders due today. Dispatching alerts...")

        for reminder in due_reminders:
            user = reminder.user
            if not user.email:
                self.stdout.write(f"Skipping reminder #{reminder.id}: User '{user.username}' has no email configured.")
                continue

            profile = user.profile
            currency = profile.currency

            subject = f"BILL DUE TODAY: {reminder.title}"
            due_date_str = reminder.due_date.strftime('%A, %b %d, %Y')
            recurrence_str = 'Yes (' + reminder.get_recurrence_period_display() + ')' if reminder.is_recurring else 'No'

            content_html = f"""
            <div style="background-color: #3b82f6; color: #ffffff; padding: 16px; border-radius: 12px; margin-bottom: 24px; font-weight: 600; font-size: 13px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px;">
                Scheduled Payment Due Today
            </div>
            <div style="background-color: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; margin-bottom: 16px;">
                <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #334155;">
                        <td style="padding: 10px 0; font-size: 12px; color: #94a3b8;">Bill Description</td>
                        <td style="padding: 10px 0; font-size: 12px; color: #ffffff; font-weight: 600; text-align: right;">{reminder.title}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #334155;">
                        <td style="padding: 10px 0; font-size: 12px; color: #94a3b8;">Amount Due</td>
                        <td style="padding: 10px 0; font-size: 12px; color: #ffffff; font-weight: 600; text-align: right;">{currency}{reminder.amount:.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #334155;">
                        <td style="padding: 10px 0; font-size: 12px; color: #94a3b8;">Due Date</td>
                        <td style="padding: 10px 0; font-size: 12px; color: #ffffff; font-weight: 600; text-align: right;">{due_date_str}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; font-size: 12px; color: #94a3b8;">Recurrence</td>
                        <td style="padding: 10px 0; font-size: 12px; color: #ffffff; font-weight: 600; text-align: right;">{recurrence_str}</td>
                    </tr>
                </table>
            </div>
            <p style="font-size: 12px; color: #94a3b8; line-height: 1.6; margin-top: 16px;">
                This automated transmission has been dispatched to remind you that your scheduled payment is due today. Please log in to your dashboard to pay the reminder and update your records.
            </p>
            """

            email_body = render_html_email(
                title=f"{reminder.title} Payment Due",
                subtitle="Scheduled Reminder Transmission",
                content_html=content_html
            )

            try:
                send_user_mail(user, subject, email_body, is_html=True)
                self.stdout.write(self.style.SUCCESS(f"Alert sent to '{user.username}' for bill '{reminder.title}'."))
            except Exception as e:
                self.stderr.write(f"Failed to send alert for reminder #{reminder.id}: {e}")
