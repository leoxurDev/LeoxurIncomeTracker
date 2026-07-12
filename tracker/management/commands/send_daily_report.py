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
                <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 24px; border-spacing: 16px; border-collapse: separate; margin-left: -16px; margin-right: -16px;">
                    <tr>
                        <td width="50%" style="background-color: #ffffff; padding: 20px; border-radius: 14px; border: 1px solid #e5e5ea; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                            <div style="font-size: 10px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700; margin-bottom: 4px;">Total Inflows</div>
                            <div style="font-size: 24px; font-weight: 700; color: #34c759; margin-top: 6px;">{currency}{total_income:.2f}</div>
                        </td>
                        <td width="50%" style="background-color: #ffffff; padding: 20px; border-radius: 14px; border: 1px solid #e5e5ea; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                            <div style="font-size: 10px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700; margin-bottom: 4px;">Total Outflows</div>
                            <div style="font-size: 24px; font-weight: 700; color: #ff3b30; margin-top: 6px;">{currency}{total_expense:.2f}</div>
                        </td>
                    </tr>
                </table>
                
                <div style="background-color: #ffffff; padding: 20px; border-radius: 14px; border: 1px solid #e5e5ea; margin-bottom: 30px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                    <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 12px; border-collapse: collapse;">
                        <tr>
                            <td style="font-size: 10px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700;">Net Surplus / Deficit</td>
                            <td style="font-size: 20px; font-weight: 700; color: {'#a855f7' if balance >= 0 else '#ff3b30'}; text-align: right;">{currency}{balance:.2f}</td>
                        </tr>
                    </table>
                    <div style="background-color: #e5e5ea; border-radius: 9999px; height: 8px; overflow: hidden; width: 100%; margin-top: 8px;">
                        <div style="background-color: #a855f7; height: 100%; width: {expense_pct}%; border-radius: 9999px;"></div>
                    </div>
                    <div style="font-size: 9px; color: #8e8e93; margin-top: 8px; text-align: right;">Spending ratio: {expense_pct}% of total inflow</div>
                </div>
                """

                # 1. SAVINGS INDEX GAUGE
                savings_rate = int((balance / total_income * 100)) if total_income > 0 else 0
                if savings_rate < 0: savings_rate = 0
                if savings_rate > 100: savings_rate = 100
                
                if savings_rate < 10:
                    savings_status = "CRITICAL OUTFLOW"
                    savings_color = "#ff3b30"
                elif savings_rate <= 30:
                    savings_status = "STANDARD SURPLUS"
                    savings_color = "#ff9500"
                else:
                    savings_status = "STRONG SAVINGS INDEX"
                    savings_color = "#34c759"
                    
                savings_gauge_html = f"""
                <div style="background-color: #ffffff; padding: 20px; border-radius: 14px; border: 1px solid #e5e5ea; margin-bottom: 24px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                    <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 12px; border-collapse: collapse;">
                        <tr>
                            <td style="font-size: 11px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700;">Savings Index Gauge</td>
                            <td style="font-size: 11px; font-weight: 700; color: {savings_color}; text-align: right; text-transform: uppercase; letter-spacing: 0.5px;">{savings_status}</td>
                        </tr>
                    </table>
                    
                    <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 8px; border-collapse: collapse;">
                        <tr>
                            <td style="font-size: 22px; font-weight: 700; color: #1c1c1e;">{savings_rate}% <span style="font-size: 12px; color: #8e8e93; font-weight: normal; text-transform: none; letter-spacing: 0;">of monthly inflows saved</span></td>
                        </tr>
                    </table>
                    
                    <div style="position: relative; background: linear-gradient(to right, #ff3b30 0%, #ff9500 30%, #34c759 100%); height: 8px; border-radius: 9999px; width: 100%; margin-top: 12px; margin-bottom: 4px;">
                        <div style="position: absolute; left: {savings_rate}%; margin-left: -4px; top: -2px; width: 8px; height: 12px; background-color: #1c1c1e; border: 2px solid #ffffff; border-radius: 9999px; box-shadow: 0 2px 4px rgba(0,0,0,0.15);"></div>
                    </div>
                    
                    <table width="100%" cellspacing="0" cellpadding="0" style="margin-top: 8px; border-collapse: collapse;">
                        <tr>
                            <td style="font-size: 8px; color: #8e8e93; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px;">Critical (0-10%)</td>
                            <td style="font-size: 8px; color: #8e8e93; font-weight: 700; text-align: center; width: 40%; text-transform: uppercase; letter-spacing: 0.3px;">Standard (10-30%)</td>
                            <td style="font-size: 8px; color: #8e8e93; font-weight: 700; text-align: right; text-transform: uppercase; letter-spacing: 0.3px;">Strong (30%+)</td>
                        </tr>
                    </table>
                </div>
                """

                # 2. OUTFLOW CONCENTRATION
                category_shares = []
                if total_expense > 0:
                    outflow_by_cat = month_txs.filter(transaction_type='OUT').values('category').annotate(total=Sum('amount')).order_by('-total')
                    for item in outflow_by_cat:
                        share_pct = int((item['total'] / total_expense * 100))
                        category_shares.append({
                            'category': item['category'],
                            'total': item['total'],
                            'pct': share_pct
                        })
                
                outflow_concentration_lines = []
                legend_colors = ["#ff3b30", "#34c759", "#007aff", "#ff9500", "#af52de", "#5856d6", "#5ac8fa", "#ffcc00", "#8e8e93"]
                for idx, share in enumerate(category_shares):
                    color = legend_colors[idx % len(legend_colors)]
                    outflow_concentration_lines.append(f"""
                    <div style="margin-bottom: 14px; font-family: -apple-system, sans-serif;">
                        <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 4px; border-collapse: collapse;">
                            <tr>
                                <td style="font-size: 11px; font-weight: 600; color: #1c1c1e; font-family: -apple-system, sans-serif;">
                                    <span style="display: inline-block; width: 8px; height: 8px; border-radius: 9999px; background-color: {color}; margin-right: 6px; vertical-align: middle;"></span>
                                    {share['category']}
                                </td>
                                <td style="font-size: 10px; color: #8e8e93; text-align: right; font-family: -apple-system, sans-serif;">{currency}{share['total']:.2f} ({share['pct']}%)</td>
                            </tr>
                        </table>
                        <div style="background-color: #f5f5f7; border-radius: 9999px; height: 5px; overflow: hidden; width: 100%;">
                            <div style="background-color: {color}; height: 100%; width: {share['pct']}%; border-radius: 9999px;"></div>
                        </div>
                    </div>
                    """)
                outflow_concentration_html = "".join(outflow_concentration_lines) if outflow_concentration_lines else '<div style="font-size: 11px; color: #8e8e93;">No outflows logged.</div>'
                
                outflow_concentration_panel_html = f"""
                <div style="background-color: #ffffff; padding: 20px; border-radius: 14px; border: 1px solid #e5e5ea; margin-bottom: 24px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                    <h3 style="font-size: 12px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-top: 0; margin-bottom: 16px; border-bottom: 1px solid #e5e5ea; padding-bottom: 8px; font-weight: 700;">Outflow Concentration</h3>
                    {outflow_concentration_html}
                </div>
                """

                # 3. WEEKLY FLOW PATTERNS
                weekly_flows = {1: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                                2: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                                3: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                                4: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                                5: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')}}
                for tx in month_txs:
                    w_idx = (tx.date.day - 1) // 7 + 1
                    if w_idx > 5: w_idx = 5
                    weekly_flows[w_idx][tx.transaction_type] += tx.amount
                    
                weekly_flow_lines = []
                for w_idx in sorted(weekly_flows.keys()):
                    inflow = weekly_flows[w_idx]['IN']
                    outflow = weekly_flows[w_idx]['OUT']
                    if inflow == 0 and outflow == 0:
                        continue
                    max_val = max(inflow, outflow)
                    inflow_pct = int((inflow / max_val * 100)) if max_val > 0 else 0
                    outflow_pct = int((outflow / max_val * 100)) if max_val > 0 else 0
                    
                    weekly_flow_lines.append(f"""
                    <div style="margin-bottom: 16px; font-family: -apple-system, sans-serif;">
                        <div style="font-size: 11px; font-weight: 700; color: #1c1c1e; margin-bottom: 6px;">Week {w_idx} Flow Summary</div>
                        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                            <tr>
                                <td width="55" style="font-size: 10px; color: #8e8e93; padding: 2px 0;">Inflow</td>
                                <td style="padding: 2px 0; width: 70%;">
                                    <div style="background-color: #f5f5f7; border-radius: 9999px; height: 5px; width: 100%;">
                                        <div style="background-color: #34c759; height: 100%; width: {inflow_pct}%; border-radius: 9999px;"></div>
                                    </div>
                                </td>
                                <td style="font-size: 10px; font-weight: 600; color: #34c759; text-align: right; padding: 2px 0; padding-left: 8px;">{currency}{inflow:.2f}</td>
                            </tr>
                            <tr>
                                <td width="55" style="font-size: 10px; color: #8e8e93; padding: 2px 0;">Outflow</td>
                                <td style="padding: 2px 0; width: 70%;">
                                    <div style="background-color: #f5f5f7; border-radius: 9999px; height: 5px; width: 100%;">
                                        <div style="background-color: #ff3b30; height: 100%; width: {outflow_pct}%; border-radius: 9999px;"></div>
                                    </div>
                                </td>
                                <td style="font-size: 10px; font-weight: 600; color: #ff3b30; text-align: right; padding: 2px 0; padding-left: 8px;">{currency}{outflow:.2f}</td>
                            </tr>
                        </table>
                    </div>
                    """)
                weekly_flow_html = "".join(weekly_flow_lines) if weekly_flow_lines else '<div style="font-size: 11px; color: #8e8e93;">No weekly flows logged.</div>'
                
                weekly_flow_panel_html = f"""
                <div style="background-color: #ffffff; padding: 20px; border-radius: 14px; border: 1px solid #e5e5ea; margin-bottom: 24px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                    <h3 style="font-size: 12px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-top: 0; margin-bottom: 16px; border-bottom: 1px solid #e5e5ea; padding-bottom: 8px; font-weight: 700;">Weekly Flow Patterns</h3>
                    {weekly_flow_html}
                </div>
                """

                # 4. BUDGET VS SPENT
                budget_vs_spent_lines = []
                for b in budgets:
                    spent = total_expense if b.category == 'Total' else month_txs.filter(category=b.category, transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
                    pct = int((spent / b.amount * 100)) if b.amount > 0 else 0
                    fill_pct = pct if pct <= 100 else 100
                    
                    if pct >= 100:
                        status_label = "BREACHED"
                        status_color = "#ff3b30"
                        bar_color = "#ff3b30"
                    elif pct >= 80:
                        status_label = "WARNING"
                        status_color = "#ff9500"
                        bar_color = "#ff9500"
                    else:
                        status_label = "HEALTHY"
                        status_color = "#34c759"
                        bar_color = "#a855f7"

                    budget_vs_spent_lines.append(f"""
                    <div style="margin-bottom: 20px; font-family: -apple-system, sans-serif;">
                        <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 6px; border-collapse: collapse;">
                            <tr>
                                <td style="font-size: 12px; font-weight: 600; color: #1c1c1e;">
                                    {b.category}
                                    <span style="font-size: 8px; font-weight: 700; color: {status_color}; background-color: rgba(255,255,255,0.1); border: 1px solid {status_color}; padding: 1px 4px; border-radius: 4px; margin-left: 6px; text-transform: uppercase; vertical-align: middle;">{status_label}</span>
                                </td>
                                <td style="font-size: 11px; color: #8e8e93; text-align: right;">{currency}{spent:.2f} / {currency}{b.amount:.2f} ({pct}%)</td>
                            </tr>
                        </table>
                        <div style="background-color: #e5e5ea; border-radius: 9999px; height: 6px; overflow: hidden; width: 100%; border: 1px solid #e5e5ea;">
                            <div style="background-color: {bar_color}; height: 100%; width: {fill_pct}%; border-radius: 9999px;"></div>
                        </div>
                    </div>
                    """)
                budgets_html = "".join(budget_vs_spent_lines) if budget_vs_spent_lines else '<div style="font-size: 11px; color: #8e8e93;">No active budget targets set.</div>'
                
                budget_vs_spent_panel_html = f"""
                <div style="background-color: #ffffff; padding: 20px; border-radius: 14px; border: 1px solid #e5e5ea; margin-bottom: 24px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                    <h3 style="font-size: 12px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-top: 0; margin-bottom: 16px; border-bottom: 1px solid #e5e5ea; padding-bottom: 8px; font-weight: 700;">Budget Vs Spent Targets</h3>
                    {budgets_html}
                </div>
                """

                recent_rows = []
                txs = Transaction.objects.filter(user=user).order_by('-date')[:5]
                for tx in txs:
                    amt_color = "#34c759" if tx.transaction_type == 'IN' else "#ff3b30"
                    amt_sign = "+" if tx.transaction_type == 'IN' else "-"
                    recent_rows.append(f"""
                    <tr style="border-bottom: 1px solid #e5e5ea;">
                        <td style="padding: 12px 0; font-size: 11px; color: #1c1c1e; font-family: -apple-system, sans-serif;">{tx.description or 'N/A'}</td>
                        <td style="padding: 12px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">{tx.category}</td>
                        <td style="padding: 12px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">{tx.date.strftime('%Y-%m-%d')}</td>
                        <td style="padding: 12px 0; font-size: 11px; text-align: right; font-weight: 600; color: {amt_color}; font-family: -apple-system, sans-serif;">{amt_sign}{currency}{tx.amount:.2f}</td>
                    </tr>
                    """)
                    
                recent_html = f"""
                <div style="margin-bottom: 16px; font-family: -apple-system, sans-serif;">
                    <h3 style="font-size: 12px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-bottom: 14px; border-bottom: 1px solid #e5e5ea; padding-bottom: 8px; font-weight: 700;">Recent Ledger Entries</h3>
                    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                        <thead>
                            <tr style="text-align: left; border-bottom: 1px solid #e5e5ea;">
                                <th style="padding-bottom: 8px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Description</th>
                                <th style="padding-bottom: 8px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Category</th>
                                <th style="padding-bottom: 8px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Date</th>
                                <th style="padding-bottom: 8px; font-size: 10px; text-transform: uppercase; color: #8e8e93; text-align: right; font-weight: 700; font-family: -apple-system, sans-serif;">Amount</th>
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
                {savings_gauge_html}
                {weekly_flow_panel_html}
                {outflow_concentration_panel_html}
                {budget_vs_spent_panel_html}
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
