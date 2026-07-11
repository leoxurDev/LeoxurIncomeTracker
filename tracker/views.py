from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Sum
from django.core.mail import send_mail
from django.http import JsonResponse
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
import calendar

from .models import Profile, Transaction, Budget, Reminder, Category
from django.contrib.auth.forms import UserCreationForm

# ----------------- Auth Views -----------------

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            # Create sample data for the user on signup to make it look great instantly
            seed_user_demo_data(user)
            messages.success(request, f"Welcome to Leoxur tracker, {user.username}!")
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'tracker/signup.html', {'form': form})

# ----------------- Dashboard & Analytics -----------------

@login_required
def dashboard_view(request):
    today = date.today()
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)
    
    # Asynchronously fetch incoming email transactions in a background thread if auto-fetch is enabled
    if profile.auto_fetch_emails:
        import threading
        from django.core.management import call_command
        from django.db import connections
        
        def run_background_sync():
            try:
                call_command('fetch_emails')
            except Exception as e:
                print(f"Background email sync failed: {e}")
            finally:
                connections.close_all()

        try:
            threading.Thread(target=run_background_sync).start()
        except Exception as e:
            print(f"Background email fetch trigger failed: {e}")
    
    # Dynamic Category Seeding Fallback (for legacy or existing users)
    if not Category.objects.filter(user=user).exists():
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
            Category.objects.get_or_create(user=user, name=name, is_income=is_income)
            
    user_income_cats = Category.objects.filter(user=user, is_income=True)
    user_expense_cats = Category.objects.filter(user=user, is_income=False)
    
    income_categories = [c.name for c in user_income_cats]
    expense_categories = [c.name for c in user_expense_cats]
    
    # Filter bounds for current month
    start_of_month = date(today.year, today.month, 1)
    _, last_day = calendar.monthrange(today.year, today.month)
    end_of_month = date(today.year, today.month, last_day)

    # Current Month Transactions
    month_txs = Transaction.objects.filter(user=user, date__range=(start_of_month, end_of_month))
    
    # Financial Aggregations
    total_income = month_txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_expense = month_txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    balance = total_income - total_expense
    
    # Category Expenses for current month
    cat_expenses = {}
    for tx in month_txs.filter(transaction_type='OUT'):
        cat_expenses[tx.category] = cat_expenses.get(tx.category, Decimal('0.00')) + tx.amount

    # Budget Progress Calculations
    budgets = Budget.objects.filter(user=user, year=today.year, month=today.month)
    budget_data = []
    alerts = []
    
    for category in expense_categories:
        budget_obj = budgets.filter(category=category).first()
        budget_amount = budget_obj.amount if budget_obj else Decimal('0.00')
        spent = cat_expenses.get(category, Decimal('0.00'))
        
        pct = 0
        if budget_amount > 0:
            pct = int((spent / budget_amount) * 100)
            if pct >= 100:
                alerts.append({
                    'type': 'danger',
                    'message': f"CRITICAL: You have exceeded your monthly budget for {category}! Spent: {profile.currency}{spent:.2f} / Budget: {profile.currency}{budget_amount:.2f} ({pct}%)"
                })
            elif pct >= 80:
                alerts.append({
                    'type': 'warning',
                    'message': f"WARNING: You've reached {pct}% of your monthly budget for {category}. Remaining: {profile.currency}{budget_amount - spent:.2f}"
                })
        
        remaining = budget_amount - spent
        overage = spent - budget_amount
        budget_data.append({
            'category': category,
            'budget': budget_amount,
            'spent': spent,
            'percentage': min(pct, 100) if budget_amount > 0 else 0,
            'raw_percentage': pct,
            'has_budget': budget_amount > 0,
            'remaining': remaining,
            'overage': overage,
        })

    # Overall Total Budget
    overall_budget_obj = budgets.filter(category='Total').first()
    overall_budget = overall_budget_obj.amount if overall_budget_obj else Decimal('0.00')
    overall_pct = 0
    if overall_budget > 0:
        overall_pct = int((total_expense / overall_budget) * 100)
        if overall_pct >= 100:
            alerts.append({
                'type': 'danger',
                'message': f"CRITICAL: Total expenses have breached your overall budget! Spent: {profile.currency}{total_expense:.2f} / Budget: {profile.currency}{overall_budget:.2f} ({overall_pct}%)"
            })
        elif overall_pct >= 80:
            alerts.append({
                'type': 'warning',
                'message': f"WARNING: Total expenses at {overall_pct}% of overall budget. Remaining: {profile.currency}{overall_budget - total_expense:.2f}"
            })

    # Smart Saving Recommendations
    recommendations = generate_recommendations(user, cat_expenses, total_income)

    # Reminders
    reminders = Reminder.objects.filter(user=user, is_paid=False)
    upcoming_reminders = reminders.filter(due_date__gte=today)
    overdue_reminders = reminders.filter(due_date__lt=today)
    
    recent_transactions = Transaction.objects.filter(user=user).order_by('-date', '-created_at')[:500]

    # Calculate gamified Financial Health Score
    health_score = 100
    if total_income > 0:
        outflow_ratio = total_expense / total_income
        if outflow_ratio > 1.0:
            health_score -= 30
        elif outflow_ratio > 0.9:
            health_score -= 15
        elif outflow_ratio > 0.8:
            health_score -= 5
    else:
        if total_expense > 0:
            health_score -= 30

    breached_count = 0
    for category in expense_categories:
        b_obj = budgets.filter(category=category).first()
        if b_obj and b_obj.amount > 0:
            spent = cat_expenses.get(category, Decimal('0.00'))
            if spent > b_obj.amount:
                breached_count += 1
    health_score -= min(breached_count * 15, 35)

    overdue_count = overdue_reminders.count()
    health_score -= min(overdue_count * 10, 30)
    health_score = max(10, health_score)
    health_offset = float(175.9 * (1.0 - health_score / 100.0))

    context = {
        'profile': profile,
        'total_income': total_income,
        'total_expense': total_expense,
        'balance': balance,
        'budget_data': budget_data,
        'overall_budget': overall_budget,
        'overall_percentage': min(overall_pct, 100) if overall_budget > 0 else 0,
        'overall_raw_percentage': overall_pct,
        'overall_remaining': overall_budget - total_expense,
        'alerts': alerts,
        'recommendations': recommendations,
        'upcoming_reminders': upcoming_reminders,
        'overdue_reminders': overdue_reminders,
        'recent_transactions': recent_transactions,
        'user_income_cats': user_income_cats,
        'user_expense_cats': user_expense_cats,
        'expense_categories': expense_categories,
        'today': today,
        'health_score': health_score,
        'health_offset': health_offset,
    }
    return render(request, 'tracker/dashboard.html', context)


def generate_recommendations(user, current_expenses, current_income):
    recommendations = []
    currency = user.profile.currency
    total_expenses = sum(current_expenses.values())

    # 1. Total expenses vs Income
    if total_expenses > current_income and current_income > 0:
        pct = int((total_expenses / current_income) * 100)
        recommendations.append(
            f"Alert: Outflows are {pct}% of your income. Consider suspending non-essential subscriptions and entertainment spending."
        )

    # 2. Category spending comparison to last month
    today = date.today()
    first_of_this_month = date(today.year, today.month, 1)
    last_month_date = first_of_this_month - timedelta(days=1)
    
    last_month_transactions = Transaction.objects.filter(
        user=user,
        transaction_type='OUT',
        date__year=last_month_date.year,
        date__month=last_month_date.month
    )
    
    last_month_expenses = {}
    for tx in last_month_transactions:
        last_month_expenses[tx.category] = last_month_expenses.get(tx.category, Decimal('0.00')) + tx.amount

    for category, current_amount in current_expenses.items():
        prev_amount = last_month_expenses.get(category, Decimal('0.00'))
        if prev_amount > 0 and current_amount > prev_amount:
            increase = current_amount - prev_amount
            increase_pct = int((increase / prev_amount) * 100)
            if increase_pct >= 15:
                recommendations.append(
                    f"You spent {increase_pct}% more on {category} this month than last month. Cutting back could save you {currency}{increase:.2f}."
                )

    # 3. Large concentration of expenses
    if total_expenses > 0:
        for category, amount in current_expenses.items():
            pct = (amount / total_expenses) * 100
            if pct > 30 and category not in ['Rent', 'Other']:
                recommendations.append(
                    f"{category} accounts for {int(pct)}% of all outflows. Setting a tighter budget here will accelerate your savings."
                )

    # 4. No Budgets set check
    user_budgets = Budget.objects.filter(user=user, year=today.year, month=today.month)
    if not user_budgets.exists():
        recommendations.append(
            "You haven't set any monthly budgets! Users with target budgets save an average of 18% more monthly."
        )

    if not recommendations:
        recommendations.append(
            "Tip: Review your active category budget targets to optimize monthly surplus outflows."
        )

    return recommendations[:3]

# ----------------- AJAX/JSON Analytics Data -----------------

@login_required
def analytics_data_api(request):
    user = request.user
    today = date.today()
    
    # 1. 6-Month Trends: Income vs Expense
    trends = []
    # Generate last 6 months list
    for i in range(5, -1, -1):
        # Subtract months
        year = today.year
        month = today.month - i
        if month <= 0:
            month += 12
            year -= 1
        
        _, last_day = calendar.monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)
        
        txs = Transaction.objects.filter(user=user, date__range=(start, end))
        inc = txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        exp = txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        trends.append({
            'month': start.strftime('%b %Y'),
            'income': float(inc),
            'expense': float(exp),
        })

    # 2. Current Month Category Expense Breakdown
    start_of_month = date(today.year, today.month, 1)
    _, last_day = calendar.monthrange(today.year, today.month)
    end_of_month = date(today.year, today.month, last_day)
    
    month_exp_txs = Transaction.objects.filter(
        user=user, 
        transaction_type='OUT', 
        date__range=(start_of_month, end_of_month)
    )
    
    category_totals = {}
    for tx in month_exp_txs:
        category_totals[tx.category] = category_totals.get(tx.category, 0.0) + float(tx.amount)
        
    categories = list(category_totals.keys())
    values = list(category_totals.values())
    
    # 3. Weekly Outflow Distribution (Week 1: 1-7, Week 2: 8-14, Week 3: 15-21, Week 4: 22-end)
    weekly_sums = [0.0, 0.0, 0.0, 0.0]
    for tx in month_exp_txs:
        day = tx.date.day
        if day <= 7:
            weekly_sums[0] += float(tx.amount)
        elif day <= 14:
            weekly_sums[1] += float(tx.amount)
        elif day <= 21:
            weekly_sums[2] += float(tx.amount)
        else:
            weekly_sums[3] += float(tx.amount)

    # 4. Budget vs Spent
    expense_categories = ['Food', 'Rent', 'Utilities', 'Entertainment', 'Travel', 'Other']
    budgets = Budget.objects.filter(user=user, year=today.year, month=today.month)
    
    comp_labels = []
    comp_budgets = []
    comp_spent = []
    
    for cat in expense_categories:
        b_obj = budgets.filter(category=cat).first()
        b_amount = float(b_obj.amount) if b_obj else 0.0
        s_amount = float(category_totals.get(cat, 0.0))
        if b_amount > 0 or s_amount > 0:
            comp_labels.append(cat)
            comp_budgets.append(b_amount)
            comp_spent.append(s_amount)

    # Return everything in single clean payload
    return JsonResponse({
        'trends': trends,
        'category_breakdown': {
            'labels': categories,
            'data': values
        },
        'budget_vs_spent': {
            'labels': comp_labels,
            'budgets': comp_budgets,
            'spent': comp_spent
        },
        'weekly_distribution': {
            'labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
            'data': weekly_sums
        }
    })


@login_required
def savings_analyst_chat(request):
    if request.method == 'POST':
        import json
        try:
            body = json.loads(request.body)
            query = body.get('query', '').strip()
        except Exception:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON body'}, status=400)
            
        if not query:
            return JsonResponse({'status': 'error', 'message': 'Query cannot be empty'}, status=400)
            
        user = request.user
        today = date.today()
        start_of_month = date(today.year, today.month, 1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_of_month = date(today.year, today.month, last_day)
        
        month_txs = Transaction.objects.filter(user=user, date__range=(start_of_month, end_of_month))
        total_income = float(month_txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
        total_expense = float(month_txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
        balance = total_income - total_expense
        
        # Category breakdown
        category_totals = {}
        for tx in month_txs.filter(transaction_type='OUT'):
            category_totals[tx.category] = category_totals.get(tx.category, 0.0) + float(tx.amount)
            
        budgets = Budget.objects.filter(user=user, year=today.year, month=today.month)
        
        q = query.lower()
        
        if "save" in q or "saving" in q or "how to" in q:
            if total_expense > 0:
                highest_cat = max(category_totals, key=category_totals.get) if category_totals else None
                highest_val = category_totals.get(highest_cat, 0.0) if highest_cat else 0.0
                if highest_cat and highest_val > 0:
                    pct = int((highest_val / total_expense) * 100)
                    response = f"Your primary saving leverage is in **{highest_cat}** which comprises {pct}% of your monthly expense. Capping non-essential purchases there by setting a target limit will immediately improve your cash balance."
                else:
                    response = "You have no active expenses logged this month! Saving starts with tracking. Try entering some transactions or setting category budgets."
            else:
                response = "Your monthly expense sheet is clean! Try setting a savings goal of at least 20% of your total income, and allocating category budgets to help structure incoming capital."
                
        elif "spend" in q or "expense" in q or "where" in q:
            if category_totals:
                items = [f"**{c}** ({user.profile.currency}{v:.2f})" for c, v in category_totals.items()]
                response = f"This month, your outflows are distributed as: {', '.join(items)}. Total current expenses sum up to **{user.profile.currency}{total_expense:.2f}**."
            else:
                response = "No outflows recorded for this month. All of your incoming cash is currently categorized as pure savings."
                
        elif "budget" in q or "limit" in q:
            if budgets.exists():
                lines = []
                for b in budgets:
                    spent = category_totals.get(b.category, 0.0)
                    lines.append(f"**{b.category}**: Limit {user.profile.currency}{b.amount:.2f} / Spent {user.profile.currency}{spent:.2f}")
                response = "Your active monthly category limits:<br>" + "<br>".join(lines)
            else:
                response = "You have no monthly category budgets configured. Setting limits for volatile categories (like Food or Entertainment) helps protect against impulsive purchases."
                
        else:
            savings_rate = int((balance / total_income) * 100) if total_income > 0 and balance > 0 else 0
            response = f"Leoxur savings analysis confirms a current month cashflow of **{user.profile.currency}{total_income:.2f}** inflow vs **{user.profile.currency}{total_expense:.2f}** outflow. Your savings rate is **{savings_rate}%**. Focus on category budget limits and review recurring bill reminders to optimize this further."

        return JsonResponse({'status': 'success', 'response': response})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

# ----------------- Settings Views -----------------

@login_required
def toggle_theme(request):
    if request.method == 'POST':
        profile = request.user.profile
        profile.theme = 'light' if profile.theme == 'dark' else 'dark'
        profile.save()
        return JsonResponse({'status': 'success', 'theme': profile.theme})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)


@login_required
def update_currency(request):
    if request.method == 'POST':
        currency = request.POST.get('currency')
        rate_str = request.POST.get('conversion_rate', '1.0')
        if currency in ['$', '€', '₹', '£']:
            try:
                rate_str = rate_str.replace(',', '.')
                rate = Decimal(rate_str)
            except Exception as e:
                print(f"[Currency Convert Error] Failed to parse rate '{rate_str}': {e}")
                rate = Decimal('1.00')

            profile = request.user.profile
            
            # If a conversion rate is supplied and it's not 1.0, scale all existing amounts
            if rate != Decimal('1.00') and rate > 0:
                # 1. Transactions
                txs = Transaction.objects.filter(user=request.user)
                for tx in txs:
                    tx.amount = tx.amount * rate
                    tx.save()
                    
                # 2. Budgets
                budgets = Budget.objects.filter(user=request.user)
                for b in budgets:
                    b.amount = b.amount * rate
                    b.save()
                    
                # 3. Reminders
                reminders = Reminder.objects.filter(user=request.user)
                for r in reminders:
                    r.amount = r.amount * rate
                    r.save()
                    
                messages.success(request, f"Currency updated to {dict(Profile.CURRENCY_CHOICES).get(currency)}. Telemetry scaled by {rate}!")
            else:
                messages.success(request, f"Currency updated to {dict(Profile.CURRENCY_CHOICES).get(currency)} (values preserved).")

            profile.currency = currency
            profile.save()
        else:
            messages.error(request, "Invalid currency choice")
    return redirect('dashboard')

# ----------------- Action Views (CRUD) -----------------

def check_and_send_budget_alerts(user, category, tx_date):
    if not user.email:
        return
        
    try:
        if isinstance(tx_date, str):
            from datetime import datetime
            d = datetime.strptime(tx_date, '%Y-%m-%d').date()
        else:
            d = tx_date
            
        start_of_month = date(d.year, d.month, 1)
        _, last_day = calendar.monthrange(d.year, d.month)
        end_of_month = date(d.year, d.month, last_day)
        
        budgets = Budget.objects.filter(user=user, year=d.year, month=d.month, category__in=[category, 'Total'])
        if not budgets.exists():
            return
            
        month_txs = Transaction.objects.filter(user=user, date__range=(start_of_month, end_of_month), transaction_type='OUT')
        cat_expenses = month_txs.filter(category=category).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        total_expenses = month_txs.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        
        currency = user.profile.currency
        
        for b in budgets:
            limit = b.amount
            spent = total_expenses if b.category == 'Total' else cat_expenses
                
            if spent > limit:
                subject = f"BUDGET BREACH ALERT: {b.category} Budget Exceeded!"
                
                content_html = f"""
                <div style="background-color: #ef4444; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-weight: 600; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px;">
                    Target Category Breach Alert
                </div>
                <div style="background-color: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 12px;">
                    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #334155;">
                            <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Target Category</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">{b.category}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #334155;">
                            <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Monthly Limit</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">{currency}{limit:.2f}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #334155;">
                            <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Accumulated Total</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #f87171; font-weight: 600; text-align: right;">{currency}{spent:.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Threshold Overage</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #f87171; font-weight: 600; text-align: right;">{currency}{spent - limit:.2f}</td>
                        </tr>
                    </table>
                </div>
                <p style="font-size: 11px; color: #94a3b8; line-height: 1.5; margin-top: 12px; margin-bottom: 0;">
                    Your account has exceeded the designated category thresholds for the month of {d.strftime('%B %Y')}. We recommend reviewing your transactions to reduce your outflows.
                </p>
                """
                
                email_body = render_html_email(
                    title=f"Category '{b.category}' Exceeded Limit",
                    subtitle="Budget Breach Transmission",
                    content_html=content_html
                )
                try:
                    send_user_mail(user, subject, email_body, is_html=True)
                except Exception as mail_err:
                    print(f"Error sending budget alert mail: {mail_err}")
    except Exception as e:
        print(f"Error in check_and_send_budget_alerts: {e}")


def add_transaction(request):
    if request.method == 'POST':
        amount = request.POST.get('amount')
        tx_type = request.POST.get('transaction_type')
        category = request.POST.get('category')
        tx_date = request.POST.get('date') or date.today().strftime('%Y-%m-%d')
        description = request.POST.get('description', '')
        
        try:
            tx = Transaction.objects.create(
                user=request.user,
                amount=Decimal(amount),
                transaction_type=tx_type,
                category=category,
                date=tx_date,
                description=description
            )
            messages.success(request, "Transaction successfully added!")
            
            # Send budget alert emails if transaction is an Expense (OUT)
            if tx_type == 'OUT':
                check_and_send_budget_alerts(request.user, category, tx_date)
        except Exception as e:
            import traceback
            traceback.print_exc()
            messages.error(request, f"Error saving transaction: {e}")
            
    return redirect('dashboard')


@login_required
def delete_transaction(request, pk):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    tx.delete()
    messages.success(request, "Transaction successfully deleted!")
    return redirect('dashboard')


@login_required
def set_budget(request):
    if request.method == 'POST':
        category = request.POST.get('category')
        amount = request.POST.get('amount')
        
        today = date.today()
        try:
            budget, created = Budget.objects.update_or_create(
                user=request.user,
                category=category,
                period='MONTHLY',
                month=today.month,
                year=today.year,
                defaults={'amount': Decimal(amount)}
            )
            messages.success(request, f"Budget set for {category}!")
        except Exception as e:
            messages.error(request, f"Error setting budget: {e}")
            
    return redirect('dashboard')


@login_required
def add_reminder(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        amount = request.POST.get('amount')
        due_date = request.POST.get('due_date')
        is_recurring = request.POST.get('is_recurring') == 'on'
        recurrence_period = request.POST.get('recurrence_period') if is_recurring else None
        
        try:
            Reminder.objects.create(
                user=request.user,
                title=title,
                amount=Decimal(amount),
                due_date=due_date,
                is_recurring=is_recurring,
                recurrence_period=recurrence_period
            )
            messages.success(request, "Bill reminder successfully added!")
        except Exception as e:
            messages.error(request, f"Error adding reminder: {e}")
            
    return redirect('dashboard')


@login_required
def pay_reminder(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk, user=request.user)
    
    if reminder.is_recurring and reminder.recurrence_period:
        # Create a new reminder for the next period
        current_due = reminder.due_date
        next_due = current_due
        
        if reminder.recurrence_period == 'DAILY':
            next_due = current_due + timedelta(days=1)
        elif reminder.recurrence_period == 'WEEKLY':
            next_due = current_due + timedelta(weeks=1)
        elif reminder.recurrence_period == 'MONTHLY':
            # Add one month handling days overflow
            month = current_due.month
            year = current_due.year
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1
            _, last_day = calendar.monthrange(year, month)
            day = min(current_due.day, last_day)
            next_due = date(year, month, day)
        elif reminder.recurrence_period == 'YEARLY':
            # Add one year
            year = current_due.year + 1
            month = current_due.month
            _, last_day = calendar.monthrange(year, month)
            day = min(current_due.day, last_day)
            next_due = date(year, month, day)
            
        # Spawn next recurrence
        Reminder.objects.create(
            user=reminder.user,
            title=reminder.title,
            amount=reminder.amount,
            due_date=next_due,
            is_recurring=True,
            recurrence_period=reminder.recurrence_period,
            is_paid=False
        )
        
    reminder.is_paid = True
    reminder.save()
    messages.success(request, f"Marked '{reminder.title}' as Paid!")
    return redirect('dashboard')

# ----------------- Helper: Seed Demo Data -----------------

def seed_user_demo_data(user):
    """
    Seeds rich, colorful, realistic transaction, budget and reminder data
    so the user sees a beautiful, fully functional dashboard right away.
    """
    today = date.today()
    # Income Transactions
    Transaction.objects.create(user=user, amount=Decimal('4200.00'), transaction_type='IN', category='Salary', date=today - timedelta(days=5), description='Monthly Tech Lead Salary')
    Transaction.objects.create(user=user, amount=Decimal('850.00'), transaction_type='IN', category='Freelance', date=today - timedelta(days=12), description='Web Design Project Delivery')
    Transaction.objects.create(user=user, amount=Decimal('120.00'), transaction_type='IN', category='Investment', date=today - timedelta(days=15), description='Stock Dividends')

    # Expenses Current Month
    Transaction.objects.create(user=user, amount=Decimal('1500.00'), transaction_type='OUT', category='Rent', date=today - timedelta(days=8), description='Studio Apartment Rent')
    Transaction.objects.create(user=user, amount=Decimal('245.50'), transaction_type='OUT', category='Food', date=today - timedelta(days=1), description='Dinner & Drinks with Friends')
    Transaction.objects.create(user=user, amount=Decimal('85.00'), transaction_type='OUT', category='Food', date=today - timedelta(days=4), description='Weekly Groceries')
    Transaction.objects.create(user=user, amount=Decimal('115.00'), transaction_type='OUT', category='Utilities', date=today - timedelta(days=7), description='High-speed Fiber Internet & Power')
    Transaction.objects.create(user=user, amount=Decimal('120.00'), transaction_type='OUT', category='Entertainment', date=today - timedelta(days=3), description='Concert Tickets')
    Transaction.objects.create(user=user, amount=Decimal('65.00'), transaction_type='OUT', category='Travel', date=today - timedelta(days=2), description='Gas & Commute')
    Transaction.objects.create(user=user, amount=Decimal('45.00'), transaction_type='OUT', category='Other', date=today - timedelta(days=10), description='Tech Magazine Subscription')

    # Seed Last Month Transactions to make recommendations look incredibly smart
    last_month_first = date(today.year, today.month, 1) - timedelta(days=15)
    Transaction.objects.create(user=user, amount=Decimal('4200.00'), transaction_type='IN', category='Salary', date=last_month_first, description='Last Month Salary')
    Transaction.objects.create(user=user, amount=Decimal('1500.00'), transaction_type='OUT', category='Rent', date=last_month_first + timedelta(days=1), description='Studio Apartment Rent')
    Transaction.objects.create(user=user, amount=Decimal('180.00'), transaction_type='OUT', category='Food', date=last_month_first + timedelta(days=5), description='Last Month Food Total (lower)')
    Transaction.objects.create(user=user, amount=Decimal('60.00'), transaction_type='OUT', category='Entertainment', date=last_month_first + timedelta(days=10), description='Movie tickets')

    # Budgets for Current Month
    Budget.objects.create(user=user, category='Food', amount=Decimal('350.00'), period='MONTHLY', month=today.month, year=today.year)
    Budget.objects.create(user=user, category='Rent', amount=Decimal('1500.00'), period='MONTHLY', month=today.month, year=today.year)
    Budget.objects.create(user=user, category='Utilities', amount=Decimal('150.00'), period='MONTHLY', month=today.month, year=today.year)
    Budget.objects.create(user=user, category='Entertainment', amount=Decimal('100.00'), period='MONTHLY', month=today.month, year=today.year) # Will trigger warning (spent 120/100, danger)
    Budget.objects.create(user=user, category='Total', amount=Decimal('2800.00'), period='MONTHLY', month=today.month, year=today.year)

    # Reminders
    Reminder.objects.create(user=user, title='AWS Cloud Hosting', amount=Decimal('42.15'), due_date=today + timedelta(days=5), is_recurring=True, recurrence_period='MONTHLY')
    Reminder.objects.create(user=user, title='Gym Membership', amount=Decimal('60.00'), due_date=today + timedelta(days=11), is_recurring=True, recurrence_period='MONTHLY')
    Reminder.objects.create(user=user, title='Car Insurance', amount=Decimal('150.00'), due_date=today + timedelta(days=20), is_recurring=False)


# ----------------- Additional Action Views (Phase 2) -----------------

@login_required
def delete_budget_category(request, category):
    today = date.today()
    deleted_count, _ = Budget.objects.filter(
        user=request.user, 
        category=category, 
        year=today.year, 
        month=today.month
    ).delete()
    
    if deleted_count > 0:
        messages.success(request, f"Budget limit for {category} cleared successfully.")
    else:
        messages.info(request, f"No budget set for {category}.")
    return redirect('dashboard')


@login_required
def export_csv_view(request):
    import csv
    from django.http import HttpResponse
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="leoxur_financial_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['LEOXUR FINANCIAL TELEMETRY EXPORT'])
    writer.writerow(['User', request.user.username])
    writer.writerow(['Export Date', date.today().strftime('%Y-%m-%d')])
    writer.writerow([])
    
    writer.writerow(['--- TRANSACTIONS LEDGER ---'])
    writer.writerow(['ID', 'Description', 'Type', 'Category', 'Date', 'Amount'])
    txs = Transaction.objects.filter(user=request.user).order_by('-date')
    for tx in txs:
        writer.writerow([tx.id, tx.description, tx.get_transaction_type_display(), tx.category, tx.date.strftime('%Y-%m-%d'), tx.amount])
        
    writer.writerow([])
    writer.writerow(['--- MONTHLY BUDGET TARGETS ---'])
    writer.writerow(['Category', 'Allowance Amount', 'Month', 'Year'])
    budgets = Budget.objects.filter(user=request.user)
    for b in budgets:
        writer.writerow([b.category, b.amount, b.month, b.year])
        
    writer.writerow([])
    writer.writerow(['--- SCHEDULED BILL REMINDERS ---'])
    writer.writerow(['Title', 'Amount', 'Due Date', 'Is Recurring', 'Frequency', 'Status'])
    reminders = Reminder.objects.filter(user=request.user)
    for r in reminders:
        status = 'Paid' if r.is_paid else 'Pending'
        writer.writerow([r.title, r.amount, r.due_date.strftime('%Y-%m-%d'), r.is_recurring, r.get_recurrence_period_display() if r.is_recurring else 'N/A', status])
        
    return response


def generate_excel_data(user):
    from openpyxl import Workbook
    import io
    wb = Workbook()
    
    ws1 = wb.active
    ws1.title = "Transactions Ledger"
    ws1.append(['Transaction ID', 'Description', 'Type', 'Category', 'Date', 'Amount'])
    txs = Transaction.objects.filter(user=user).order_by('-date')
    for tx in txs:
        ws1.append([tx.id, tx.description, tx.get_transaction_type_display(), tx.category, tx.date.strftime('%Y-%m-%d'), float(tx.amount)])
        
    ws2 = wb.create_sheet(title="Budget Targets")
    ws2.append(['Category', 'Limit Amount', 'Month', 'Year'])
    budgets = Budget.objects.filter(user=user)
    for b in budgets:
        ws2.append([b.category, float(b.amount), b.month, b.year])
        
    ws3 = wb.create_sheet(title="Bill Reminders")
    ws3.append(['Title', 'Amount', 'Due Date', 'Is Recurring', 'Recurrence Frequency', 'Status'])
    reminders = Reminder.objects.filter(user=user)
    for r in reminders:
        status = 'Paid' if r.is_paid else 'Pending'
        ws3.append([r.title, float(r.amount), r.due_date.strftime('%Y-%m-%d'), "Yes" if r.is_recurring else "No", r.get_recurrence_period_display() if r.is_recurring else 'N/A', status])
        
    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    data = excel_buffer.getvalue()
    excel_buffer.close()
    return data


def generate_pdf_data(user, total_income, total_expense, balance, currency):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    import io
    
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    primary_color = colors.HexColor("#1d1d1f")
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        textColor=primary_color,
        spaceAfter=10
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        textColor=colors.gray,
        spaceAfter=20
    )
    
    h2_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        textColor=primary_color,
        spaceBefore=12,
        spaceAfter=8
    )
    
    story.append(Paragraph("LEOXUR FINANCIAL LEDGER", title_style))
    story.append(Paragraph(f"Monthly Telemetry Statement for node '{user.username}' | Date: {date.today().strftime('%B %d, %Y')}", subtitle_style))
    story.append(Spacer(1, 5))
    
    overview_data = [
        ["Telemetry Metric", "Value"],
        ["Total Earnings (Inflow)", f"{currency}{total_income:.2f}"],
        ["Total Spending (Outflow)", f"{currency}{total_expense:.2f}"],
        ["Current Monthly Balance", f"{currency}{balance:.2f}"]
    ]
    overview_table = Table(overview_data, colWidths=[200, 150])
    overview_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#f8fafc")),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    
    story.append(Paragraph("Monthly Overview Summary", h2_style))
    story.append(overview_table)
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("Recent Transactions Statement", h2_style))
    tx_headers = ["ID", "Description", "Type", "Category", "Date", "Amount"]
    tx_rows = [tx_headers]
    
    txs = Transaction.objects.filter(user=user).order_by('-date')[:30]
    for tx in txs:
        tx_rows.append([
            f"#{tx.id:05d}",
            tx.description or "N/A",
            tx.get_transaction_type_display(),
            tx.category,
            tx.date.strftime('%Y-%m-%d'),
            f"{'+' if tx.transaction_type == 'IN' else '-'}{currency}{tx.amount:.2f}"
        ])
        
    tx_table = Table(tx_rows, colWidths=[50, 150, 60, 90, 80, 70])
    tx_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(tx_table)
    
    doc.build(story)
    data = pdf_buffer.getvalue()
    pdf_buffer.close()
    return data


def render_html_email(title, subtitle, content_html):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                margin: 0;
                padding: 4px;
                background-color: #0d1527;
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 4px; background-color: #0d1527; color: #f8fafc;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #0d1527; padding: 10px 0;">
            <tr>
                <td align="center" valign="top">
                    <table width="100%" max-width="500" style="width: 100%; max-width: 500px; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 12px; border-collapse: separate; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.3);" cellspacing="0" cellpadding="0">
                        <!-- Header -->
                        <tr>
                            <td style="padding: 12px 16px; border-bottom: 1px solid #1e293b; background-color: #090e1a;">
                                <table width="100%" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td>
                                            <h2 style="margin: 0; font-size: 11px; font-weight: 700; color: #38bdf8; letter-spacing: 1px; font-family: -apple-system, sans-serif; text-transform: uppercase;">LEOXUR TELEMETRY</h2>
                                            <div style="font-size: 8px; color: #64748b; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px;">{subtitle}</div>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <!-- Content -->
                        <tr>
                            <td style="padding: 16px;">
                                <h1 style="margin: 0 0 12px 0; font-size: 15px; font-weight: 600; color: #ffffff; letter-spacing: -0.3px;">{title}</h1>
                                {content_html}
                            </td>
                        </tr>
                        <!-- Footer -->
                        <tr>
                            <td style="padding: 10px 16px; background-color: #090e1a; border-top: 1px solid #1e293b; text-align: center; font-size: 8px; color: #64748b;">
                                Automated transmission. Settings and UI are synchronized.
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def render_compact_transaction_email(category_name, amount, tx_type_str, date_str, description, currency, tx_type):
    flow_color = '#10b981' if tx_type == 'IN' else '#ef4444'
    flow_label = 'INCOME' if tx_type == 'IN' else 'EXPENSE'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: #0d1527;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 10px; background-color: #0d1527;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #0d1527;">
            <tr>
                <td align="center" valign="top">
                    <table width="100%" max-width="440" style="width: 100%; max-width: 440px; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.3); border-collapse: separate;" cellspacing="0" cellpadding="0">
                        <!-- Banner Header -->
                        <tr>
                            <td style="background-color: {flow_color}; color: #ffffff; padding: 6px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; text-align: center;">
                                Transaction Processed: {flow_label}
                            </td>
                        </tr>
                        <!-- Details Table -->
                        <tr>
                            <td style="padding: 12px;">
                                <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                                    <tr>
                                        <td style="font-size: 8px; text-transform: uppercase; color: #94a3b8; padding-bottom: 2px;">Category</td>
                                        <td style="font-size: 8px; text-transform: uppercase; color: #94a3b8; padding-bottom: 2px; text-align: center;">Amount</td>
                                        <td style="font-size: 8px; text-transform: uppercase; color: #94a3b8; padding-bottom: 2px; text-align: right;">Date</td>
                                    </tr>
                                    <tr>
                                        <td style="font-size: 11px; color: #ffffff; font-weight: 600; padding-right: 8px;">{category_name}</td>
                                        <td style="font-size: 11px; color: #ffffff; font-weight: 600; text-align: center; padding-right: 8px;">{currency}{amount:.2f}</td>
                                        <td style="font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">{date_str}</td>
                                    </tr>
                                </table>
                                <div style="margin-top: 8px; border-top: 1px solid #1e293b; padding-top: 6px; font-size: 10px; color: #94a3b8;">
                                    <strong>Note:</strong> {description or 'N/A'}
                                </div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def send_user_mail(user, subject, body, attachments=None, is_html=False):
    from django.core.mail import get_connection, EmailMultiAlternatives
    import re
    profile = user.profile
    if profile.smtp_host and profile.smtp_user and profile.smtp_password:
        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=profile.smtp_host,
            port=profile.smtp_port,
            username=profile.smtp_user,
            password=profile.smtp_password,
            use_tls=True,
        )
        from_email = f"Leoxur Financial <{profile.smtp_user}>"
    else:
        connection = None
        from_email = None

    if is_html:
        plain_text = re.sub(r'<[^>]+>', '', body)
    else:
        plain_text = body

    email = EmailMultiAlternatives(
        subject=subject,
        body=plain_text,
        from_email=from_email,
        to=[user.email],
        connection=connection
    )
    email.extra_headers['X-Leoxur-Auto'] = 'True'
    email.extra_headers['Auto-Submitted'] = 'auto-generated'
    if is_html:
        email.attach_alternative(body, "text/html")
        
    if attachments:
        for name, content, mimetype in attachments:
            email.attach(name, content, mimetype)
    email.send()


@login_required
def update_email_settings(request):
    if request.method == 'POST':
        profile = request.user.profile
        profile.smtp_host = request.POST.get('smtp_host', 'smtp.gmail.com')
        profile.smtp_port = int(request.POST.get('smtp_port', '587'))
        profile.smtp_user = request.POST.get('smtp_user', '')
        profile.smtp_password = request.POST.get('smtp_password', '')
        profile.imap_host = request.POST.get('imap_host', 'imap.gmail.com')
        profile.imap_port = int(request.POST.get('imap_port', '993'))
        profile.imap_user = request.POST.get('imap_user', '')
        profile.imap_password = request.POST.get('imap_password', '')
        profile.auto_fetch_emails = request.POST.get('auto_fetch_emails') == 'on'
        profile.save()
        messages.success(request, "Email SMTP/IMAP settings updated successfully!")
    return redirect('dashboard')


@login_required
def test_email_report(request):
    user = request.user
    if not user.email:
        messages.error(request, "Please register an email address on your user profile before running tests.")
        return redirect('dashboard')
        
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

    budgets = Budget.objects.filter(user=user, year=today.year, month=today.month)
    
    expense_pct = int((total_expense / total_income * 100)) if total_income > 0 else 0
    if expense_pct > 100: expense_pct = 100

    balances_html = f"""
    <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 12px; border-spacing: 8px; border-collapse: separate; margin-left: -8px; margin-right: -8px;">
        <tr>
            <td width="50%" style="background-color: #1e293b; padding: 10px; border-radius: 8px; border: 1px solid #334155;">
                <div style="font-size: 9px; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.5px; font-weight: 600;">Total Earnings</div>
                <div style="font-size: 18px; font-weight: 700; color: #4ade80; margin-top: 4px;">{currency}{total_income:.2f}</div>
            </td>
            <td width="50%" style="background-color: #1e293b; padding: 10px; border-radius: 8px; border: 1px solid #334155;">
                <div style="font-size: 9px; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.5px; font-weight: 600;">Total Spending</div>
                <div style="font-size: 18px; font-weight: 700; color: #f87171; margin-top: 4px;">{currency}{total_expense:.2f}</div>
            </td>
        </tr>
    </table>
    
    <div style="background-color: #1e293b; padding: 10px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 9px; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.5px; font-weight: 600;">
            <span>Net Monthly Balance</span>
            <span style="font-size: 15px; font-weight: 700; color: {'#38bdf8' if balance >= 0 else '#f87171'};">{currency}{balance:.2f}</span>
        </div>
        <div style="margin-top: 8px; background-color: #0f172a; border-radius: 9999px; height: 5px; overflow: hidden; width: 100%;">
            <div style="background-color: #38bdf8; height: 100%; width: {expense_pct}%; border-radius: 9999px;"></div>
        </div>
        <div style="font-size: 8px; color: #64748b; margin-top: 4px; text-align: right;">Spending ratio: {expense_pct}%</div>
    </div>
    """

    budget_lines = []
    for b in budgets:
        spent = total_expense if b.category == 'Total' else month_txs.filter(category=b.category, transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        pct = int((spent / b.amount * 100)) if b.amount > 0 else 0
        fill_pct = pct if pct <= 100 else 100
        bar_color = "#f87171" if pct >= 100 else "#38bdf8"
        budget_lines.append(f"""
        <div style="margin-bottom: 8px;">
            <div style="font-size: 10px; margin-bottom: 2px; color: #ffffff;">
                <span style="font-weight: 600;">{b.category}</span>
                <span style="color: #94a3b8; float: right;">{currency}{spent:.2f} / {currency}{b.amount:.2f} ({pct}%)</span>
            </div>
            <div style="background-color: #0f172a; border-radius: 9999px; height: 4px; overflow: hidden; width: 100%; border: 1px solid #1e293b;">
                <div style="background-color: {bar_color}; height: 100%; width: {fill_pct}%; border-radius: 9999px;"></div>
            </div>
        </div>
        """)
        
    budgets_html = f"""
    <div style="margin-bottom: 16px;">
        <h3 style="font-size: 10px; text-transform: uppercase; color: #38bdf8; letter-spacing: 0.5px; margin-bottom: 8px; border-bottom: 1px solid #1e293b; padding-bottom: 4px; font-weight: 700;">Budget Limits</h3>
        {"".join(budget_lines) if budget_lines else '<div style="font-size: 9px; color: #64748b;">No active budget targets.</div>'}
    </div>
    """

    recent_rows = []
    txs = Transaction.objects.filter(user=user).order_by('-date')[:5]
    for tx in txs:
        amt_color = "#4ade80" if tx.transaction_type == 'IN' else "#f87171"
        amt_sign = "+" if tx.transaction_type == 'IN' else "-"
        recent_rows.append(f"""
        <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 6px 0; font-size: 10px; color: #e2e8f0;">{tx.description or 'N/A'}</td>
            <td style="padding: 6px 0; font-size: 10px; color: #94a3b8;">{tx.category}</td>
            <td style="padding: 6px 0; font-size: 10px; text-align: right; font-weight: 600; color: {amt_color};">{amt_sign}{currency}{tx.amount:.2f}</td>
        </tr>
        """)
        
    recent_html = f"""
    <div style="margin-bottom: 8px;">
        <h3 style="font-size: 10px; text-transform: uppercase; color: #38bdf8; letter-spacing: 0.5px; margin-bottom: 8px; border-bottom: 1px solid #1e293b; padding-bottom: 4px; font-weight: 700;">Recent Statements</h3>
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
            <thead>
                <tr style="text-align: left; border-bottom: 1px solid #334155;">
                    <th style="padding-bottom: 4px; font-size: 9px; text-transform: uppercase; color: #64748b; font-weight: 600;">Description</th>
                    <th style="padding-bottom: 4px; font-size: 9px; text-transform: uppercase; color: #64748b; font-weight: 600;">Category</th>
                    <th style="padding-bottom: 4px; font-size: 9px; text-transform: uppercase; color: #64748b; text-align: right; font-weight: 600;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {"".join(recent_rows) if recent_rows else '<tr><td colspan="3" style="padding: 8px 0; font-size: 10px; color: #64748b; text-align: center;">No transactions found.</td></tr>'}
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

    try:
        excel_data = generate_excel_data(user)
        pdf_data = generate_pdf_data(user, total_income, total_expense, balance, currency)
        
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
        messages.success(request, f"Test Daily Report email successfully sent to {user.email}!")
    except Exception as e:
        messages.error(request, f"Error sending test report email: {e}")
    return redirect('dashboard')


@login_required
def test_email_alert(request):
    user = request.user
    if not user.email:
        messages.error(request, "Please register an email address on your user profile before running tests.")
        return redirect('dashboard')
        
    currency = user.profile.currency
    
    subject = "BUDGET BREACH ALERT: Entertainment Budget Exceeded"
    
    content_html = f"""
    <div style="background-color: #ef4444; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-weight: 600; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px;">
        Target Category Breach Alert
    </div>
    <div style="background-color: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 12px;">
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Target Category</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">Entertainment</td>
            </tr>
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Monthly Limit</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">{currency}250.00</td>
            </tr>
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Accumulated Total</td>
                <td style="padding: 8px 0; font-size: 11px; color: #f87171; font-weight: 600; text-align: right;">{currency}320.00</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Threshold Overage</td>
                <td style="padding: 8px 0; font-size: 11px; color: #f87171; font-weight: 600; text-align: right;">{currency}70.00</td>
            </tr>
        </table>
    </div>
    <p style="font-size: 11px; color: #94a3b8; line-height: 1.5; margin-top: 12px; margin-bottom: 0;">
        Your account has exceeded the designated category thresholds for the month of {date.today().strftime('%B %Y')}. We recommend reviewing your transactions to reduce your outflows.
    </p>
    """
    
    email_body = render_html_email(
        title="Category 'Entertainment' Exceeded Limit",
        subtitle="Budget Breach Transmission",
        content_html=content_html
    )
    
    try:
        send_user_mail(user, subject, email_body, is_html=True)
        messages.success(request, f"Test Budget Alert email successfully sent to {user.email}!")
    except Exception as e:
        messages.error(request, f"Error sending test alert email: {e}")
    return redirect('dashboard')


@login_required
def test_email_reminder(request):
    user = request.user
    if not user.email:
        messages.error(request, "Please register an email address on your user profile before running tests.")
        return redirect('dashboard')
        
    currency = user.profile.currency
    
    subject = "BILL DUE TODAY: Internet & Broadband subscription"
    
    content_html = f"""
    <div style="background-color: #3b82f6; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-weight: 600; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px;">
        Scheduled Payment Due Today
    </div>
    <div style="background-color: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 12px;">
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Bill Description</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">Internet & Broadband subscription</td>
            </tr>
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Amount Due</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">{currency}79.99</td>
            </tr>
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Due Date</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">{date.today().strftime('%A, %b %d, %Y')}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; font-size: 11px; color: #94a3b8;">Recurrence</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ffffff; font-weight: 600; text-align: right;">Yes (Monthly)</td>
            </tr>
        </table>
    </div>
    <p style="font-size: 11px; color: #94a3b8; line-height: 1.5; margin-top: 12px; margin-bottom: 0;">
        This automated transmission has been dispatched to remind you that your scheduled payment is due today. Please log in to your dashboard to pay the reminder and update your records.
    </p>
    """
    
    email_body = render_html_email(
        title="Internet & Broadband Subscription Payment Due",
        subtitle="Scheduled Reminder Transmission",
        content_html=content_html
    )
    
    try:
        send_user_mail(user, subject, email_body, is_html=True)
        messages.success(request, f"Test Bill Reminder email successfully sent to {user.email}!")
    except Exception as e:
        messages.error(request, f"Error sending test bill reminder email: {e}")
    return redirect('dashboard')


@login_required
def export_excel_view(request):
    from django.http import HttpResponse
    try:
        data = generate_excel_data(request.user)
        response = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="leoxur_financial_export.xlsx"'
        return response
    except Exception as e:
        messages.error(request, f"Error generating Excel statement: {e}")
        return redirect('dashboard')


@login_required
def export_pdf_view(request):
    from django.http import HttpResponse
    try:
        today = date.today()
        start_of_month = date(today.year, today.month, 1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_of_month = date(today.year, today.month, last_day)
        
        month_txs = Transaction.objects.filter(user=request.user, date__range=(start_of_month, end_of_month))
        total_income = month_txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        total_expense = month_txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        balance = total_income - total_expense
        raw_currency = request.user.profile.currency
        currency_map = {
            '$': '$',
            '€': 'EUR ',
            '₹': 'INR ',
            '£': 'GBP ',
        }
        currency = currency_map.get(raw_currency, raw_currency + ' ')
        
        data = generate_pdf_data(request.user, total_income, total_expense, balance, currency)
        response = HttpResponse(data, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="leoxur_financial_statement.pdf"'
        return response
    except Exception as e:
        messages.error(request, f"Error generating PDF statement: {e}")
        return redirect('dashboard')


# ----------------- Custom Category & modifiers (Phase 3) -----------------

@login_required
def add_category(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        is_income = request.POST.get('is_income') == 'on' or request.POST.get('is_income') == 'True'
        
        if name:
            try:
                # Restrict to unique per user
                category, created = Category.objects.get_or_create(user=request.user, name=name, is_income=is_income)
                if created:
                    messages.success(request, f"Custom category '{name}' created successfully!")
                else:
                    messages.info(request, f"Category '{name}' already exists.")
            except Exception as e:
                messages.error(request, f"Error creating category: {e}")
        else:
            messages.error(request, "Category name cannot be empty.")
    return redirect('dashboard')


@login_required
def edit_transaction(request, pk):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    if request.method == 'POST':
        amount = request.POST.get('amount')
        tx_type = request.POST.get('transaction_type')
        category = request.POST.get('category')
        tx_date = request.POST.get('date')
        description = request.POST.get('description', '')
        
        try:
            tx.amount = Decimal(amount)
            tx.transaction_type = tx_type
            tx.category = category
            tx.date = tx_date
            tx.description = description
            tx.save()
            messages.success(request, "Transaction updated successfully!")
            
            # Send budget alert emails if transaction is an Expense (OUT)
            if tx_type == 'OUT':
                check_and_send_budget_alerts(request.user, category, tx_date)
        except Exception as e:
            import traceback
            traceback.print_exc()
            messages.error(request, f"Error updating transaction: {e}")
    return redirect('dashboard')


@login_required
def delete_transaction_bulk(request):
    if request.method == 'POST':
        tx_ids_str = request.POST.get('transaction_ids', '')
        if tx_ids_str:
            try:
                id_list = [int(x) for x in tx_ids_str.split(',') if x.strip()]
                deleted_count, _ = Transaction.objects.filter(user=request.user, id__in=id_list).delete()
                messages.success(request, f"Deleted {deleted_count} selected transaction(s).")
            except Exception as e:
                messages.error(request, f"Error bulk deleting: {e}")
        else:
            messages.warning(request, "No transactions selected for deletion.")
    return redirect('dashboard')


@login_required
def edit_reminder(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk, user=request.user)
    if request.method == 'POST':
        title = request.POST.get('title')
        amount = request.POST.get('amount')
        due_date = request.POST.get('due_date')
        is_recurring = request.POST.get('is_recurring') == 'on'
        recurrence_period = request.POST.get('recurrence_period') if is_recurring else None
        
        try:
            reminder.title = title
            reminder.amount = Decimal(amount)
            reminder.due_date = due_date
            reminder.is_recurring = is_recurring
            reminder.recurrence_period = recurrence_period
            reminder.save()
            messages.success(request, f"Bill reminder '{title}' updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating reminder: {e}")
    return redirect('dashboard')


@login_required
def delete_reminder(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk, user=request.user)
    title = reminder.title
    reminder.delete()
    messages.success(request, f"Bill reminder '{title}' deleted successfully.")
    return redirect('dashboard')


@login_required
def sync_emails_now(request):
    from django.core.management import call_command
    try:
        call_command('fetch_emails')
        messages.success(request, "Email inbox sync completed successfully!")
    except Exception as e:
        messages.error(request, f"Error synchronizing emails: {e}")
    return redirect('dashboard')


@login_required
def download_template(request):
    from openpyxl import Workbook
    from django.http import HttpResponse
    
    wb = Workbook()
    
    # 1. Setup Transactions Sheet
    ws_tx = wb.active
    ws_tx.title = "Transactions"
    ws_tx.append(["Date (YYYY-MM-DD)", "Amount", "Type (IN/OUT)", "Category", "Description"])
    ws_tx.append(["2026-07-10", 1500.00, "OUT", "Utilities", "Electricity Bill"])
    ws_tx.append(["2026-07-11", 75000.00, "IN", "Salary", "Monthly Salary payment"])
    ws_tx.append(["2026-07-12", 450.50, "OUT", "Food", "Lunch"])
    
    # Adjust column dimensions
    for col in ws_tx.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = col[0].column_letter
        ws_tx.column_dimensions[col_letter].width = max(max_len + 3, 12)
        
    # 2. Setup Instructions Sheet
    ws_instr = wb.create_sheet(title="Instructions")
    ws_instr.append(["Field Name", "Requirement", "Allowed Values / Examples"])
    ws_instr.append(["Date (YYYY-MM-DD)", "Required date format.", "YYYY-MM-DD (e.g., 2026-07-12)"])
    ws_instr.append(["Amount", "Required positive numeric value.", "Any decimal greater than 0 (e.g., 1250.50)"])
    ws_instr.append(["Type (IN/OUT)", "Transaction direction.", "IN (for Incomes) or OUT (for Expenses)"])
    ws_instr.append(["Category", "The budget category name.", "e.g., Salary, Food, Utilities. If the category does not exist, it will be automatically created for your profile."])
    ws_instr.append(["Description", "Optional narrative detail.", "e.g., Rent payment, Weekly groceries"])
    
    for col in ws_instr.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = col[0].column_letter
        ws_instr.column_dimensions[col_letter].width = max(max_len + 3, 15)
        
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="leoxur_import_template.xlsx"'
    wb.save(response)
    return response


@login_required
def import_transactions(request):
    import csv
    from datetime import datetime, date
    from decimal import Decimal
    from openpyxl import load_workbook
    
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        filename = file.name
        
        success_count = 0
        error_rows = []
        
        try:
            if filename.endswith('.csv'):
                decoded_file = file.read().decode('utf-8').splitlines()
                reader = csv.reader(decoded_file)
                # Skip header
                header = next(reader, None)
                rows = list(reader)
                
                for idx, row in enumerate(rows, start=2):
                    if not row or all(not str(val).strip() for val in row):
                        continue
                    if len(row) < 4:
                        error_rows.append(f"Row {idx}: Missing columns.")
                        continue
                        
                    date_val, amount_val, type_val, category_val = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
                    desc_val = row[4].strip() if len(row) > 4 else ""
                    
                    try:
                        date_parsed = datetime.strptime(date_val, '%Y-%m-%d').date()
                    except Exception:
                        error_rows.append(f"Row {idx}: Invalid date format. Use YYYY-MM-DD.")
                        continue
                        
                    try:
                        amount = Decimal(amount_val)
                        if amount <= 0:
                            raise ValueError()
                    except Exception:
                        error_rows.append(f"Row {idx}: Invalid amount. Must be positive number.")
                        continue
                        
                    tx_type = type_val.upper()
                    if tx_type not in ['IN', 'OUT']:
                        error_rows.append(f"Row {idx}: Invalid type. Use IN or OUT.")
                        continue
                        
                    category_name = category_val
                    if not category_name:
                        error_rows.append(f"Row {idx}: Category cannot be empty.")
                        continue
                        
                    # Auto-create category
                    is_income = (tx_type == 'IN')
                    Category.objects.get_or_create(user=request.user, name=category_name, is_income=is_income)
                    
                    Transaction.objects.create(
                        user=request.user,
                        amount=amount,
                        transaction_type=tx_type,
                        category=category_name,
                        date=date_parsed,
                        description=desc_val
                    )
                    success_count += 1
                    
            elif filename.endswith('.xlsx'):
                wb = load_workbook(file, read_only=True)
                if "Transactions" not in wb.sheetnames:
                    messages.error(request, "Invalid template: Sheet named 'Transactions' was not found.")
                    return redirect('dashboard')
                    
                ws = wb["Transactions"]
                rows = list(ws.iter_rows(values_only=True))
                if not rows or len(rows) <= 1:
                    messages.warning(request, "No transaction data found in the spreadsheet.")
                    return redirect('dashboard')
                    
                # Skip header
                data_rows = rows[1:]
                
                for idx, row in enumerate(data_rows, start=2):
                    if not row or all(val is None for val in row):
                        continue
                    if len(row) < 4:
                        error_rows.append(f"Row {idx}: Missing columns.")
                        continue
                        
                    date_val, amount_val, type_val, category_val = row[0], row[1], row[2], row[3]
                    desc_val = row[4] if len(row) > 4 else ""
                    
                    if isinstance(date_val, datetime):
                        date_parsed = date_val.date()
                    elif isinstance(date_val, date):
                        date_parsed = date_val
                    else:
                        try:
                            date_parsed = datetime.strptime(str(date_val).strip(), '%Y-%m-%d').date()
                        except Exception:
                            error_rows.append(f"Row {idx}: Invalid date format. Use YYYY-MM-DD.")
                            continue
                            
                    try:
                        amount = Decimal(str(amount_val).strip())
                        if amount <= 0:
                            raise ValueError()
                    except Exception:
                        error_rows.append(f"Row {idx}: Invalid amount. Must be positive number.")
                        continue
                        
                    tx_type = str(type_val).strip().upper()
                    if tx_type not in ['IN', 'OUT']:
                        error_rows.append(f"Row {idx}: Invalid type. Use IN or OUT.")
                        continue
                        
                    category_name = str(category_val).strip()
                    if not category_name:
                        error_rows.append(f"Row {idx}: Category cannot be empty.")
                        continue
                        
                    is_income = (tx_type == 'IN')
                    Category.objects.get_or_create(user=request.user, name=category_name, is_income=is_income)
                    
                    Transaction.objects.create(
                        user=request.user,
                        amount=amount,
                        transaction_type=tx_type,
                        category=category_name,
                        date=date_parsed,
                        description=str(desc_val).strip() if desc_val else ""
                    )
                    success_count += 1
            else:
                messages.error(request, "Unsupported file format. Please upload a .csv or .xlsx file.")
                return redirect('dashboard')
                
        except Exception as e:
            messages.error(request, f"Error reading file: {e}")
            return redirect('dashboard')
            
        if error_rows:
            err_msg = " | ".join(error_rows[:5])
            if len(error_rows) > 5:
                err_msg += f" ...and {len(error_rows) - 5} more errors."
            messages.warning(request, f"Imported {success_count} transactions. Ignored rows: {err_msg}")
        else:
            messages.success(request, f"Successfully imported {success_count} transactions!")
            
    else:
        messages.error(request, "No file uploaded.")
        
    return redirect('dashboard')
