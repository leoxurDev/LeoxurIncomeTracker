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
    real_today = date.today()
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
    
    # ----------------- Multi-Month & Multi-Year Navigation -----------------
    try:
        selected_year = int(request.GET.get('year', real_today.year))
        selected_month = int(request.GET.get('month', real_today.month))
        if selected_month < 1 or selected_month > 12:
            selected_month = real_today.month
        if selected_year < 1970 or selected_year > 2099:
            selected_year = real_today.year
    except (ValueError, TypeError):
        selected_year = real_today.year
        selected_month = real_today.month

    # Date bounds for the selected month
    start_of_month = date(selected_year, selected_month, 1)
    _, last_day = calendar.monthrange(selected_year, selected_month)
    end_of_month = date(selected_year, selected_month, last_day)

    # Previous and Next Month calculations
    if selected_month == 1:
        prev_month, prev_year = 12, selected_year - 1
    else:
        prev_month, prev_year = selected_month - 1, selected_year

    if selected_month == 12:
        next_month, next_year = 1, selected_year + 1
    else:
        next_month, next_year = selected_month + 1, selected_year

    is_current_month = (selected_year == real_today.year and selected_month == real_today.month)
    selected_month_name = calendar.month_name[selected_month]
    selected_month_abbr = calendar.month_abbr[selected_month]
    selected_cycle_label = f"{selected_month_name} {selected_year}"

    # Transactions for selected month
    month_txs = Transaction.objects.filter(user=user, date__range=(start_of_month, end_of_month))
    
    # Financial Aggregations for selected month
    month_inflow_txs = month_txs.filter(transaction_type='IN')
    month_outflow_txs = month_txs.filter(transaction_type='OUT')
    
    total_income = month_inflow_txs.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    total_expense = month_outflow_txs.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    balance = total_income - total_expense
    
    month_inflow_count = month_inflow_txs.count()
    month_outflow_count = month_outflow_txs.count()
    net_margin_pct = int(round((balance / total_income * 100))) if total_income > 0 else 0

    # Largest Inflow & Outflow sources
    primary_inflow_obj = month_inflow_txs.values('category').annotate(c_sum=Sum('amount')).order_by('-c_sum').first()
    primary_inflow_name = primary_inflow_obj['category'] if primary_inflow_obj else "Direct Deposit"
    primary_inflow_amount = primary_inflow_obj['c_sum'] if primary_inflow_obj else Decimal('0.00')

    top_outflow_obj = month_outflow_txs.values('category').annotate(c_sum=Sum('amount')).order_by('-c_sum').first()
    top_outflow_name = top_outflow_obj['category'] if top_outflow_obj else "General"
    top_outflow_amount = top_outflow_obj['c_sum'] if top_outflow_obj else Decimal('0.00')
    top_outflow_pct = int(round((top_outflow_amount / total_expense * 100))) if total_expense > 0 else 0

    # Category Expenses for selected month
    cat_expenses = {}
    for tx in month_outflow_txs:
        cat_expenses[tx.category] = cat_expenses.get(tx.category, Decimal('0.00')) + tx.amount

    # Budget Progress Calculations for selected month
    budgets = Budget.objects.filter(user=user, year=selected_year, month=selected_month)
    
    # Fallback to general category budgets if specific month has no budgets
    fallback_budgets = {}
    if not budgets.exists():
        for b in Budget.objects.filter(user=user).order_by('-year', '-month'):
            if b.category not in fallback_budgets:
                fallback_budgets[b.category] = b.amount

    budget_data = []
    alerts = []
    
    for category in expense_categories:
        budget_obj = budgets.filter(category=category).first()
        if budget_obj:
            budget_amount = budget_obj.amount
        else:
            budget_amount = fallback_budgets.get(category, Decimal('0.00'))

        spent = cat_expenses.get(category, Decimal('0.00'))
        
        pct = 0
        if budget_amount > 0:
            pct = int((spent / budget_amount) * 100)
            if pct >= 100:
                alerts.append({
                    'type': 'danger',
                    'message': f"CRITICAL: Monthly budget exceeded for {category}! Spent: {profile.currency}{spent:,.2f} / Limit: {profile.currency}{budget_amount:,.2f} ({pct}%)"
                })
            elif pct >= 80:
                alerts.append({
                    'type': 'warning',
                    'message': f"WARNING: Reached {pct}% of monthly budget for {category}. Remaining: {profile.currency}{budget_amount - spent:,.2f}"
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
    if overall_budget_obj:
        overall_budget = overall_budget_obj.amount
    else:
        overall_budget = fallback_budgets.get('Total', Decimal('0.00'))

    overall_pct = 0
    if overall_budget > 0:
        overall_pct = int((total_expense / overall_budget) * 100)
        if overall_pct >= 100:
            alerts.append({
                'type': 'danger',
                'message': f"CRITICAL: Total disbursements have breached overall monthly budget! Spent: {profile.currency}{total_expense:,.2f} / Limit: {profile.currency}{overall_budget:,.2f} ({overall_pct}%)"
            })
        elif overall_pct >= 80:
            alerts.append({
                'type': 'warning',
                'message': f"WARNING: Total disbursements at {overall_pct}% of budget cap. Remaining: {profile.currency}{overall_budget - total_expense:,.2f}"
            })

    # Rich AI Financial Intelligence & Telemetry Hub
    ai_telemetry = generate_ai_telemetry(user, cat_expenses, total_income, total_expense, selected_month, selected_year, profile, overall_budget)
    recommendations = [item['message'] for item in ai_telemetry['insights']]

    # Reminders
    reminders = Reminder.objects.filter(user=user, is_paid=False)
    upcoming_reminders = reminders.filter(due_date__gte=real_today)
    overdue_reminders = reminders.filter(due_date__lt=real_today)
    
    # Financial Activity Ledger: show transactions for the selected cycle
    month_transactions = month_txs.order_by('-date', '-created_at')
    recent_transactions = month_transactions if month_transactions.exists() else Transaction.objects.filter(user=user).order_by('-date', '-created_at')[:100]

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
        b_val = b_obj.amount if b_obj else fallback_budgets.get(category, Decimal('0.00'))
        if b_val > 0:
            spent = cat_expenses.get(category, Decimal('0.00'))
            if spent > b_val:
                breached_count += 1
    health_score -= min(breached_count * 15, 35)

    overdue_count = overdue_reminders.count()
    health_score -= min(overdue_count * 10, 30)
    health_score = max(10, health_score)
    health_offset = float(175.9 * (1.0 - health_score / 100.0))

    # Available years list for dropdown
    tx_years = set(Transaction.objects.filter(user=user).dates('date', 'year').values_list('date__year', flat=True))
    tx_years.add(real_today.year)
    tx_years.add(selected_year)
    available_years = sorted(list(tx_years), reverse=True)
    if len(available_years) < 3:
        available_years = sorted(list(set(available_years + [real_today.year - 1, real_today.year, real_today.year + 1])), reverse=True)

    months_list = [
        {'num': m, 'name': calendar.month_name[m], 'abbr': calendar.month_abbr[m]}
        for m in range(1, 13)
    ]

    context = {
        'profile': profile,
        'total_income': total_income,
        'total_expense': total_expense,
        'balance': balance,
        'net_margin_pct': net_margin_pct,
        'month_inflow_count': month_inflow_count,
        'month_outflow_count': month_outflow_count,
        'primary_inflow_name': primary_inflow_name,
        'primary_inflow_amount': primary_inflow_amount,
        'top_outflow_name': top_outflow_name,
        'top_outflow_amount': top_outflow_amount,
        'top_outflow_pct': top_outflow_pct,
        'daily_avg_outflow': ai_telemetry['burn_rate']['daily_burn'],
        'days_remaining_in_month': ai_telemetry['burn_rate']['days_remaining'],
        'budget_data': budget_data,
        'overall_budget': overall_budget,
        'overall_percentage': min(overall_pct, 100) if overall_budget > 0 else 0,
        'overall_raw_percentage': overall_pct,
        'overall_remaining': overall_budget - total_expense,
        'alerts': alerts,
        'recommendations': recommendations,
        'ai_telemetry': ai_telemetry,
        'upcoming_reminders': upcoming_reminders,
        'overdue_reminders': overdue_reminders,
        'recent_transactions': recent_transactions,
        'user_income_cats': user_income_cats,
        'user_expense_cats': user_expense_cats,
        'expense_categories': expense_categories,
        'today': real_today,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'selected_month_name': selected_month_name,
        'selected_month_abbr': selected_month_abbr,
        'selected_cycle_label': selected_cycle_label,
        'is_current_month': is_current_month,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'available_years': available_years,
        'months_list': months_list,
        'health_score': health_score,
        'health_offset': health_offset,
    }
    return render(request, 'tracker/dashboard.html', context)


def generate_ai_telemetry(user, current_expenses, current_income, total_expense, selected_month, selected_year, profile, overall_budget=None):
    """
    Computes rich, multi-dimensional financial intelligence:
    - 50/30/20 Rule breakdown (Needs, Wants, Savings)
    - Burn Rate & Safe Daily Allowance velocity
    - Category Surges and Anomalies vs Previous Month
    - Targeted Dollar Savings Potential
    - Executive Anomaly Insights & Actionable Copilot Prompts
    """
    currency = profile.currency if profile else '$'
    real_today = date.today()
    days_in_month = calendar.monthrange(selected_year, selected_month)[1]
    
    # Days elapsed & remaining
    if selected_year == real_today.year and selected_month == real_today.month:
        days_elapsed = max(1, real_today.day)
        days_remaining = max(0, days_in_month - real_today.day)
    else:
        days_elapsed = days_in_month
        days_remaining = 0

    daily_burn = (total_expense / Decimal(str(days_elapsed))) if days_elapsed > 0 else Decimal('0.00')
    projected_spend = daily_burn * Decimal(str(days_in_month))
    
    safe_daily_allowance = Decimal('0.00')
    if overall_budget and overall_budget > total_expense and days_remaining > 0:
        safe_daily_allowance = (overall_budget - total_expense) / Decimal(str(days_remaining))

    # 1. 50/30/20 Rule Analysis
    needs_cats = {'Rent', 'Food', 'Utilities', 'Groceries', 'Mortgage', 'Bills', 'Healthcare', 'Health', 'Insurance'}
    needs_amt = Decimal('0.00')
    wants_amt = Decimal('0.00')
    
    for cat, amt in current_expenses.items():
        if cat in needs_cats or any(k in cat.lower() for k in ['rent', 'food', 'grocer', 'utilit', 'bill']):
            needs_amt += amt
        else:
            wants_amt += amt

    savings_surplus = max(Decimal('0.00'), current_income - total_expense)

    needs_pct = int(round((needs_amt / current_income) * 100)) if current_income > 0 else 0
    wants_pct = int(round((wants_amt / current_income) * 100)) if current_income > 0 else 0
    savings_pct = int(round((savings_surplus / current_income) * 100)) if current_income > 0 else 0

    # 2. Previous Month Comparison
    prev_m = 12 if selected_month == 1 else selected_month - 1
    prev_y = selected_year - 1 if selected_month == 1 else selected_year
    
    prev_txs = Transaction.objects.filter(user=user, transaction_type='OUT', date__year=prev_y, date__month=prev_m)
    prev_expenses = {}
    for tx in prev_txs:
        prev_expenses[tx.category] = prev_expenses.get(tx.category, Decimal('0.00')) + tx.amount

    # Insights collection
    insights = []
    potential_savings = Decimal('0.00')

    # A. Check Outflow to Inflow Ratio
    if total_expense > current_income and current_income > 0:
        over_pct = int(round((total_expense / current_income) * 100))
        deficit = total_expense - current_income
        insights.append({
            'type': 'danger',
            'badge': f'Outflows at {over_pct}% of Income',
            'badge_color': 'rose',
            'icon': 'alert-triangle',
            'title': 'Deficit Velocity Warning',
            'message': f"Monthly outflows exceed total inflows by {currency}{deficit:,.2f}. Discretionary expenditures require immediate freeze.",
            'savings_tip': f"Trim non-essential wants to recover {currency}{deficit:,.2f} baseline balance.",
            'action_prompt': f"Help me audit my spending to eliminate my {currency}{deficit:,.2f} monthly deficit"
        })
    elif current_income > 0 and savings_pct >= 20:
        insights.append({
            'type': 'success',
            'badge': f'{savings_pct}% Net Savings Surplus',
            'badge_color': 'emerald',
            'icon': 'trending-up',
            'title': 'Optimal Wealth Accumulation',
            'message': f"Your savings rate is {savings_pct}%, beating the standard 20% benchmark with {currency}{savings_surplus:,.2f} surplus capital.",
            'savings_tip': f"Direct {currency}{savings_surplus * Decimal('0.5'):,.2f} toward long-term index investments or high-yield reserves.",
            'action_prompt': f"Suggest the best allocation strategy for my {currency}{savings_surplus:,.2f} monthly savings surplus"
        })

    # B. Category Surges vs Previous Month
    for category, current_amt in sorted(current_expenses.items(), key=lambda x: x[1], reverse=True):
        prev_amt = prev_expenses.get(category, Decimal('0.00'))
        if prev_amt > 0 and current_amt > prev_amt:
            diff = current_amt - prev_amt
            surge_pct = int(round((diff / prev_amt) * 100))
            if surge_pct >= 15 and diff >= Decimal('25.00'):
                potential_savings += diff
                insights.append({
                    'type': 'surge',
                    'badge': f'+{surge_pct}% vs Last Month',
                    'badge_color': 'amber',
                    'icon': 'flame',
                    'title': f'{category} Outflow Surge',
                    'message': f"You spent {currency}{current_amt:,.2f} on {category} compared to {currency}{prev_amt:,.2f} last month (+{surge_pct}%).",
                    'savings_tip': f"Trimming {category} back to previous levels preserves {currency}{diff:,.2f} in cashflow.",
                    'action_prompt': f"Give me tips and budget limits to reduce spending on {category}"
                })

    # C. High Category Concentration
    if total_expense > 0:
        for category, amt in current_expenses.items():
            share_pct = int(round((amt / total_expense) * 100))
            if share_pct >= 30 and category != 'Rent':
                insights.append({
                    'type': 'concentration',
                    'badge': f'{share_pct}% of Outflows',
                    'badge_color': 'purple',
                    'icon': 'pie-chart',
                    'title': f'High {category} Concentration',
                    'message': f"{category} accounts for {share_pct}% of all your monthly disbursements ({currency}{amt:,.2f}).",
                    'savings_tip': "Diversifying and setting a strict weekly cap prevents capital lockup.",
                    'action_prompt': f"Set up a strict weekly budget plan for {category}"
                })

    # D. 50/30/20 Alignment Tip
    if current_income > 0:
        if needs_pct > 55:
            excess_needs = needs_amt - (current_income * Decimal('0.50'))
            insights.append({
                'type': 'blueprint',
                'badge': f'Needs at {needs_pct}% (Target 50%)',
                'badge_color': 'rose',
                'icon': 'shield-alert',
                'title': 'Needs Budget Compression',
                'message': f"Essential living necessities consume {needs_pct}% of your inflow, exceeding the 50% target by {currency}{excess_needs:,.2f}.",
                'savings_tip': "Audit recurring utility bills, grocery subscriptions, and fixed service contracts.",
                'action_prompt': "How can I lower my fixed living expenses and utilities?"
            })
        elif wants_pct > 32:
            excess_wants = wants_amt - (current_income * Decimal('0.30'))
            insights.append({
                'type': 'blueprint',
                'badge': f'Wants at {wants_pct}% (Target 30%)',
                'badge_color': 'amber',
                'icon': 'shopping-bag',
                'title': 'Discretionary Overspend',
                'message': f"Discretionary wants account for {wants_pct}% of inflows, overshooting the 30% guideline by {currency}{excess_wants:,.2f}.",
                'savings_tip': f"Implement a 48-hour rule for non-essential purchases to save {currency}{excess_wants:,.2f}.",
                'action_prompt': "Give me an action plan to curb impulsive and discretionary spending"
            })

    # Fallback insight if telemetry is perfectly smooth
    if not insights:
        insights.append({
            'type': 'success',
            'badge': 'Telemetry Stable',
            'badge_color': 'emerald',
            'icon': 'sparkles',
            'title': 'Disciplined Cashflow Alignment',
            'message': f"All categories are operating within healthy parameters with consistent inflow velocity.",
            'savings_tip': "Consider setting automated recurring transfer to high-yield investment reserves.",
            'action_prompt': "Forecast my savings growth over the next 12 months"
        })

    health_label = "OPTIMAL SURPLUS" if savings_pct >= 20 else ("BALANCED RUNWAY" if savings_pct >= 10 else "ACTION NEEDED")

    return {
        'insights': insights[:5],
        'fifty_thirty_twenty': {
            'needs_amt': needs_amt,
            'needs_pct': min(100, needs_pct),
            'needs_target': current_income * Decimal('0.50'),
            'wants_amt': wants_amt,
            'wants_pct': min(100, wants_pct),
            'wants_target': current_income * Decimal('0.30'),
            'savings_amt': savings_surplus,
            'savings_pct': min(100, savings_pct),
            'savings_target': current_income * Decimal('0.20'),
        },
        'burn_rate': {
            'daily_burn': daily_burn,
            'days_in_month': days_in_month,
            'days_elapsed': days_elapsed,
            'days_remaining': days_remaining,
            'projected_spend': projected_spend,
            'safe_daily_allowance': safe_daily_allowance,
        },
        'potential_savings': potential_savings,
        'health_label': health_label,
    }


def generate_recommendations(user, current_expenses, current_income):
    """Backwards-compatible recommendation generator."""
    today = date.today()
    total_expense = sum(current_expenses.values())
    telemetry = generate_ai_telemetry(user, current_expenses, current_income, total_expense, today.month, today.year, getattr(user, 'profile', None))
    return [item['message'] for item in telemetry['insights']][:3]

# ----------------- AJAX/JSON Analytics Data -----------------

@login_required
def analytics_data_api(request):
    user = request.user
    today = date.today()
    try:
        req_month = int(request.GET.get('month', today.month))
        req_year = int(request.GET.get('year', today.year))
        if req_month < 1 or req_month > 12 or req_year < 2000 or req_year > 2100:
            req_month, req_year = today.month, today.year
    except (ValueError, TypeError):
        req_month, req_year = today.month, today.year
    
    # 1. 6-Month Trends: Inflows vs Outflows ending at selected month/year
    trends = []
    for i in range(5, -1, -1):
        year = req_year
        month = req_month - i
        while month <= 0:
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

    # 2. Selected Month Category Expense Breakdown
    start_of_month = date(req_year, req_month, 1)
    _, last_day = calendar.monthrange(req_year, req_month)
    end_of_month = date(req_year, req_month, last_day)
    
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

    # 4. Budget vs Spent for Selected Month
    expense_categories = ['Food', 'Rent', 'Utilities', 'Entertainment', 'Travel', 'Other']
    budgets = Budget.objects.filter(user=user, year=req_year, month=req_month)
    
    fallback_budgets = {}
    if not budgets.exists():
        for b in Budget.objects.filter(user=user).order_by('-year', '-month'):
            if b.category not in fallback_budgets:
                fallback_budgets[b.category] = float(b.amount)

    comp_labels = []
    comp_budgets = []
    comp_spent = []
    
    for cat in expense_categories:
        b_obj = budgets.filter(category=cat).first()
        b_amount = float(b_obj.amount) if b_obj else fallback_budgets.get(cat, 0.0)
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
    if request.method == "POST":
        import json
        try:
            body = json.loads(request.body)
            query = body.get("query", "").strip()
        except Exception:
            return JsonResponse({"status": "error", "message": "Invalid JSON body"}, status=400)
        if not query:
            return JsonResponse({"status": "error", "message": "Query cannot be empty"}, status=400)
        from .assistant import LeoxurIntelligence
        intel = LeoxurIntelligence(user=request.user, client_context=body.get("client_context", {}))
        result = intel.process_message(query)
        return JsonResponse(result)
    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=400)


@login_required
def voice_process_api(request):
    """
    Multimodal voice detection and processing endpoint.
    Accepts audio data (file or base64) and language hint,
    transcribes/processes using Gemini Multimodal Audio or returns transcription for execution.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)
    
    import base64
    from .assistant import LeoxurIntelligence

    profile = request.user.profile
    ai_key = profile.get_active_ai_key()
    
    audio_bytes = None
    mime_type = "audio/webm"
    language_hint = request.POST.get('language') or 'auto'
    
    if 'audio' in request.FILES:
        audio_file = request.FILES['audio']
        audio_bytes = audio_file.read()
        mime_type = audio_file.content_type or 'audio/webm'
    elif request.content_type == 'application/json':
        import json
        try:
            body = json.loads(request.body)
            b64_data = body.get('audio_base64', '')
            if ',' in b64_data:
                header, b64_data = b64_data.split(',', 1)
                if 'audio/wav' in header: mime_type = 'audio/wav'
                elif 'audio/mp3' in header: mime_type = 'audio/mp3'
                elif 'audio/ogg' in header: mime_type = 'audio/ogg'
            if b64_data:
                audio_bytes = base64.b64decode(b64_data)
            language_hint = body.get('language') or language_hint
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Invalid JSON: {str(e)}'}, status=400)
        
    if not audio_bytes:
        return JsonResponse({'status': 'error', 'message': 'No audio data received'}, status=400)

    intel = LeoxurIntelligence(user=request.user)
    result = intel.process_voice_audio(audio_bytes, mime_type, language_hint, ai_key)
    return JsonResponse(result)


@login_required
def voice_speak_api(request):
    """
    Generate natural human speech audio from text using Google TTS engine.
    Supports global languages: en, es, hi, ta, fr, de, it, pt, ar, ru, zh, ja, etc.
    Returns base64 MP3 audio data for instant playback in browser.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)
    
    import json, base64, io, re

    try:
        data = json.loads(request.body)
        text = data.get('text', '').strip()
        lang_code = (data.get('language') or 'en').lower()
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Invalid JSON: {str(e)}'}, status=400)

    if not text:
        return JsonResponse({'status': 'error', 'message': 'No text provided'}, status=400)

    # 1. Clean and normalize text for realistic, warm, human-sounding speech
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    clean_text = re.sub(r'https?://\S+', '', clean_text)
    clean_text = re.sub(r'[*_#`~]', '', clean_text)
    # Currency conversions to natural words
    clean_text = re.sub(r'₹\s*([0-9,.]+)', r'\1 rupees', clean_text)
    clean_text = re.sub(r'\$\s*([0-9,.]+)', r'\1 dollars', clean_text)
    clean_text = re.sub(r'€\s*([0-9,.]+)', r'\1 euros', clean_text)
    clean_text = re.sub(r'£\s*([0-9,.]+)', r'\1 pounds', clean_text)
    clean_text = clean_text.replace('Refresh Dashboard', '').replace('↻', '').strip()
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    if not clean_text:
        return JsonResponse({'status': 'error', 'message': 'Cleaned text is empty'}, status=400)

    if len(clean_text) > 360:
        sentences = re.split(r'(?<=[.!?])\s+', clean_text)
        clean_text = ' '.join(sentences[:2]) if len(sentences) > 1 else clean_text[:360]

    lang_map = {
        'en': ('en', 'co.uk'),
        'en-us': ('en', 'com'),
        'en-in': ('en', 'co.in'),
        'es': ('es', 'es'),
        'es-es': ('es', 'es'),
        'hi': ('hi', 'co.in'),
        'hi-in': ('hi', 'co.in'),
        'ta': ('ta', 'co.in'),
        'ta-in': ('ta', 'co.in'),
        'fr': ('fr', 'fr'),
        'fr-fr': ('fr', 'fr'),
        'de': ('de', 'de'),
        'de-de': ('de', 'de'),
        'it': ('it', 'it'),
        'pt': ('pt', 'com.br'),
        'ar': ('ar', 'com'),
        'ru': ('ru', 'ru'),
        'zh': ('zh-CN', 'com'),
        'ja': ('ja', 'co.jp'),
        'te': ('te', 'co.in'),
        'ml': ('ml', 'co.in'),
        'kn': ('kn', 'co.in'),
    }

    base_lang = lang_code.split('-')[0]
    gtts_lang, gtts_tld = lang_map.get(lang_code, lang_map.get(base_lang, ('en', 'co.uk')))

    try:
        from gtts import gTTS
        tts = gTTS(text=clean_text, lang=gtts_lang, tld=gtts_tld, slow=False)
        audio_fp = io.BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        audio_b64 = base64.b64encode(audio_fp.read()).decode('utf-8')
        return JsonResponse({
            'status': 'success',
            'audio_base64': f'data:audio/mp3;base64,{audio_b64}',
            'language': gtts_lang,
            'clean_text': clean_text
        })
    except Exception as err:
        return JsonResponse({
            'status': 'error',
            'message': f'Human voice synthesis failed: {str(err)}'
        }, status=500)



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
        from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
        currency = request.POST.get('currency')
        rate_str = request.POST.get('conversion_rate', '1.0')
        scale_records = request.POST.get('scale_records', 'true') == 'true'

        if currency in ['$', '€', '₹', '£']:
            try:
                rate_str = rate_str.replace(',', '.').strip()
                rate = Decimal(rate_str)
            except Exception as e:
                print(f"[Currency Convert Error] Failed to parse rate '{rate_str}': {e}")
                rate = Decimal('1.00')

            profile = request.user.profile
            MAX_VAL = Decimal('999999999.99')

            # If scale_records is requested and rate is not 1.0, scale amounts safely
            if scale_records and rate != Decimal('1.00') and rate > 0:
                # 1. Transactions
                txs = Transaction.objects.filter(user=request.user)
                for tx in txs:
                    try:
                        new_amt = (tx.amount * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        tx.amount = min(new_amt, MAX_VAL)
                        tx.save(update_fields=['amount'])
                    except Exception as err:
                        print(f"[Currency Convert] Skipped tx {tx.id}: {err}")

                # 2. Budgets
                budgets = Budget.objects.filter(user=request.user)
                for b in budgets:
                    try:
                        new_amt = (b.amount * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        b.amount = min(new_amt, MAX_VAL)
                        b.save(update_fields=['amount'])
                    except Exception as err:
                        print(f"[Currency Convert] Skipped budget {b.id}: {err}")

                # 3. Reminders
                reminders = Reminder.objects.filter(user=request.user)
                for r in reminders:
                    try:
                        new_amt = (r.amount * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        r.amount = min(new_amt, MAX_VAL)
                        r.save(update_fields=['amount'])
                    except Exception as err:
                        print(f"[Currency Convert] Skipped reminder {r.id}: {err}")

                messages.success(request, f"Currency updated to {dict(Profile.CURRENCY_CHOICES).get(currency)}. Telemetry converted using rate ×{rate}!")
            else:
                messages.success(request, f"Currency updated to {dict(Profile.CURRENCY_CHOICES).get(currency)} (historical values preserved).")

            profile.currency = currency
            profile.save(update_fields=['currency'])
        else:
            messages.error(request, "Invalid currency choice.")
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
                <div style="background-color: #ff3b30; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-weight: 700; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; font-family: -apple-system, sans-serif;">
                    Target Category Breach Alert
                </div>
                <div style="background-color: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #e5e5ea; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.02);">
                    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e5ea;">
                            <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Target Category</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{b.category}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e5ea;">
                            <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Monthly Limit</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}{limit:.2f}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e5ea;">
                            <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Accumulated Total</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #ff3b30; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}{spent:.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Threshold Overage</td>
                            <td style="padding: 8px 0; font-size: 11px; color: #ff3b30; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}{spent - limit:.2f}</td>
                        </tr>
                    </table>
                </div>
                <p style="font-size: 11px; color: #8e8e93; line-height: 1.5; margin-top: 12px; margin-bottom: 0; font-family: -apple-system, sans-serif;">
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
            target_month = int(request.POST.get('month', today.month))
            target_year = int(request.POST.get('year', today.year))
            if target_month < 1 or target_month > 12 or target_year < 2000 or target_year > 2100:
                target_month, target_year = today.month, today.year
        except (ValueError, TypeError):
            target_month, target_year = today.month, today.year

        try:
            budget, created = Budget.objects.update_or_create(
                user=request.user,
                category=category,
                period='MONTHLY',
                month=target_month,
                year=target_year,
                defaults={'amount': Decimal(amount)}
            )
            messages.success(request, f"Budget set for {category} ({calendar.month_name[target_month]} {target_year})!")
        except Exception as e:
            messages.error(request, f"Error setting budget: {e}")
            
        return redirect(f"/dashboard/?month={target_month}&year={target_year}")
            
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
    try:
        target_month = int(request.GET.get('month', today.month))
        target_year = int(request.GET.get('year', today.year))
    except (ValueError, TypeError):
        target_month, target_year = today.month, today.year

    deleted_count, _ = Budget.objects.filter(
        user=request.user, 
        category=category, 
        year=target_year, 
        month=target_month
    ).delete()
    
    if deleted_count == 0:
        # Also clean up any un-anchored or generic budget for this category if existing
        deleted_count, _ = Budget.objects.filter(user=request.user, category=category).delete()

    if deleted_count > 0:
        messages.success(request, f"Budget limit for {category} cleared successfully.")
    else:
        messages.info(request, f"No budget set for {category}.")
    return redirect(f"/dashboard/?month={target_month}&year={target_year}")


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


def generate_pdf_data(user, total_income, total_expense, balance, currency, month=None, year=None):
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
    
    today = date.today()
    target_year = year or today.year
    target_month = month or today.month
    period_label = f"{calendar.month_name[target_month]} {target_year}"
    
    story.append(Paragraph("LEOXUR FINANCIAL LEDGER", title_style))
    story.append(Paragraph(f"Financial Telemetry Statement for node '{user.username}' | Period: {period_label} | Generated: {today.strftime('%B %d, %Y')}", subtitle_style))
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
    
    # Query transactions for the selected cycle
    from django.db.models import Sum
    from decimal import Decimal
    month_txs = Transaction.objects.filter(user=user, date__year=target_year, date__month=target_month)
    
    # 1. Savings Index Gauge Table
    savings_rate = int((balance / total_income * 100)) if total_income > 0 else 0
    if savings_rate < 0: savings_rate = 0
    if savings_rate > 100: savings_rate = 100
    
    if savings_rate < 10:
        savings_status = "CRITICAL OUTFLOW"
    elif savings_rate <= 30:
        savings_status = "STANDARD SURPLUS"
    else:
        savings_status = "STRONG SAVINGS INDEX"

    story.append(Paragraph("Savings Index Gauge", h2_style))
    savings_data = [
        ["Savings rate", "Saved Ratio Status"],
        [f"{savings_rate}% of Inflows Saved", savings_status]
    ]
    savings_table = Table(savings_data, colWidths=[180, 170])
    savings_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,1), (-1,-1), colors.white),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(savings_table)
    story.append(Spacer(1, 15))

    # 2. Outflow Concentration Table
    story.append(Paragraph("Outflow Concentration", h2_style))
    outflow_rows = [["Category", "Total Outflow Share", "Percentage Share"]]
    if total_expense > 0:
        outflow_by_cat = month_txs.filter(transaction_type='OUT').values('category').annotate(total=Sum('amount')).order_by('-total')
        for item in outflow_by_cat:
            pct = int((item['total'] / total_expense * 100))
            outflow_rows.append([
                item['category'],
                f"{currency}{item['total']:.2f}",
                f"{pct}%"
            ])
    if len(outflow_rows) == 1:
        outflow_rows.append(["N/A", "N/A", "N/A"])
        
    outflow_table = Table(outflow_rows, colWidths=[150, 120, 80])
    outflow_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(outflow_table)
    story.append(Spacer(1, 10))

    # Visual Graphical Chart: Category Outflow Distribution
    if total_expense > 0 and len(outflow_rows) > 1 and outflow_rows[1][0] != "N/A":
        try:
            from reportlab.graphics.shapes import Drawing
            from reportlab.graphics.charts.piecharts import Pie
            chart_drawing = Drawing(400, 140)
            pie = Pie()
            pie.x = 120
            pie.y = 10
            pie.width = 110
            pie.height = 110
            pie_vals = []
            pie_lbls = []
            palette = [
                colors.HexColor('#0071E3'), colors.HexColor('#34C759'), colors.HexColor('#FF9500'),
                colors.HexColor('#AF52DE'), colors.HexColor('#FF3B30'), colors.HexColor('#5AC8FA')
            ]
            for row in outflow_rows[1:7]:
                cat_name = row[0]
                amt_str = row[1].replace(currency, '').replace(',', '').strip()
                try:
                    amt_val = float(amt_str)
                    if amt_val > 0:
                        pie_vals.append(amt_val)
                        pie_lbls.append(f"{cat_name} ({row[2]})")
                except ValueError:
                    pass
            if pie_vals:
                pie.data = pie_vals
                pie.labels = pie_lbls
                pie.sideLabels = 1
                for idx in range(len(pie_vals)):
                    pie.slices[idx].fillColor = palette[idx % len(palette)]
                    pie.slices[idx].strokeColor = colors.white
                    pie.slices[idx].strokeWidth = 1
                chart_drawing.add(pie)
                story.append(Paragraph("Visual Outflow Distribution Chart", h2_style))
                story.append(chart_drawing)
                story.append(Spacer(1, 12))
        except Exception:
            pass
    else:
        story.append(Spacer(1, 15))

    # 3. Weekly Flow Patterns Table
    story.append(Paragraph("Weekly Flow Patterns", h2_style))
    weekly_flows = {1: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                    2: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                    3: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                    4: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')},
                    5: {'IN': Decimal('0.00'), 'OUT': Decimal('0.00')}}
    for tx in month_txs:
        w_idx = (tx.date.day - 1) // 7 + 1
        if w_idx > 5: w_idx = 5
        weekly_flows[w_idx][tx.transaction_type] += tx.amount
        
    weekly_rows = [["Week Name", "Weekly Inflow", "Weekly Outflow", "Weekly Net"]]
    for w_idx in sorted(weekly_flows.keys()):
        inflow = weekly_flows[w_idx]['IN']
        outflow = weekly_flows[w_idx]['OUT']
        if inflow == 0 and outflow == 0:
            continue
        weekly_rows.append([
            f"Week {w_idx}",
            f"{currency}{inflow:.2f}",
            f"{currency}{outflow:.2f}",
            f"{currency}{(inflow - outflow):.2f}"
        ])
    if len(weekly_rows) == 1:
        weekly_rows.append(["N/A", "N/A", "N/A", "N/A"])
        
    weekly_table = Table(weekly_rows, colWidths=[90, 90, 90, 80])
    weekly_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(weekly_table)
    story.append(Spacer(1, 15))

    # 4. Budget vs Spent Table
    story.append(Paragraph("Budget Vs Spent Targets", h2_style))
    budget_rows = [["Category", "Budget Limit", "Amount Spent", "Usage Ratio", "Status"]]
    budgets = Budget.objects.filter(user=user, year=today.year, month=today.month)
    for b in budgets:
        spent = total_expense if b.category == 'Total' else month_txs.filter(category=b.category, transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        pct = int((spent / b.amount * 100)) if b.amount > 0 else 0
        if pct >= 100:
            status_label = "BREACHED"
        elif pct >= 80:
            status_label = "WARNING"
        else:
            status_label = "HEALTHY"
            
        budget_rows.append([
            b.category,
            f"{currency}{b.amount:.2f}",
            f"{currency}{spent:.2f}",
            f"{pct}%",
            status_label
        ])
    if len(budget_rows) == 1:
        budget_rows.append(["N/A", "N/A", "N/A", "N/A", "N/A"])
        
    budget_table = Table(budget_rows, colWidths=[90, 80, 80, 50, 50])
    budget_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(budget_table)
    story.append(Spacer(1, 20))

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
                padding: 12px;
                background-color: #f5f5f7;
                color: #1c1c1e;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 12px; background-color: #f5f5f7; color: #1c1c1e;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f5f5f7; padding: 20px 0;">
            <tr>
                <td align="center" valign="top">
                    <table width="100%" max-width="600" style="width: 100%; max-width: 600px; background-color: #ffffff; border: 1px solid #e5e5ea; border-radius: 16px; border-collapse: separate; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.06);" cellspacing="0" cellpadding="0">
                        <!-- Header -->
                        <tr>
                            <td style="padding: 20px 24px; border-bottom: 1px solid #e5e5ea; background-color: #fafafa;">
                                <table width="100%" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td>
                                            <h2 style="margin: 0; font-size: 11px; font-weight: 700; color: #a855f7; letter-spacing: 1px; font-family: -apple-system, sans-serif; text-transform: uppercase;">LEOXUR TELEMETRY</h2>
                                            <div style="font-size: 8px; color: #8e8e93; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px;">{subtitle}</div>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <!-- Content -->
                        <tr>
                            <td style="padding: 24px 30px;">
                                <h1 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #1c1c1e; letter-spacing: -0.3px;">{title}</h1>
                                {content_html}
                            </td>
                        </tr>
                        <!-- Footer -->
                        <tr>
                            <td style="padding: 14px 24px; background-color: #fafafa; border-top: 1px solid #e5e5ea; text-align: center; font-size: 8px; color: #8e8e93;">
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
    flow_color = '#34c759' if tx_type == 'IN' else '#ff3b30'
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
                background-color: #f5f5f7;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }}
        </style>
    </head>
    <body style="margin: 0; padding: 10px; background-color: #f5f5f7;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f5f5f7;">
            <tr>
                <td align="center" valign="top">
                    <table width="100%" max-width="440" style="width: 100%; max-width: 440px; background-color: #ffffff; border: 1px solid #e5e5ea; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border-collapse: separate;" cellspacing="0" cellpadding="0">
                        <!-- Banner Header -->
                        <tr>
                            <td style="background-color: {flow_color}; color: #ffffff; padding: 8px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; text-align: center;">
                                Transaction Processed: {flow_label}
                            </td>
                        </tr>
                        <!-- Details Table -->
                        <tr>
                            <td style="padding: 16px;">
                                <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                                    <tr>
                                        <td style="font-size: 8px; text-transform: uppercase; color: #8e8e93; padding-bottom: 2px;">Category</td>
                                        <td style="font-size: 8px; text-transform: uppercase; color: #8e8e93; padding-bottom: 2px; text-align: center;">Amount</td>
                                        <td style="font-size: 8px; text-transform: uppercase; color: #8e8e93; padding-bottom: 2px; text-align: right;">Date</td>
                                    </tr>
                                    <tr>
                                        <td style="font-size: 12px; color: #1c1c1e; font-weight: 600; padding-right: 8px;">{category_name}</td>
                                        <td style="font-size: 12px; color: #1c1c1e; font-weight: 600; text-align: center; padding-right: 8px;">{currency}{amount:.2f}</td>
                                        <td style="font-size: 12px; color: #1c1c1e; font-weight: 600; text-align: right;">{date_str}</td>
                                    </tr>
                                </table>
                                <div style="margin-top: 10px; border-top: 1px solid #e5e5ea; padding-top: 8px; font-size: 10px; color: #8e8e93;">
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


def send_user_mail(user, subject, body, attachments=None, is_html=False, recipient=None):
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

    target_to = (recipient or '').strip() or getattr(user, 'email', None) or (profile.smtp_user if profile else None)
    if not target_to:
        raise ValueError("No recipient email address specified.")

    email = EmailMultiAlternatives(
        subject=subject,
        body=plain_text,
        from_email=from_email,
        to=[target_to],
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
        
        # Update User email profile
        user = request.user
        user.email = request.POST.get('account_email', '')
        user.save()
        
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
    <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 24px; border-spacing: 12px; border-collapse: separate; margin-left: -12px; margin-right: -12px;">
        <tr>
            <td width="50%" style="background-color: #ffffff; padding: 18px; border-radius: 12px; border: 1px solid #e5e5ea; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                <div style="font-size: 9px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700; margin-bottom: 4px;">Total Inflows</div>
                <div style="font-size: 20px; font-weight: 700; color: #34c759; margin-top: 6px;">{currency}{total_income:.2f}</div>
            </td>
            <td width="50%" style="background-color: #ffffff; padding: 18px; border-radius: 12px; border: 1px solid #e5e5ea; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                <div style="font-size: 9px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700; margin-bottom: 4px;">Total Outflows</div>
                <div style="font-size: 20px; font-weight: 700; color: #ff3b30; margin-top: 6px;">{currency}{total_expense:.2f}</div>
            </td>
        </tr>
    </table>
    
    <div style="background-color: #ffffff; padding: 18px; border-radius: 12px; border: 1px solid #e5e5ea; margin-bottom: 24px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
        <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 10px; border-collapse: collapse;">
            <tr>
                <td style="font-size: 10px; text-transform: uppercase; color: #8e8e93; letter-spacing: 0.5px; font-weight: 700;">Net Monthly Balance</td>
                <td style="font-size: 16px; font-weight: 700; color: {'#a855f7' if balance >= 0 else '#ff3b30'}; text-align: right;">{currency}{balance:.2f}</td>
            </tr>
        </table>
        <div style="background-color: #e5e5ea; border-radius: 9999px; height: 6px; overflow: hidden; width: 100%; margin-top: 6px;">
            <div style="background-color: #a855f7; height: 100%; width: {expense_pct}%; border-radius: 9999px;"></div>
        </div>
        <div style="font-size: 8px; color: #8e8e93; margin-top: 6px; text-align: right;">Spending ratio: {expense_pct}%</div>
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
            <td style="padding: 10px 0; font-size: 11px; color: #1c1c1e; font-family: -apple-system, sans-serif;">{tx.description or 'N/A'}</td>
            <td style="padding: 10px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">{tx.category}</td>
            <td style="padding: 10px 0; font-size: 11px; text-align: right; font-weight: 600; color: {amt_color}; font-family: -apple-system, sans-serif;">{amt_sign}{currency}{tx.amount:.2f}</td>
        </tr>
        """)
        
    recent_html = f"""
    <div style="margin-bottom: 8px; font-family: -apple-system, sans-serif;">
        <h3 style="font-size: 11px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-bottom: 12px; border-bottom: 1px solid #e5e5ea; padding-bottom: 6px; font-weight: 700;">Recent Statements</h3>
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
            <thead>
                <tr style="text-align: left; border-bottom: 1px solid #e5e5ea;">
                    <th style="padding-bottom: 6px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Description</th>
                    <th style="padding-bottom: 6px; font-size: 10px; text-transform: uppercase; color: #8e8e93; font-weight: 700; font-family: -apple-system, sans-serif;">Category</th>
                    <th style="padding-bottom: 6px; font-size: 10px; text-transform: uppercase; color: #8e8e93; text-align: right; font-weight: 700; font-family: -apple-system, sans-serif;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {"".join(recent_rows) if recent_rows else '<tr><td colspan="3" style="padding: 12px 0; font-size: 11px; color: #8e8e93; text-align: center; font-family: -apple-system, sans-serif;">No transactions found.</td></tr>'}
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
    <div style="background-color: #ff3b30; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-weight: 700; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; font-family: -apple-system, sans-serif;">
        Target Category Breach Alert
    </div>
    <div style="background-color: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #e5e5ea; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.02);">
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
            <tr style="border-bottom: 1px solid #e5e5ea;">
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Target Category</td>
                <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">Entertainment</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e5ea;">
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Monthly Limit</td>
                <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}250.00</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e5ea;">
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Accumulated Total</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ff3b30; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}320.00</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Threshold Overage</td>
                <td style="padding: 8px 0; font-size: 11px; color: #ff3b30; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}70.00</td>
            </tr>
        </table>
    </div>
    <p style="font-size: 11px; color: #8e8e93; line-height: 1.5; margin-top: 12px; margin-bottom: 0; font-family: -apple-system, sans-serif;">
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
    <div style="background-color: #a855f7; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-weight: 700; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; font-family: -apple-system, sans-serif;">
        Scheduled Payment Due Today
    </div>
    <div style="background-color: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #e5e5ea; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.02);">
        <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
            <tr style="border-bottom: 1px solid #e5e5ea;">
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Bill Description</td>
                <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">Internet & Broadband subscription</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e5ea;">
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Amount Due</td>
                <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}79.99</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e5ea;">
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Due Date</td>
                <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{date.today().strftime('%A, %b %d, %Y')}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Recurrence</td>
                <td style="padding: 8px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">Yes (Monthly)</td>
            </tr>
        </table>
    </div>
    <p style="font-size: 11px; color: #8e8e93; line-height: 1.5; margin-top: 12px; margin-bottom: 0; font-family: -apple-system, sans-serif;">
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
        try:
            req_month = int(request.GET.get('month', today.month))
            req_year = int(request.GET.get('year', today.year))
            if req_month < 1 or req_month > 12 or req_year < 2000 or req_year > 2100:
                req_month, req_year = today.month, today.year
        except (ValueError, TypeError):
            req_month, req_year = today.month, today.year
            
        start_of_month = date(req_year, req_month, 1)
        _, last_day = calendar.monthrange(req_year, req_month)
        end_of_month = date(req_year, req_month, last_day)
        
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
        
        data = generate_pdf_data(request.user, total_income, total_expense, balance, currency, month=req_month, year=req_year)
        response = HttpResponse(data, content_type='application/pdf')
        month_abbr = calendar.month_abbr[req_month].lower()
        response['Content-Disposition'] = f'attachment; filename="leoxur_statement_{month_abbr}_{req_year}.pdf"'
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


@login_required
def update_ai_settings(request):
    if request.method == 'POST':
        import json
        profile = request.user.profile
        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST
            ai_mode = data.get('ai_mode', profile.ai_mode)
            ai_provider = data.get('ai_provider', profile.ai_provider)
            ai_api_key = (data.get('ai_api_key') or '').strip()
            ai_model = (data.get('ai_model') or '').strip()
            ai_custom_endpoint = (data.get('ai_custom_endpoint') or '').strip()

            profile.ai_mode = ai_mode
            profile.ai_provider = ai_provider
            if ai_api_key:
                profile.ai_api_key = ai_api_key
                if ai_provider == 'gemini':
                    profile.gemini_api_key = ai_api_key
            elif data.get('clear_key'):
                profile.ai_api_key = ''
                profile.gemini_api_key = ''

            profile.ai_model = ai_model
            profile.ai_custom_endpoint = ai_custom_endpoint
            profile.save()
            return JsonResponse({
                'status': 'success',
                'message': 'AI Settings updated successfully!',
                'ai_mode': profile.ai_mode,
                'ai_provider': profile.ai_provider,
                'has_key': bool(profile.get_saved_ai_key()),
                'model': profile.get_effective_ai_model(),
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)


def reminders_check_api(request):
    """Graceful JSON endpoint for background reminder checks"""
    return JsonResponse({'status': 'ok', 'due_reminders': []})


@login_required
def test_smtp_settings(request):
    """Real-time validation for SMTP outbound connection and test email dispatch."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)
    
    import json
    from django.core.mail import get_connection, EmailMultiAlternatives
    from django.utils import timezone
    profile = request.user.profile
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST

        host = data.get('smtp_host') or profile.smtp_host or 'smtp.gmail.com'
        port = int(data.get('smtp_port') or profile.smtp_port or 587)
        user = data.get('smtp_user') or profile.smtp_user or ''
        pwd = data.get('smtp_password') or profile.smtp_password or ''
        account_email = data.get('account_email') or request.user.email or user

        if not user or not pwd:
            return JsonResponse({
                'status': 'error',
                'message': 'SMTP Username and App Password are required to test outbound mail.'
            }, status=400)

        # Attempt SMTP connection
        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=host,
            port=port,
            username=user,
            password=pwd,
            use_tls=(port == 587),
            use_ssl=(port == 465),
            timeout=10,
        )
        connection.open()

        # Send test verification message
        recipient = account_email if account_email else user
        msg = EmailMultiAlternatives(
            subject="[Leoxur Financial] SMTP Outbound Verification Successful",
            body=(
                f"Hello {request.user.username},\n\n"
                f"Your SMTP outbound node has been successfully verified!\n\n"
                f"• SMTP Server: {host}:{port}\n"
                f"• Authenticated User: {user}\n"
                f"• Target Recipient: {recipient}\n"
                f"• Timestamp: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                f"Automated email alerts, financial reports, and transaction receipts are fully operational.\n\n"
                f"— Leoxur Financial Telemetry Engine"
            ),
            from_email=f"Leoxur Financial <{user}>",
            to=[recipient],
            connection=connection
        )
        msg.send()
        connection.close()

        # Persist tested credentials to profile
        profile.smtp_host = host
        profile.smtp_port = port
        profile.smtp_user = user
        profile.smtp_password = pwd
        profile.save(update_fields=['smtp_host', 'smtp_port', 'smtp_user', 'smtp_password'])
        if account_email and account_email != request.user.email:
            request.user.email = account_email
            request.user.save(update_fields=['email'])

        return JsonResponse({
            'status': 'success',
            'message': f"✓ SMTP connection verified! Test email successfully delivered to {recipient}."
        })
    except Exception as e:
        err_msg = str(e)
        if "Authentication" in err_msg or "Username and Password not accepted" in err_msg:
            err_msg = "Authentication failed. If using Gmail, please create and use a 16-character App Password (not your normal Google account password)."
        return JsonResponse({
            'status': 'error',
            'message': f"SMTP Verification Failed: {err_msg}"
        }, status=400)


@login_required
def test_imap_settings(request):
    """Real-time validation for IMAP inbox connection and message search."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)
    
    import json
    import imaplib
    profile = request.user.profile
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST

        host = data.get('imap_host') or profile.imap_host or 'imap.gmail.com'
        port = int(data.get('imap_port') or profile.imap_port or 993)
        user = data.get('imap_user') or profile.imap_user or ''
        pwd = data.get('imap_password') or profile.imap_password or ''
        account_email = data.get('account_email') or request.user.email or user

        if not user or not pwd:
            return JsonResponse({
                'status': 'error',
                'message': 'IMAP Username and Password are required to test mailbox fetching.'
            }, status=400)

        # Connect to IMAP
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, pwd)
        status, folder_info = mail.select("inbox", readonly=True)
        if status != 'OK':
            raise RuntimeError(f"Could not open INBOX on {host}.")

        total_msgs = int(folder_info[0].decode('utf-8')) if folder_info and folder_info[0] else 0

        # Check unread count
        _, unseen_res = mail.search(None, 'UNSEEN')
        unseen_count = len(unseen_res[0].split()) if unseen_res and unseen_res[0] else 0

        # Check transactions from user's email if available
        target_sender = account_email or user
        _, sender_res = mail.search(None, f'(FROM "{target_sender}")')
        sender_count = len(sender_res[0].split()) if sender_res and sender_res[0] else 0

        mail.close()
        mail.logout()

        # Persist tested credentials to profile
        profile.imap_host = host
        profile.imap_port = port
        profile.imap_user = user
        profile.imap_password = pwd
        profile.save(update_fields=['imap_host', 'imap_port', 'imap_user', 'imap_password'])

        return JsonResponse({
            'status': 'success',
            'message': (
                f"✓ IMAP connection verified! Successfully accessed INBOX on {host}:{port}. "
                f"Total emails: {total_msgs} | Unread: {unseen_count} | From {target_sender}: {sender_count}."
            ),
            'total_emails': total_msgs,
            'unread_emails': unseen_count,
            'sender_emails': sender_count
        })
    except Exception as e:
        err_msg = str(e)
        if "AUTHENTICATIONFAILED" in err_msg or "Invalid credentials" in err_msg:
            err_msg = "IMAP authentication failed. If using Gmail, make sure IMAP is enabled in Gmail settings and use an App Password."
        return JsonResponse({
            'status': 'error',
            'message': f"IMAP Connection Failed: {err_msg}"
        }, status=400)


@login_required
def test_ai_settings(request):
    """Test AI LLM Connection and generate a test greeting/audit response."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)
    
    import json
    from .assistant import LeoxurIntelligence
    profile = request.user.profile
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST

        prov = data.get('ai_provider') or profile.ai_provider
        key = (data.get('ai_api_key') or profile.get_saved_ai_key() or '').strip()
        model = (data.get('ai_model') or profile.ai_model or '').strip()
        endpoint = (data.get('ai_custom_endpoint') or profile.ai_custom_endpoint or '').strip()

        if data.get('ai_mode') == 'local':
            return JsonResponse({
                'status': 'success',
                'message': '✓ Local Deterministic Engine is active (Zero external API dependencies).'
            })

        if not key:
            return JsonResponse({
                'status': 'error',
                'message': 'API Key is required to test Cloud AI provider.'
            }, status=400)

        profile.ai_api_key = key
        profile.ai_provider = prov
        if prov == 'gemini':
            profile.gemini_api_key = key
        profile.ai_model = model
        profile.ai_mode = 'cloud'
        profile.ai_custom_endpoint = endpoint
        profile.save()

        intel = LeoxurIntelligence(user=request.user)
        result = intel._call_cloud_ai("Perform quick handshake: confirm AI connection in 1 short sentence.", key)
        
        return JsonResponse({
            'status': 'success',
            'message': f"✓ Successfully connected to {profile.get_ai_provider_display_name()} ({profile.get_effective_ai_model()})!",
            'reply': result.get('reply', 'AI Connection Live'),
            'model': profile.get_effective_ai_model()
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f"AI Connection Failed: {str(e)}"
        }, status=400)
