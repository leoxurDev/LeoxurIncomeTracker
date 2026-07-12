from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from datetime import date
from decimal import Decimal
import calendar
from django.db.models import Sum

from tracker.models import Transaction, Budget
from tracker.views import generate_excel_data, generate_pdf_data, send_user_mail, render_html_email

class Command(BaseCommand):
    help = 'Sends a daily financial summary report email with PDF and Excel statement attachments.'

    def handle(self, *args, **options):
        # Find all users with email address configured
        users = User.objects.exclude(email='')
        if not users.exists():
            self.stdout.write("No users with emails found to dispatch daily reports.")
            return

        self.stdout.write(f"Preparing daily financial summaries for {users.count()} user(s)...")

        for user in users:
            try:
                # 1. Fetch current monthly statistics
                today = date.today()
                start_of_month = date(today.year, today.month, 1)
                _, last_day = calendar.monthrange(today.year, today.month)
                end_of_month = date(today.year, today.month, last_day)

                month_txs = Transaction.objects.filter(user=user, date__range=(start_of_month, end_of_month))
                total_income = month_txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
                total_expense = month_txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
                balance = total_income - total_expense

                raw_currency = user.profile.currency
                currency_map = {
                    '$': '$',
                    '€': 'EUR ',
                    '₹': 'INR ',
                    '£': 'GBP ',
                }
                currency = currency_map.get(raw_currency, raw_currency + ' ')

                # Active budgets
                budgets = Budget.objects.filter(user=user, year=today.year, month=today.month)
                
                # Render Ratio and Balances Card
                expense_pct = int((total_expense / total_income * 100)) if total_income > 0 else 0
                if expense_pct > 100: expense_pct = 100

                balances_html = f"""
                <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 24px; border-spacing: 12px; border-collapse: separate; margin-left: -12px; margin-right: -12px;">
                    <tr>
                        <td width="50%" style="background-color: #ffffff; padding: 16px; border-radius: 12px; border: 1px solid #e5e5ea; font-family: -apple-system, sans-serif;">
                            <div style="font-size: 10px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700;">Total Inflows</div>
                            <div style="font-size: 22px; font-weight: 700; color: #34c759; margin-top: 6px;">{currency}{total_income:.2f}</div>
                        </td>
                        <td width="50%" style="background-color: #ffffff; padding: 16px; border-radius: 12px; border: 1px solid #e5e5ea; font-family: -apple-system, sans-serif;">
                            <div style="font-size: 10px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700;">Total Outflows</div>
                            <div style="font-size: 22px; font-weight: 700; color: #ff3b30; margin-top: 6px;">{currency}{total_expense:.2f}</div>
                        </td>
                    </tr>
                </table>
                
                <div style="background-color: #ffffff; padding: 16px; border-radius: 12px; border: 1px solid #e5e5ea; margin-bottom: 24px; font-family: -apple-system, sans-serif;">
                    <div style="font-size: 10px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700; margin-bottom: 8px;">Net Surplus / Deficit</div>
                    <div style="font-size: 20px; font-weight: 700; color: {'#a855f7' if balance >= 0 else '#ff3b30'};">{currency}{balance:.2f}</div>
                    <div style="margin-top: 12px; background-color: #e5e5ea; border-radius: 9999px; height: 6px; overflow: hidden; width: 100%;">
                        <div style="background-color: #a855f7; height: 100%; width: {expense_pct}%; border-radius: 9999px;"></div>
                    </div>
                    <div style="font-size: 9px; color: #8e8e93; margin-top: 6px; text-align: right;">Spending ratio: {expense_pct}% of total inflow</div>
                </div>
                """

                budget_lines = []
                for b in budgets:
                    spent = total_expense if b.category == 'Total' else month_txs.filter(category=b.category, transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
                    pct = int((spent / b.amount * 100)) if b.amount > 0 else 0
                    fill_pct = pct if pct <= 100 else 100
                    bar_color = "#ff3b30" if pct >= 100 else "#a855f7"
                    budget_lines.append(f"""
                    <div style="margin-bottom: 14px; font-family: -apple-system, sans-serif;">
                        <div style="font-size: 11px; margin-bottom: 4px; color: #1c1c1e;">
                            <span style="font-weight: 600;">{b.category}</span>
                            <span style="color: #8e8e93; float: right;">{currency}{spent:.2f} / {currency}{b.amount:.2f} ({pct}%)</span>
                        </div>
                        <div style="background-color: #e5e5ea; border-radius: 9999px; height: 6px; overflow: hidden; width: 100%; border: 1px solid #e5e5ea;">
                            <div style="background-color: {bar_color}; height: 100%; width: {fill_pct}%; border-radius: 9999px;"></div>
                        </div>
                    </div>
                    """)
                    
                budgets_html = f"""
                <div style="margin-bottom: 24px; font-family: -apple-system, sans-serif;">
                    <h3 style="font-size: 11px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-bottom: 12px; border-bottom: 1px solid #e5e5ea; padding-bottom: 6px; font-weight: 700;">Budget Targets Health</h3>
                    {"".join(budget_lines) if budget_lines else '<div style="font-size: 11px; color: #8e8e93;">No active budget targets set.</div>'}
                </div>
                """

                recent_rows = []
                txs = Transaction.objects.filter(user=user).order_by('-date')[:5]
                for tx in txs:
                    amt_color = "#34c759" if tx.transaction_type == 'IN' else "#ff3b30"
                    amt_sign = "+" if tx.transaction_type == 'IN' else "-"
                    recent_rows.append(f"""
                    <tr style="border-bottom: 1px solid #e5e5ea;">
                        <td style="padding: 10px 0; font-size: 11px; color: #1c1c1e; font-family: -apple-system, sans-serif;">{tx.description or 'N/A'}</td>
                        <td style="padding: 10px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">{tx.category}</td>
                        <td style="padding: 10px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">{tx.date.strftime('%Y-%m-%d')}</td>
                        <td style="padding: 10px 0; font-size: 11px; text-align: right; font-weight: 600; color: {amt_color}; font-family: -apple-system, sans-serif;">{amt_sign}{currency}{tx.amount:.2f}</td>
                    </tr>
                    """)
                    
                recent_html = f"""
                <div style="margin-bottom: 16px; font-family: -apple-system, sans-serif;">
                    <h3 style="font-size: 11px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-bottom: 12px; border-bottom: 1px solid #e5e5ea; padding-bottom: 6px; font-weight: 700;">Recent Ledger Entries</h3>
                    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                        <thead>
                            <tr style="text-align: left; border-bottom: 1px solid #e5e5ea;">
                                <th style="padding-bottom: 6px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Description</th>
                                <th style="padding-bottom: 6px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Category</th>
                                <th style="padding-bottom: 6px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Date</th>
                                <th style="padding-bottom: 6px; font-size: 10px; text-transform: uppercase; color: #8e8e93; text-align: right; font-weight: 700; font-family: -apple-system, sans-serif;">Amount</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join(recent_rows) if recent_rows else '<tr><td colspan="4" style="padding: 12px 0; font-size: 11px; color: #8e8e93; text-align: center; font-family: -apple-system, sans-serif;">No transactions registered.</td></tr>'}
                        </tbody>
                    </table>
                </div>
                """

                content_html = f"""
                {balances_html}
                {budgets_html}
                {recent_html}
                """

                email_body = render_html_email(
                    title="Daily Financial Summary Report",
                    subtitle=f"Generated Statement for '{user.username}'",
                    content_html=content_html
                )

                # Generate statements
                excel_data = generate_excel_data(user)
                pdf_data = generate_pdf_data(user, total_income, total_expense, balance, currency)

                # Dispatch Email using user's custom SMTP credentials
                send_user_mail(
                    user,
                    f"Daily Financial Report - {today.strftime('%b %d, %Y')}",
                    email_body,
                    attachments=[
                        (f"Statement_{today.strftime('%Y%m%d')}.pdf", pdf_data, "application/pdf"),
                        (f"Statement_{today.strftime('%Y%m%d')}.xlsx", excel_data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    ],
                    is_html=True
                )
                self.stdout.write(self.style.SUCCESS(f"Successfully dispatched daily report to '{user.username}' ({user.email})."))

            except Exception as ex:
                self.stderr.write(f"Failed to generate and dispatch daily report for user '{user.username}': {ex}")
