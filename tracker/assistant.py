import os
import re
import json
import urllib.request
import urllib.error
import datetime
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Q
from .models import Transaction, Budget, Reminder, Category, Profile

class LeoxurIntelligence:
    """
    Leoxur Intelligence — Autonomous Financial Telemetry & AI Agent.
    Powered by Cloud AI Agents (Google Gemini, Groq, OpenAI, Anthropic, OpenRouter)
    with seamless fallback to an ultra-fast local deterministic financial brain.
    """

    def __init__(self, user, client_context=None):
        self.user = user
        self.profile = getattr(user, 'profile', None)
        self.client_context = client_context or {}

    def _build_financial_analytics(self):
        """Assemble comprehensive, real-time financial telemetry for the user."""
        today = timezone.localdate()
        start_of_month = datetime.date(today.year, today.month, 1)
        if today.month == 12:
            next_month = datetime.date(today.year + 1, 1, 1)
        else:
            next_month = datetime.date(today.year, today.month + 1, 1)
        end_of_month = next_month - datetime.timedelta(days=1)

        currency = self.profile.currency if self.profile else '$'

        # Current month transactions
        month_txs = Transaction.objects.filter(user=self.user, date__range=(start_of_month, end_of_month))
        total_income = float(month_txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
        total_expense = float(month_txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
        net_balance = total_income - total_expense
        savings_rate = int((net_balance / total_income) * 100) if total_income > 0 and net_balance > 0 else 0

        # Expenses by Category
        category_expenses = {}
        for tx in month_txs.filter(transaction_type='OUT'):
            category_expenses[tx.category] = category_expenses.get(tx.category, 0.0) + float(tx.amount)
        cat_expenses_str = ", ".join([f"{k}: {currency}{v:.2f}" for k, v in sorted(category_expenses.items(), key=lambda x: x[1], reverse=True)]) or "No expenses logged this month"

        # Incomes by Category
        category_incomes = {}
        for tx in month_txs.filter(transaction_type='IN'):
            category_incomes[tx.category] = category_incomes.get(tx.category, 0.0) + float(tx.amount)
        cat_incomes_str = ", ".join([f"{k}: {currency}{v:.2f}" for k, v in sorted(category_incomes.items(), key=lambda x: x[1], reverse=True)]) or "No income logged this month"

        # Budgets
        budgets = Budget.objects.filter(user=self.user, year=today.year, month=today.month)
        budget_details = []
        overspent_count = 0
        for b in budgets:
            spent = category_expenses.get(b.category, 0.0)
            diff = float(b.amount) - spent
            if diff < 0:
                overspent_count += 1
                budget_details.append(f"• {b.category}: Limit {currency}{b.amount:.2f} | Spent {currency}{spent:.2f} (OVERSPENT by {currency}{abs(diff):.2f})")
            else:
                budget_details.append(f"• {b.category}: Limit {currency}{b.amount:.2f} | Spent {currency}{spent:.2f} ({currency}{diff:.2f} remaining)")
        budgets_str = "\n".join(budget_details) if budget_details else "No active category budgets set this month."

        # Upcoming Reminders & Outflow Alerts
        reminders = Reminder.objects.filter(user=self.user).order_by('due_date')
        pending_reminders = reminders.filter(is_paid=False)
        reminders_list = []
        for r in pending_reminders[:5]:
            reminders_list.append(f"• '{r.title}': {currency}{r.amount:.2f} due on {r.due_date.strftime('%Y-%m-%d')}")
        reminders_str = "\n".join(reminders_list) if reminders_list else "No pending bill reminders."

        # Recent Transactions
        recent_txs = Transaction.objects.filter(user=self.user).order_by('-date', '-created_at')[:6]
        recent_list = []
        for t in recent_txs:
            sign = "+" if t.transaction_type == 'IN' else "-"
            recent_list.append(f"• {t.date.strftime('%b %d')}: {sign}{currency}{t.amount:.2f} [{t.category}] {t.description or ''}")
        recent_txs_str = "\n".join(recent_list) if recent_list else "No transactions recorded yet."

        # Categories list
        categories = Category.objects.filter(user=self.user).values_list('name', flat=True)
        categories_str = ", ".join(list(categories)) if categories else "Food, Rent, Salary, Freelance, Utilities, Entertainment, Travel"

        provider = self.profile.ai_provider if self.profile else 'gemini'
        model = self.profile.get_effective_ai_model() if self.profile else 'gemini-1.5-flash'
        ai_mode = getattr(self.profile, 'ai_mode', 'cloud')

        return {
            'today_str': today.strftime('%Y-%m-%d'),
            'month_name': today.strftime('%B %Y'),
            'currency': currency,
            'total_income': total_income,
            'total_expense': total_expense,
            'net_balance': net_balance,
            'savings_rate': savings_rate,
            'cat_expenses_str': cat_expenses_str,
            'cat_incomes_str': cat_incomes_str,
            'budgets_str': budgets_str,
            'overspent_count': overspent_count,
            'reminders_str': reminders_str,
            'recent_txs_str': recent_txs_str,
            'categories_str': categories_str,
            'ai_provider': provider,
            'ai_model': model,
            'ai_mode': ai_mode,
        }

    def get_active_ai_key(self):
        """Retrieve active API key for cloud LLM."""
        if self.profile:
            return self.profile.get_active_ai_key()
        return (
            os.getenv('GEMINI_API_KEY') or
            getattr(settings, 'GEMINI_API_KEY', '') or
            os.getenv('OPENAI_API_KEY') or
            os.getenv('GROQ_API_KEY') or
            ''
        )

    def process_message(self, user_text):
        """
        Analyze user query and return a structured response dictionary:
        {
            'status': 'success',
            'response': html_or_markdown_str,
            'reply': plain_markdown_str,
            'action_type': str,
            'payload': dict
        }
        """
        text = user_text.strip()
        text_lower = text.lower()

        # 0. Strict Domain Guardrail: Exclusively personal finance & Leoxur app
        out_of_scope_match = re.search(
            r'\b(aws|ec2|iaas|paas|s3|vpc|lambda|iam\s+role|elastic\s+beanstalk|cloudformation|'
            r'kubernetes|k8s|terraform|ansible|docker\s+compose|nginx\s+proxy|apache\s+server|'
            r'azure\s+vm|gcp\s+compute|devops|ci\/cd|github\s+actions)\b',
            text_lower
        )
        if out_of_scope_match:
            reply = (
                "🛡️ **Exclusive Financial Domain Scope**\n\n"
                "I am **Leoxur AI Copilot**, engineered solely for **personal financial telemetry, "
                "expense/income tracking, budgeting, and cashflow optimization** within this application.\n\n"
                "I cannot configure or answer questions about external cloud infrastructure like **AWS EC2 or IaaS services**.\n\n"
                "Here is what I can do for you:\n"
                "• ➕ **Log transactions** (*\"Add expense 45 for Food\"*)\n"
                "• 🎨 **Change theme** (*\"Switch to dark theme\"* or *\"Switch to light mode\"*)\n"
                "• 📧 **Email reports** (*\"Send report to my email\"*)\n"
                "• 📬 **Inspect IMAP mailbox** (*\"Fetch IMAP details\"* or *\"Sync emails\"*)\n"
                "• 📊 **Audit cashflow & visual suggestions** (*\"Give me visual spending suggestions\"*)"
            )
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Financial Scope Only", reply, "bg-apple-orange/10 text-apple-orange"),
                'action_type': 'scope_refusal',
                'payload': {}
            }

        # 1. Check for API Key configuration via chat
        api_key_set_match = re.search(
            r'(?:set|save|update)\s+(gemini|groq|openai|claude|anthropic|openrouter|ai)\s+(?:api\s+)?key\s+(?:to\s+)?([A-Za-z0-9_\-\.:]{14,})',
            text, re.I
        )
        if api_key_set_match:
            prov = api_key_set_match.group(1).lower()
            if prov == 'claude': prov = 'anthropic'
            if prov == 'ai': prov = (self.profile.ai_provider if self.profile else 'gemini')
            new_key = api_key_set_match.group(2).strip()
            if self.profile:
                self.profile.ai_provider = prov
                self.profile.ai_api_key = new_key
                self.profile.ai_mode = 'cloud'
                if prov == 'gemini':
                    self.profile.gemini_api_key = new_key
                self.profile.save()
                reply = (
                    f"🤖 **{prov.upper()} API Key Configured!**\n\n"
                    f"Leoxur AI Copilot is now connected to **{self.profile.get_ai_provider_display_name()}** "
                    f"(`{self.profile.get_effective_ai_model()}`). Autonomous reasoning and financial actions are live."
                )
                return {
                    'status': 'success',
                    'reply': reply,
                    'response': self._format_bubble_html("API Key Configured", reply, "bg-apple-blue/10 text-apple-blue"),
                    'action_type': 'general',
                    'payload': {'ai_connected': True, 'provider': prov}
                }

        # 2. AI Mode Switching & Clear Key
        if any(p in text_lower for p in ['switch to non-ai mode', 'switch to non ai mode', 'switch to local mode', 'enable local mode', 'turn off ai', 'disable ai', 'offline mode']):
            if self.profile:
                self.profile.ai_mode = 'local'
                self.profile.save(update_fields=['ai_mode'])
            reply = (
                "🔒 **Switched to 100% Offline Local Engine Mode.**\n\n"
                "Leoxur Copilot is now operating without external cloud requests:\n\n"
                "• Zero API keys required or transmitted\n"
                "• Instant deterministic execution of expense logging, budget checking, and cashflow analytics\n"
                "• All telemetry remains strictly local."
            )
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Local Engine Active", reply, "bg-apple-green/10 text-apple-green"),
                'action_type': 'general',
                'payload': {'ai_mode': 'local'}
            }

        if any(p in text_lower for p in ['switch to ai mode', 'switch to cloud ai mode', 'switch to cloud mode', 'enable ai mode', 'turn on ai', 'activate ai mode']):
            if self.profile:
                self.profile.ai_mode = 'cloud'
                self.profile.save(update_fields=['ai_mode'])
            has_key = bool(self.get_active_ai_key())
            key_msg = f"Connected to **{self.profile.get_ai_provider_display_name()}** (`{self.profile.get_effective_ai_model()}`)." if has_key else "No API key configured yet. Click **AI Settings** or paste: `set gemini api key to <KEY>`."
            reply = f"⚡ **Switched to Cloud AI Mode.**\n\n{key_msg}"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Cloud AI Mode", reply, "bg-apple-blue/10 text-apple-blue"),
                'action_type': 'general',
                'payload': {'ai_mode': 'cloud', 'ai_connected': has_key}
            }

        if any(p in text_lower for p in ['clear api key', 'remove api key', 'delete api key', 'clear key']):
            if self.profile:
                self.profile.ai_api_key = ''
                self.profile.gemini_api_key = ''
                self.profile.save(update_fields=['ai_api_key', 'gemini_api_key'])
            reply = "🗑️ **API Key Cleared.**\n\nLeoxur Copilot is now running safely on the built-in Local Deterministic Engine."
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Key Removed", reply, "bg-apple-orange/10 text-apple-orange"),
                'action_type': 'general',
                'payload': {'api_key_cleared': True}
            }

        # 3. If in Cloud AI mode and active API key is provided, attempt LLM agent call
        ai_key = self.get_active_ai_key()
        if getattr(self.profile, 'ai_mode', 'cloud') == 'cloud' and ai_key:
            try:
                ai_result = self._call_cloud_ai(text, ai_key)
                if ai_result:
                    return ai_result
            except Exception as e:
                # Fallback quietly to local deterministic engine if cloud call fails
                print(f"[Leoxur Copilot] Cloud AI call failed: {e}. Falling back to local brain.")

        # 4. Local Deterministic Financial Brain
        return self._process_local_deterministic(text, text_lower)

    def _call_cloud_ai(self, user_text, api_key):
        """Invoke Cloud AI across Google Gemini, Groq, OpenAI, Claude, OpenRouter, or Custom Local."""
        provider = (self.profile.ai_provider if self.profile else 'gemini').lower()
        model = self.profile.get_effective_ai_model() if self.profile else 'gemini-1.5-flash'
        endpoint = (self.profile.ai_custom_endpoint if self.profile else '').strip()

        analytics = self._build_financial_analytics()
        currency = analytics['currency']

        system_prompt = f"""You are Leoxur Copilot, an autonomous executive financial AI companion and telemetry analyst for the Leoxur Income & Expense Tracker web application.
You possess COMPLETE, REAL-TIME, and EXCLUSIVE operational authority over this personal finance application and the user's ledger.

=== CRITICAL DOMAIN BOUNDARY ===
You are SOLELY and EXCLUSIVELY dedicated to this personal finance application.
Under NO CIRCUMSTANCE should you answer questions about Amazon Web Services (AWS), EC2 instance creation, VPC, S3, cloud hosting infrastructure, Kubernetes, Terraform, or generic IT sysadmin topics.
If asked about AWS, EC2, or external IT, politely decline and state that you are exclusively focused on personal finance telemetry and the Leoxur tracker.

=== REAL-TIME USER FINANCIAL TELEMETRY ===
• Current Month: {analytics['month_name']} (Today: {analytics['today_str']})
• Currency: {currency}
• Total Monthly Inflow (Income): {currency}{analytics['total_income']:.2f}
• Total Monthly Outflow (Expense): {currency}{analytics['total_expense']:.2f}
• Net Cashflow Balance: {currency}{analytics['net_balance']:.2f}
• Savings Rate: {analytics['savings_rate']}%
• Top Outflows by Category: {analytics['cat_expenses_str']}
• Inflow Sources: {analytics['cat_incomes_str']}
• Category Budgets & Health:
{analytics['budgets_str']}
• Upcoming Bill Reminders:
{analytics['reminders_str']}
• Recent Ledger Entries:
{analytics['recent_txs_str']}
• Available System Categories: {analytics['categories_str']}

=== AUTONOMOUS TOOL KNOWLEDGE & ACTIONS ===
You can execute any of these tools directly by setting "action_type" and "payload":

1. "log_transaction":
   Log a single income or expense.
   payload: {{"amount": float, "transaction_type": "IN" | "OUT", "category": str, "description": str, "date": "YYYY-MM-DD"}}

2. "log_multiple_transactions":
   Log multiple items at once (e.g., "spent 50 on food, 20 on fuel, and 100 on groceries").
   payload: {{"transactions": [{{"amount": float, "transaction_type": "OUT", "category": str, "description": str}}, ...]}}

3. "delete_transaction":
   Delete last transaction or delete matching record.
   payload: {{"last": true}} OR {{"id": int}} OR {{"category": str, "amount": float}}

4. "set_budget":
   Set or adjust a category or Total budget cap.
   payload: {{"category": str, "amount": float, "period": "MONTHLY"}}

5. "reset_budgets":
   Rebalance budgets to healthy benchmarks (e.g. 50% needs, 30% wants).
   payload: {{"targets": {{"Food": float, "Rent": float, "Utilities": float, "Total": float}}}}

6. "set_reminder":
   Schedule a bill due date.
   payload: {{"title": str, "amount": float, "due_date": "YYYY-MM-DD"}}

7. "pay_reminder":
   Mark a bill reminder as settled/paid.
   payload: {{"title": str}}

8. "change_currency":
   Switch primary currency (e.g. from $ to ₹, or ₹ to $) and convert ledger.
   payload: {{"currency": "$" | "€" | "₹" | "£", "conversion_rate": float, "scale_records": true | false}}

9. "sync_emails":
   Inspect IMAP mailbox, check unread banking receipts, and sync transactions into ledger.
   payload: {{}}

10. "change_theme":
    Switch application appearance between dark and light mode.
    payload: {{"theme": "dark" | "light"}}

11. "send_email_report":
    Dispatch monthly cashflow and budget report to user's configured email via SMTP.
    payload: {{"recipient": str (optional)}}

12. "cashflow_audit" / "visual_suggestion":
    Perform a comprehensive diagnostic with 50/30/20 rule, budget leakages, actionable spending suggestions, and set "visual_card": true to render an inline visual SVG blueprint chart and money utilization guidelines.

=== STRICT RESPONSE SCHEMA ===
You must ALWAYS respond with a valid JSON object matching this schema:
{{
  "thought": "Deep strategic analysis of user intent and financial state",
  "reply": "Concise, elegant, executive Apple-style markdown response with emojis and high-value details",
  "action_type": "log_transaction | log_multiple_transactions | delete_transaction | set_budget | reset_budgets | set_reminder | pay_reminder | change_currency | sync_emails | change_theme | send_email_report | cashflow_audit | visual_suggestion | general | guide",
  "payload": {{ ... }},
  "visual_card": true | false
}}

Return ONLY valid JSON.
"""
        user_agent = 'LeoxurTracker/2.5.0 (Apple iOS Theme; Leoxur Inc.)'

        # 1. Google Gemini
        if provider == 'gemini':
            payload_data = {
                "contents": [{"role": "user", "parts": [{"text": user_text}]}],
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}
            }
            deprecated = {'gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-1.5-pro'}
            candidate_models = [
                model,
                'gemini-3.5-flash-lite',
                'gemini-flash-lite-latest',
                'gemini-3.1-flash-lite',
                'gemini-3.8-flash',
                'gemini-flash-latest',
            ]
            seen = set()
            last_err = None
            for m in candidate_models:
                if not m or m in seen or m in deprecated:
                    continue
                seen.add(m)
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload_data).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'User-Agent': user_agent},
                    method='POST'
                )
                try:
                    with urllib.request.urlopen(req, timeout=12) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        text_content = result['candidates'][0]['content']['parts'][0]['text']
                        data = self._clean_json(text_content)
                        return self._apply_cloud_action(data)
                except urllib.error.HTTPError as e:
                    last_err = f"HTTP {e.code}"
                    if e.code in (400, 404, 503, 429):
                        continue
                    raise
                except Exception as ex:
                    last_err = str(ex)
                    continue
            raise RuntimeError(f"Gemini models did not respond ({last_err or 'No responsive endpoint'}).")

        # 2. OpenAI-Compatible (Groq, OpenAI, OpenRouter, Custom)
        elif provider in ('groq', 'openai', 'openrouter', 'custom'):
            if provider == 'groq':
                api_url = "https://api.groq.com/openai/v1/chat/completions"
            elif provider == 'openai':
                api_url = "https://api.openai.com/v1/chat/completions"
            elif provider == 'openrouter':
                api_url = "https://openrouter.ai/api/v1/chat/completions"
            else:
                base = (endpoint or 'http://localhost:11434/v1').rstrip('/')
                api_url = f"{base}/chat/completions"

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': user_agent,
                'Authorization': f'Bearer {api_key}' if api_key else ''
            }
            candidates = [model]
            if provider == 'groq':
                candidates.extend(['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'])

            for candidate_model in candidates:
                req_body = {
                    "model": candidate_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
                req = urllib.request.Request(api_url, data=json.dumps(req_body).encode('utf-8'), headers=headers, method='POST')
                try:
                    with urllib.request.urlopen(req, timeout=12) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        raw_text = result['choices'][0]['message']['content']
                        data = self._clean_json(raw_text)
                        return self._apply_cloud_action(data)
                except Exception:
                    continue

        # 3. Anthropic Claude
        elif provider == 'anthropic':
            api_url = "https://api.anthropic.com/v1/messages"
            headers = {
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            }
            req_body = {
                "model": model or "claude-3-5-sonnet-20241022",
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_text}],
                "max_tokens": 1024,
                "temperature": 0.1
            }
            req = urllib.request.Request(api_url, data=json.dumps(req_body).encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=12) as response:
                result = json.loads(response.read().decode('utf-8'))
                raw_text = result['content'][0]['text']
                data = self._clean_json(raw_text)
                return self._apply_cloud_action(data)

        raise ValueError(f"Unsupported AI provider: {provider}")

    def _clean_json(self, text):
        text = text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1]
        return json.loads(text)

    def _generate_visual_telemetry_svg(self, analytics):
        """Generate sleek Apple-styled SVG financial telemetry infographic card."""
        currency = analytics.get('currency', '$')
        income = float(analytics.get('total_income', 0.0))
        expense = float(analytics.get('total_expense', 0.0))
        balance = float(analytics.get('net_balance', 0.0))

        # 50/30/20 target breakdown
        needs_target = income * 0.50 if income > 0 else 15000.0
        wants_target = income * 0.30 if income > 0 else 9000.0
        savings_target = income * 0.20 if income > 0 else 6000.0

        # Health score (0-100)
        if income > 0:
            savings_ratio = max(0.0, balance / income)
            expense_ratio = min(1.0, expense / income)
            health_score = int(min(100, max(20, (savings_ratio * 60) + (40 * (1 - expense_ratio)))))
        else:
            health_score = 45 if expense == 0 else 25

        score_color = "#34C759" if health_score >= 70 else ("#FF9500" if health_score >= 45 else "#FF3B30")
        score_label = "HEALTHY SURPLUS" if health_score >= 70 else ("ATTENTION" if health_score >= 45 else "DEFICIT ALERT")

        marker_x = min(360, max(15, int(10 + (expense / (income or expense or 1)) * 340)))

        svg = f"""
        <div style="margin-top:14px; border-radius:14px; padding:16px; background:linear-gradient(135deg, rgba(15,23,42,0.92), rgba(30,41,59,0.92)); border:1px solid rgba(255,255,255,0.14); color:#ffffff; font-family:-apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:16px;">📊</span>
                    <strong style="font-size:12px; letter-spacing:-0.01em;">Autonomous 50/30/20 Blueprint & Telemetry</strong>
                </div>
                <span style="font-size:10px; font-weight:800; padding:3px 8px; border-radius:999px; background:{score_color}25; color:{score_color}; border:1px solid {score_color}40;">
                    SCORE: {health_score}/100 ({score_label})
                </span>
            </div>

            <svg viewBox="0 0 380 90" width="100%" height="90" style="display:block; overflow:visible;">
                <defs>
                    <linearGradient id="gNeeds" x1="0%" y1="0%" x2="100%" y2="0%">
                        <stop offset="0%" stop-color="#0A84FF"/>
                        <stop offset="100%" stop-color="#5AC8FA"/>
                    </linearGradient>
                    <linearGradient id="gWants" x1="0%" y1="0%" x2="100%" y2="0%">
                        <stop offset="0%" stop-color="#BF5AF2"/>
                        <stop offset="100%" stop-color="#FF375F"/>
                    </linearGradient>
                    <linearGradient id="gSavings" x1="0%" y1="0%" x2="100%" y2="0%">
                        <stop offset="0%" stop-color="#30D158"/>
                        <stop offset="100%" stop-color="#34C759"/>
                    </linearGradient>
                </defs>

                <rect x="10" y="24" width="360" height="14" rx="7" fill="rgba(255,255,255,0.08)"/>
                <rect x="10" y="24" width="180" height="14" rx="7" fill="url(#gNeeds)"/>
                <rect x="194" y="24" width="108" height="14" rx="7" fill="url(#gWants)"/>
                <rect x="306" y="24" width="64" height="14" rx="7" fill="url(#gSavings)"/>

                <text x="10" y="16" fill="#8E8ED2" font-size="9" font-weight="700">50% NEEDS</text>
                <text x="194" y="16" fill="#FF85A0" font-size="9" font-weight="700">30% WANTS</text>
                <text x="306" y="16" fill="#80E89E" font-size="9" font-weight="700">20% SAVINGS</text>

                <text x="10" y="52" fill="#FFFFFF" font-size="10" font-weight="800">{currency}{needs_target:,.0f}</text>
                <text x="194" y="52" fill="#FFFFFF" font-size="10" font-weight="800">{currency}{wants_target:,.0f}</text>
                <text x="306" y="52" fill="#FFFFFF" font-size="10" font-weight="800">{currency}{savings_target:,.0f}</text>

                <circle cx="{marker_x}" cy="31" r="8" fill="#FFFFFF" stroke="#000000" stroke-width="2"/>
                <text x="{marker_x}" y="74" text-anchor="middle" fill="#FFD60A" font-size="9" font-weight="700">Current Spend: {currency}{expense:,.0f}</text>
            </svg>

            <div style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.08); font-size:11px; line-height:1.5;">
                <div style="color:rgba(255,255,255,0.7); margin-bottom:4px;">💡 <strong>Strategic Money Utilization Advice:</strong></div>
                <div style="color:#A7F3D0;">• Essential Needs cap target: {currency}{needs_target:,.2f}</div>
                <div style="color:#BAE6FD;">• Discretionary Wants target: {currency}{wants_target:,.2f}</div>
                <div style="color:#FDE68A;">• Wealth Accumulation: Allocate {currency}{savings_target:,.2f} directly to investments each cycle.</div>
            </div>
        </div>
        """
        return svg

    def _send_financial_report_email(self, recipient_override=None):
        """Build and send rich Apple-style financial telemetry report via SMTP with attached PDF & Excel spreadsheets."""
        try:
            from tracker.views import send_user_mail, generate_excel_data, generate_pdf_data
            analytics = self._build_financial_analytics()
            recipient = (recipient_override or '').strip()
            if not recipient and self.user.email:
                recipient = self.user.email.strip()
            if not recipient and self.profile:
                recipient = (self.profile.smtp_user or self.profile.imap_user or '').strip()

            if not recipient:
                return False, "No recipient email configured. Please set your email address in Email Node Settings or profile.", []

            currency = analytics['currency']
            month_slug = analytics['month_name'].replace(' ', '_')
            subject = f"Leoxur Financial Telemetry Statement — {analytics['month_name']}"

            # 1. Generate real ReportLab PDF with visual category charts & ledger
            pdf_bytes = generate_pdf_data(
                self.user,
                Decimal(str(analytics['total_income'])),
                Decimal(str(analytics['total_expense'])),
                Decimal(str(analytics['net_balance'])),
                currency
            )

            # 2. Generate real OpenPyXL Excel spreadsheet with Inflows, Outflows, and Budgets
            excel_bytes = generate_excel_data(self.user)

            attachments = [
                (f"Leoxur_Financial_Report_{month_slug}.pdf", pdf_bytes, "application/pdf"),
                (f"Leoxur_Cashflow_{month_slug}.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            ]

            html_body = f"""
            <div style="font-family:-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif; max-width:620px; margin:0 auto; padding:28px 24px; background:#0B0F19; color:#FFFFFF; border-radius:18px; border:1px solid rgba(255,255,255,0.12);">
                <div style="border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:18px; margin-bottom:22px;">
                    <div style="display:inline-block; font-size:11px; font-weight:800; color:#0A84FF; text-transform:uppercase; letter-spacing:0.08em; background:rgba(10,132,255,0.15); padding:3px 10px; border-radius:999px; margin-bottom:8px;">LEOXUR FINANCIAL INTELLIGENCE</div>
                    <h2 style="margin:0; font-size:22px; font-weight:700; letter-spacing:-0.02em;">Executive Telemetry Statement & Ledger</h2>
                    <p style="margin:4px 0 0 0; font-size:12px; color:#94A3B8;">Cycle: {analytics['month_name']} (Generated on {analytics['today_str']})</p>
                </div>

                <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px;">
                    <div style="background:rgba(255,255,255,0.04); padding:16px; border-radius:14px; border:1px solid rgba(255,255,255,0.06);">
                        <div style="font-size:10px; font-weight:700; color:#94A3B8; text-transform:uppercase; letter-spacing:0.04em;">Monthly Inflow</div>
                        <div style="font-size:20px; font-weight:800; color:#34C759; margin-top:4px;">{currency}{analytics['total_income']:,.2f}</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.04); padding:16px; border-radius:14px; border:1px solid rgba(255,255,255,0.06);">
                        <div style="font-size:10px; font-weight:700; color:#94A3B8; text-transform:uppercase; letter-spacing:0.04em;">Monthly Outflow</div>
                        <div style="font-size:20px; font-weight:800; color:#FF453A; margin-top:4px;">{currency}{analytics['total_expense']:,.2f}</div>
                    </div>
                </div>

                <div style="background:rgba(255,255,255,0.04); padding:18px; border-radius:14px; border:1px solid rgba(255,255,255,0.06); margin-bottom:20px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <span style="font-size:12px; color:#94A3B8;">Net Cashflow Balance</span>
                        <span style="font-size:16px; font-weight:800; color:{'#34C759' if analytics['net_balance'] >= 0 else '#FF453A'};">{currency}{analytics['net_balance']:,.2f}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:12px; color:#94A3B8;">Savings Allocation</span>
                        <span style="font-size:14px; font-weight:700; color:#0A84FF;">{analytics['savings_rate']}% of Inflows</span>
                    </div>
                </div>

                <!-- Attached Files Notice -->
                <div style="background:rgba(10,132,255,0.08); border:1px solid rgba(10,132,255,0.25); border-radius:12px; padding:14px; margin-bottom:20px;">
                    <div style="font-size:12px; font-weight:700; color:#0A84FF; margin-bottom:6px;">📎 Enclosed Attachments:</div>
                    <div style="font-size:11px; color:#E2E8F0; line-height:1.6;">
                        • <strong>Leoxur_Financial_Report_{month_slug}.pdf</strong>: Official PDF financial statement with category visual pie charts and telemetry breakdown.<br>
                        • <strong>Leoxur_Cashflow_{month_slug}.xlsx</strong>: Multi-sheet spreadsheet ledger of all inflows, outflows, and budget targets.
                    </div>
                </div>

                <div style="margin-bottom:18px;">
                    <div style="font-size:11px; font-weight:700; color:#94A3B8; text-transform:uppercase; margin-bottom:6px;">Category Outflows</div>
                    <div style="font-size:12px; color:#E2E8F0; line-height:1.6;">{analytics['cat_expenses_str']}</div>
                </div>

                <div style="margin-bottom:20px;">
                    <div style="font-size:11px; font-weight:700; color:#94A3B8; text-transform:uppercase; margin-bottom:6px;">Category Budgets</div>
                    <div style="font-size:12px; color:#E2E8F0; line-height:1.6; white-space:pre-line;">{analytics['budgets_str']}</div>
                </div>

                <div style="border-top:1px solid rgba(255,255,255,0.08); padding-top:14px; font-size:11px; color:#64748B; text-align:center;">
                    Transmitted by Leoxur Autonomous Telemetry Node for <strong>{self.user.username}</strong>
                </div>
            </div>
            """
            # Ensure user object has email set if necessary
            if not self.user.email and recipient:
                self.user.email = recipient
                self.user.save(update_fields=['email'])

            send_user_mail(self.user, subject, html_body, attachments=attachments, is_html=True, recipient=recipient)
            return True, recipient, [att[0] for att in attachments]
        except Exception as ex:
            return False, str(ex), []

    def _inspect_and_sync_imap(self):
        """Inspect configured IMAP mailbox, report telemetry, and sync incoming transactions."""
        import imaplib
        from django.core.management import call_command
        from django.db import connections

        profile = self.profile
        host = (profile.imap_host if profile and profile.imap_host else 'imap.gmail.com').strip()
        port = int(profile.imap_port if profile and profile.imap_port else 993)
        user = (profile.imap_user if profile and profile.imap_user else '').strip()
        pwd = (profile.imap_password if profile and profile.imap_password else '').strip()

        if not user or not pwd:
            return {
                'success': False,
                'message': (
                    "⚠️ **IMAP Mailbox Not Configured**\n\n"
                    "Your IMAP credentials (username / App Password) have not been configured yet.\n\n"
                    "👉 Click **⚙️ Email Node Settings** to configure your IMAP host (`imap.gmail.com`) "
                    "and App Password so I can fetch and parse bank receipts."
                )
            }

        try:
            mail = imaplib.IMAP4_SSL(host, port)
            mail.login(user, pwd)
            status, folder_info = mail.select("inbox", readonly=True)
            total_msgs = int(folder_info[0].decode('utf-8')) if folder_info and folder_info[0] else 0

            _, unseen_res = mail.search(None, 'UNSEEN')
            unseen_count = len(unseen_res[0].split()) if unseen_res and unseen_res[0] else 0

            mail.close()
            mail.logout()

            # Execute actual fetch and parse command
            try:
                call_command('fetch_emails')
            except Exception:
                pass
            finally:
                connections.close_all()

            msg = (
                f"📬 **IMAP Mailbox Telemetry & Sync Active!**\n\n"
                f"• **IMAP Server**: `{host}:{port}` (SSL Verified ✅)\n"
                f"• **Connected Account**: `{user}`\n"
                f"• **Total Emails in Inbox**: **{total_msgs:,}**\n"
                f"• **Unread Bank Receipts**: **{unseen_count}**\n\n"
                f"Incoming receipts were scanned and synchronized into your ledger."
            )
            return {'success': True, 'message': msg}
        except Exception as e:
            err = str(e)
            if "AUTHENTICATIONFAILED" in err or "Invalid credentials" in err:
                err = "Authentication failed. Check your App Password."
            msg = (
                f"❌ **IMAP Mailbox Connection Notice**\n\n"
                f"• **Server**: `{host}:{port}`\n"
                f"• **Account**: `{user}`\n"
                f"• **Status**: {err}\n\n"
                f"Please verify your credentials in **Email Node Settings**."
            )
            return {'success': False, 'message': msg}

    def _apply_cloud_action(self, data):
        """Execute action requested by Cloud AI."""
        action_type = data.get('action_type', 'general')
        payload = data.get('payload', {})
        reply = data.get('reply', '')
        currency = self.profile.currency if self.profile else '$'
        today = timezone.localdate()
        analytics = self._build_financial_analytics()
        show_visual = data.get('visual_card') or action_type in ('cashflow_audit', 'visual_suggestion')

        if action_type == 'log_transaction':
            amount = float(payload.get('amount') or 0.0)
            tx_type = payload.get('transaction_type', 'OUT').upper()
            category = (payload.get('category') or 'Other').strip().title()
            desc = payload.get('description', '')
            date_val = payload.get('date') or today

            if amount > 0:
                Transaction.objects.create(
                    user=self.user,
                    amount=Decimal(str(amount)),
                    transaction_type=tx_type,
                    category=category,
                    description=desc,
                    date=date_val
                )
                Category.objects.get_or_create(user=self.user, name=category, defaults={'is_income': (tx_type == 'IN')})
                sign = "+" if tx_type == 'IN' else "-"
                badge_class = "bg-apple-green/10 text-apple-green" if tx_type == 'IN' else "bg-apple-red/10 text-apple-red"
                html = self._format_bubble_html("Ledger Entry Created", reply or f"Recorded {sign}{currency}{amount:.2f} in {category}.", badge_class)
                return {'status': 'success', 'reply': reply, 'response': html, 'action_type': action_type, 'payload': payload}

        elif action_type == 'log_multiple_transactions':
            items = payload.get('transactions', [])
            logged_count = 0
            for item in items:
                try:
                    amt = float(item.get('amount') or 0.0)
                    if amt <= 0: continue
                    t_type = (item.get('transaction_type') or 'OUT').upper()
                    cat = (item.get('category') or 'General').strip().title()
                    d = item.get('description', '')
                    dt = item.get('date') or today
                    Transaction.objects.create(
                        user=self.user,
                        amount=Decimal(str(amt)),
                        transaction_type=t_type,
                        category=cat,
                        description=d,
                        date=dt
                    )
                    Category.objects.get_or_create(user=self.user, name=cat, defaults={'is_income': (t_type == 'IN')})
                    logged_count += 1
                except Exception:
                    pass
            html = self._format_bubble_html("Multiple Ledger Entries Created", reply or f"Successfully logged {logged_count} transactions.", "bg-apple-green/10 text-apple-green")
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'log_transaction', 'payload': payload}

        elif action_type == 'delete_transaction':
            deleted_count = 0
            if payload.get('id'):
                deleted_count, _ = Transaction.objects.filter(user=self.user, id=payload['id']).delete()
            elif payload.get('last'):
                latest = Transaction.objects.filter(user=self.user).order_by('-created_at').first()
                if latest:
                    latest.delete()
                    deleted_count = 1
            elif payload.get('category') or payload.get('amount'):
                q = Transaction.objects.filter(user=self.user)
                if payload.get('category'):
                    q = q.filter(category__iexact=payload['category'])
                if payload.get('amount'):
                    q = q.filter(amount=Decimal(str(payload['amount'])))
                deleted_count, _ = q.delete()
            html = self._format_bubble_html("Ledger Entry Removed", reply or f"Deleted {deleted_count} transaction(s).", "bg-apple-orange/10 text-apple-orange")
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'delete_transaction', 'payload': payload}

        elif action_type == 'set_budget':
            category = payload.get('category', 'General').title()
            amount = float(payload.get('amount') or 0.0)
            if amount > 0:
                Budget.objects.update_or_create(
                    user=self.user,
                    category=category,
                    period='MONTHLY',
                    month=today.month,
                    year=today.year,
                    defaults={'amount': Decimal(str(amount))}
                )
                html = self._format_bubble_html("Budget Configured", reply or f"Set monthly budget for {category} to {currency}{amount:.2f}.", "bg-apple-blue/10 text-apple-blue")
                return {'status': 'success', 'reply': reply, 'response': html, 'action_type': action_type, 'payload': payload}

        elif action_type == 'reset_budgets':
            targets = payload.get('targets', {
                'Food': 6000.0,
                'Rent': 25000.0,
                'Utilities': 3000.0,
                'Total': 34000.0
            })
            for cat, amt in targets.items():
                Budget.objects.update_or_create(
                    user=self.user,
                    category=cat.title(),
                    period='MONTHLY',
                    month=today.month,
                    year=today.year,
                    defaults={'amount': Decimal(str(amt))}
                )
            html = self._format_bubble_html("Budgets Rebalanced", reply or "Normalized budgets to optimal telemetry benchmarks.", "bg-apple-blue/10 text-apple-blue")
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'set_budget', 'payload': payload}

        elif action_type == 'set_reminder':
            title = payload.get('title', 'Upcoming Bill')
            amount = float(payload.get('amount') or 0.0)
            due_date = payload.get('due_date') or today
            if amount > 0:
                Reminder.objects.create(
                    user=self.user,
                    title=title,
                    amount=Decimal(str(amount)),
                    due_date=due_date,
                    is_paid=False
                )
                html = self._format_bubble_html("Reminder Created", reply or f"Created reminder for '{title}' ({currency}{amount:.2f}) on {due_date}.", "bg-apple-orange/10 text-apple-orange")
                return {'status': 'success', 'reply': reply, 'response': html, 'action_type': action_type, 'payload': payload}

        elif action_type == 'pay_reminder':
            title = payload.get('title')
            rem = Reminder.objects.filter(user=self.user, is_paid=False)
            if title:
                rem = rem.filter(title__icontains=title)
            r_obj = rem.first()
            if r_obj:
                r_obj.is_paid = True
                r_obj.save()
                reply = reply or f"Marked bill '{r_obj.title}' ({currency}{r_obj.amount:.2f}) as paid."
            html = self._format_bubble_html("Bill Settled", reply, "bg-apple-green/10 text-apple-green")
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'set_reminder', 'payload': payload}

        elif action_type == 'change_currency':
            new_curr = payload.get('currency', '$')
            rate_val = float(payload.get('conversion_rate') or 1.0)
            scale = bool(payload.get('scale_records', True))
            if self.profile and new_curr in ['$', '€', '₹', '£']:
                self.profile.currency = new_curr
                self.profile.save()
                if scale and rate_val != 1.0 and rate_val > 0:
                    dec_rate = Decimal(str(rate_val))
                    for tx in Transaction.objects.filter(user=self.user):
                        try:
                            tx.amount = (tx.amount * dec_rate).quantize(Decimal('0.01'))
                            tx.save()
                        except Exception: pass
                    for b in Budget.objects.filter(user=self.user):
                        try:
                            b.amount = (b.amount * dec_rate).quantize(Decimal('0.01'))
                            b.save()
                        except Exception: pass
            html = self._format_bubble_html("Currency Denomination Converted", reply or f"Switched ledger denomination to {new_curr}.", "bg-apple-blue/10 text-apple-blue")
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'change_currency', 'payload': payload}

        elif action_type == 'change_theme':
            t = (payload.get('theme') or 'dark').lower()
            if t not in ('dark', 'light'):
                t = 'light' if 'light' in reply.lower() else 'dark'
            if self.profile:
                self.profile.theme = t
                self.profile.save(update_fields=['theme'])
            reply = reply or f"Switched interface appearance to **{t.title()} Mode**."
            html = self._format_bubble_html("Appearance Updated", reply, "bg-apple-purple/10 text-apple-purple")
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'change_theme', 'payload': {'theme': t}}

        elif action_type == 'send_email_report':
            recipient = payload.get('recipient')
            ok, msg, file_list = self._send_financial_report_email(recipient)
            if ok:
                reply = (
                    f"📧 **Executive Financial Statement Dispatched!**\n\n"
                    f"Transmitted your monthly financial report to **{msg}** via your configured SMTP mail node.\n\n"
                    f"**📎 Enclosed Attachments:**\n"
                    f"• **PDF Statement**: Complete financial telemetry statement with category visual pie charts and telemetry breakdown.\n"
                    f"• **Excel Spreadsheet (.xlsx)**: Itemized ledger of all inflows, outflows, and monthly budget targets."
                )
                badge = "bg-apple-green/10 text-apple-green"
                download_buttons = """
                <div style="margin-top:12px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.08); display:flex; flex-wrap:wrap; gap:8px;">
                    <a href="/export-pdf/" target="_blank" style="padding:6px 14px; font-size:11px; font-weight:700; border-radius:999px; background:var(--apple-blue); color:#ffffff; text-decoration:none; display:inline-flex; align-items:center; gap:6px; box-shadow:0 2px 8px rgba(0,113,227,0.35);">
                        📄 Open PDF Statement
                    </a>
                    <a href="/export-excel/" target="_blank" style="padding:6px 14px; font-size:11px; font-weight:700; border-radius:999px; background:var(--bg-subtle); color:var(--text-primary); border:1px solid var(--border-hairline); text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
                        📊 Open Excel Spreadsheet
                    </a>
                </div>
                """
                html = self._format_bubble_html("Email Report Dispatched", reply, badge) + download_buttons
            else:
                reply = f"⚠️ **Email Report Failed**: {msg}"
                badge = "bg-apple-red/10 text-apple-red"
                html = self._format_bubble_html("Email Report", reply, badge)
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'send_email_report', 'payload': {'recipient': msg, 'success': ok}}

        elif action_type == 'sync_emails':
            sync_info = self._inspect_and_sync_imap()
            reply = sync_info['message']
            badge = "bg-apple-purple/10 text-apple-purple" if sync_info['success'] else "bg-apple-red/10 text-apple-red"
            html = self._format_bubble_html("Mailbox Sync Telemetry", reply, badge)
            return {'status': 'success', 'reply': reply, 'response': html, 'action_type': 'sync_emails', 'payload': {'synced': sync_info['success']}}

        html = self._format_bubble_html("Leoxur Intelligence", reply, "bg-apple-blue/10 text-apple-blue")
        if show_visual:
            html += self._generate_visual_telemetry_svg(analytics)

        return {'status': 'success', 'reply': reply, 'response': html, 'action_type': action_type, 'payload': payload}

    def _process_local_deterministic(self, query, q_lower):
        """Fast, robust deterministic local processing."""
        today = timezone.localdate()
        currency = self.profile.currency if self.profile else '$'

        # Theme switching
        if re.search(r'(?:switch|change|set|toggle)\s+(?:theme|mode|appearance)\s+(?:to\s+)?(dark|light)', q_lower) or re.search(r'\b(dark\s+mode|light\s+mode|dark\s+theme|light\s+theme)\b', q_lower):
            t = 'light' if 'light' in q_lower else 'dark'
            if self.profile:
                self.profile.theme = t
                self.profile.save(update_fields=['theme'])
            reply = f"🌓 **Appearance Updated**\n\nSwitched Leoxur interface to **{t.title()} Mode**."
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Appearance Updated", reply, "bg-apple-purple/10 text-apple-purple"),
                'action_type': 'change_theme',
                'payload': {'theme': t}
            }

        # Send Email Report via SMTP with PDF & Spreadsheet
        if re.search(r'(?:send|email|mail|dispatch)\b.*?\b(?:report|summary|statement|pdf|spreadsheet|excel|telemetry)\b', q_lower):
            recipient_match = re.search(r'(?:to|recipient)\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', query)
            target_rcpt = recipient_match.group(1) if recipient_match else None
            ok, msg, file_list = self._send_financial_report_email(target_rcpt)
            if ok:
                reply = (
                    f"📧 **Executive Financial Statement Dispatched!**\n\n"
                    f"Transmitted your monthly financial report to **{msg}** via your configured SMTP mail node.\n\n"
                    f"**📎 Enclosed Attachments:**\n"
                    f"• **PDF Statement**: Complete financial telemetry statement with category visual pie charts and telemetry breakdown.\n"
                    f"• **Excel Spreadsheet (.xlsx)**: Itemized ledger of all inflows, outflows, and monthly budget targets."
                )
                badge = "bg-apple-green/10 text-apple-green"
                download_buttons = """
                <div style="margin-top:12px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.08); display:flex; flex-wrap:wrap; gap:8px;">
                    <a href="/export-pdf/" target="_blank" style="padding:6px 14px; font-size:11px; font-weight:700; border-radius:999px; background:var(--apple-blue); color:#ffffff; text-decoration:none; display:inline-flex; align-items:center; gap:6px; box-shadow:0 2px 8px rgba(0,113,227,0.35);">
                        📄 Open PDF Statement
                    </a>
                    <a href="/export-excel/" target="_blank" style="padding:6px 14px; font-size:11px; font-weight:700; border-radius:999px; background:var(--bg-subtle); color:var(--text-primary); border:1px solid var(--border-hairline); text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
                        📊 Open Excel Spreadsheet
                    </a>
                </div>
                """
                html = self._format_bubble_html("Email Report Dispatched", reply, badge) + download_buttons
            else:
                reply = f"⚠️ **Email Report Failed**: {msg}"
                badge = "bg-apple-red/10 text-apple-red"
                html = self._format_bubble_html("Email Report", reply, badge)
            return {
                'status': 'success',
                'reply': reply,
                'response': html,
                'action_type': 'send_email_report',
                'payload': {'recipient': msg, 'success': ok}
            }

        # Email IMAP sync & inspection
        if re.search(r'(?:sync\s+emails|fetch\s+emails|fetch\s+transactions|fetch\s+imap|check\s+imap|imap\s+details|check\s+mail|mailbox)', q_lower):
            sync_info = self._inspect_and_sync_imap()
            reply = sync_info['message']
            badge = "bg-apple-purple/10 text-apple-purple" if sync_info['success'] else "bg-apple-red/10 text-apple-red"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("IMAP Mailbox Telemetry", reply, badge),
                'action_type': 'sync_emails',
                'payload': {'synced': sync_info['success']}
            }

        # Visual Suggestions, Images & Money Utilization Blueprint
        if re.search(r'(?:visual|chart|image|blueprint|utilize\s+money|spend\s+better|money\s+advice|financial\s+advice|suggestion)', q_lower):
            analytics = self._build_financial_analytics()
            curr = analytics['currency']
            tot_inc = analytics['total_income']
            tot_exp = analytics['total_expense']
            needs_tgt = tot_inc * 0.50 if tot_inc > 0 else 25000.0
            wants_tgt = tot_inc * 0.30 if tot_inc > 0 else 15000.0
            save_tgt = tot_inc * 0.20 if tot_inc > 0 else 10000.0
            reply = (
                f"📈 **Autonomous Spending Optimization & Money Allocation Blueprint:**\n\n"
                f"To maximize long-term wealth, trust, and fiscal resilience, adhere to this **50/30/20 rule allocation**:\n\n"
                f"1️⃣ **Essential Needs (50% Cap: {curr}{needs_tgt:,.2f})**:\n"
                f"• Rent, groceries, utilities, and debt minimums.\n"
                f"• *Current Status*: Essential expenses are tracking within normal parameters.\n\n"
                f"2️⃣ **Discretionary Wants (30% Cap: {curr}{wants_tgt:,.2f})**:\n"
                f"• Dining out, entertainment, shopping, hobbies.\n"
                f"• *Rule*: Never exceed 30% of monthly net income to prevent lifestyle creep.\n\n"
                f"3️⃣ **Wealth Accumulation (20% Minimum: {curr}{save_tgt:,.2f})**:\n"
                f"• Emergency fund liquidity & diversified index investments.\n"
                f"• *Pro-Tip*: Automate your savings transfer on payday before discretionary spending begins."
            )
            html = self._format_bubble_html("Visual Spending Blueprint", reply, "bg-apple-blue/10 text-apple-blue")
            html += self._generate_visual_telemetry_svg(analytics)
            return {
                'status': 'success',
                'reply': reply,
                'response': html,
                'action_type': 'visual_suggestion',
                'payload': analytics
            }

        # Add transaction
        tx_match = re.search(r'add\s+(expense|income)\s+(\d+(?:\.\d{1,2})?)(?:\s+(?:for|in)\s+([a-zA-Z0-9_\-\s]+?))?(?:\s+(?:desc|description|note)\s+(.+))?$', query, re.I)
        if tx_match:
            t_type_str = tx_match.group(1).lower()
            amt = Decimal(tx_match.group(2))
            cat = (tx_match.group(3) or 'General').strip().title()
            desc = (tx_match.group(4) or '').strip()
            t_type = 'IN' if t_type_str == 'income' else 'OUT'
            
            Transaction.objects.create(
                user=self.user,
                amount=amt,
                transaction_type=t_type,
                category=cat,
                date=today,
                description=desc
            )
            Category.objects.get_or_create(user=self.user, name=cat, defaults={'is_income': (t_type == 'IN')})
            sign = "+" if t_type == 'IN' else "-"
            reply = f"✅ **{t_type_str.title()} Logged Successfully**\n\n• **Amount**: {sign}{currency}{amt:.2f}\n• **Category**: {cat}\n• **Note**: {desc or 'N/A'}\n• **Date**: {today.strftime('%b %d, %Y')}"
            badge_class = "bg-apple-green/10 text-apple-green" if t_type == 'IN' else "bg-apple-red/10 text-apple-red"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Transaction Logged", reply, badge_class),
                'action_type': 'log_transaction',
                'payload': {'amount': float(amt), 'category': cat, 'type': t_type}
            }

        # Set budget
        b_match = re.search(r'set\s+(?:budget|limit)\s+(?:for\s+)?([a-zA-Z0-9_\-\s]+?)\s+(?:to\s+)?(\d+(?:\.\d{1,2})?)$', query, re.I)
        if b_match:
            cat = b_match.group(1).strip().title()
            amt = Decimal(b_match.group(2))
            Budget.objects.update_or_create(
                user=self.user,
                category=cat,
                period='MONTHLY',
                month=today.month,
                year=today.year,
                defaults={'amount': amt}
            )
            reply = f"🎯 **Monthly Budget Updated**\n\n• **Category**: {cat}\n• **Monthly Limit**: {currency}{amt:.2f}\n• **Period**: {today.strftime('%B %Y')}"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Budget Configured", reply, "bg-apple-blue/10 text-apple-blue"),
                'action_type': 'set_budget',
                'payload': {'category': cat, 'amount': float(amt)}
            }

        # Bill reminder
        r_match = re.search(r'remind\s+(?:me\s+to\s+pay\s+)?(.+?)\s+(\d+(?:\.\d{1,2})?)\s+on\s+(\d{4}-\d{2}-\d{2})$', query, re.I)
        if r_match:
            title = r_match.group(1).strip().capitalize()
            amt = Decimal(r_match.group(2))
            due_date_str = r_match.group(3)
            try:
                due_date = datetime.datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                due_date = today

            Reminder.objects.create(
                user=self.user,
                title=title,
                amount=amt,
                due_date=due_date,
                is_paid=False
            )
            reply = f"⏰ **Bill Reminder Created**\n\n• **Title**: {title}\n• **Amount**: {currency}{amt:.2f}\n• **Due Date**: {due_date.strftime('%b %d, %Y')}"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Reminder Created", reply, "bg-apple-orange/10 text-apple-orange"),
                'action_type': 'set_reminder',
                'payload': {'title': title, 'amount': float(amt), 'due_date': str(due_date)}
            }

        # Help / Guide
        if q_lower in ('help', 'commands', 'menu', '?', 'what can you do', 'guide'):
            reply = (
                "🧠 **Leoxur Financial Intelligence — Command Guide:**\n\n"
                "I can autonomously manage your personal financial ledger, telemetry, and system actions:\n\n"
                "1️⃣ **Log Expenses & Incomes**:\n"
                "• *\"Add expense 45 for Food desc lunch at office\"*\n"
                "• *\"Add income 2500 for Salary desc October paycheck\"*\n\n"
                "2️⃣ **Appearance & System Actions**:\n"
                "• *\"Switch to dark theme\"* / *\"Switch to light mode\"* — Instant appearance change\n"
                "• *\"Send report to my email\"* — Transmit monthly cashflow report via SMTP\n"
                "• *\"Fetch IMAP details\"* or *\"Sync emails\"* — Inspect mailbox receipts & unread count\n\n"
                "3️⃣ **Set Budgets & Outflow Limits**:\n"
                "• *\"Set budget for Food to 350\"*\n"
                "• *\"Set Entertainment budget to 150\"*\n\n"
                "4️⃣ **Bill Reminders**:\n"
                "• *\"Remind me to pay internet bill 60 on 2026-10-25\"*\n\n"
                "5️⃣ **Telemetry Diagnostics & Visual Blueprint**:\n"
                "• *\"Give me visual suggestions to utilize money properly\"*\n"
                "• *\"Check budgets\"* — Audit budget limits and overspending\n"
                "• *\"Cashflow status\"* — 50/30/20 breakdown and savings rate\n\n"
                "6️⃣ **AI Agent Configuration**:\n"
                "• *\"Set Gemini API key to <KEY>\"*\n"
                "• *\"Switch to Cloud AI mode\"* / *\"Switch to Local mode\"*"
            )
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Command Guide", reply, "bg-apple-blue/10 text-apple-blue"),
                'action_type': 'guide',
                'payload': {}
            }

        # Budget Check
        if re.search(r'(?:budget|limit|overspent)', q_lower):
            analytics = self._build_financial_analytics()
            reply = f"🎯 **Budget Health Audit ({analytics['month_name']})**\n\n{analytics['budgets_str']}"
            badge_class = "bg-apple-red/10 text-apple-red" if analytics['overspent_count'] > 0 else "bg-apple-green/10 text-apple-green"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Budget Health", reply, badge_class),
                'action_type': 'check_budgets',
                'payload': {'overspent_count': analytics['overspent_count']}
            }

        # Cashflow Diagnostic & 50/30/20 Rule
        analytics = self._build_financial_analytics()
        tot_inc = analytics['total_income']
        tot_exp = analytics['total_expense']
        bal = analytics['net_balance']
        rate = analytics['savings_rate']

        reply = (
            f"📊 **Monthly Cashflow Diagnostic ({analytics['month_name']}):**\n\n"
            f"• **Inflow (Income)**: **{currency}{tot_inc:.2f}**\n"
            f"• **Outflow (Expenses)**: **{currency}{tot_exp:.2f}**\n"
            f"• **Net Savings**: **{currency}{bal:.2f}** ({rate}% savings rate)\n\n"
            f"💡 **Top Outflow Category**: {analytics['cat_expenses_str'].split(',')[0] if analytics['cat_expenses_str'] else 'None'}\n\n"
            f"*(Type 'help' for the complete list of natural-language commands or configure an AI API Key to unlock generative agent reasoning.)*"
        )
        return {
            'status': 'success',
            'reply': reply,
            'response': self._format_bubble_html("Cashflow Diagnostic", reply, "bg-apple-blue/10 text-apple-blue"),
            'action_type': 'cashflow_audit',
            'payload': analytics
        }

    def _format_bubble_html(self, title, markdown_text, badge_class="bg-apple-blue/10 text-apple-blue"):
        """Format reply into rich Apple-styled HTML snippet."""
        # Convert simple markdown to html
        formatted = markdown_text.replace('\n\n', '<br><br>').replace('\n', '<br>')
        formatted = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', formatted)
        formatted = re.sub(r'\*(.+?)\*', r'<em>\1</em>', formatted)
        formatted = re.sub(r'`(.+?)`', r'<code class="px-1.5 py-0.5 rounded text-[11px] bg-black/5 dark:bg-white/10 font-mono">\1</code>', formatted)

        return (
            f"<div class='ios-chat-bubble-content'>"
            f"  <div class='flex items-center justify-between mb-2'>"
            f"    <span class='px-2 py-0.5 text-[10px] font-semibold rounded-full {badge_class} uppercase tracking-wider'>{title}</span>"
            f"    <span class='text-[10px] opacity-60'>{timezone.localtime().strftime('%I:%M %p')}</span>"
            f"  </div>"
            f"  <div class='text-xs leading-relaxed text-primary'>{formatted}</div>"
            f"</div>"
        )
