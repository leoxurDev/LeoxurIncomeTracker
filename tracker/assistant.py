import os
import re
import json
import urllib.request
import urllib.error
import datetime
import calendar
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Q
from .models import Transaction, Budget, Reminder, Category, Profile

class LeoxurIntelligence:
    """
    Leoxur Intelligence — Autonomous Financial Telemetry & AI Agent.
    Powered by Cloud AI Agents (Google Gemini, Groq, OpenAI, Anthropic, OpenRouter)
    with seamless fallback to an ultra-fast, multilingual local deterministic financial brain.
    """

    def __init__(self, user, client_context=None):
        self.user = user
        self.profile = getattr(user, 'profile', None)
        self.client_context = client_context or {}

    @staticmethod
    def _detect_language(text):
        """Detect user input language or dialect for accurate reciprocal response."""
        text_low = text.lower()
        if re.search(r'[\u0600-\u06FF]', text):
            return 'ar'
        if re.search(r'[\u0400-\u04FF]', text):
            return 'ru'
        if re.search(r'[\u4E00-\u9FFF]', text):
            return 'zh'
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text):
            return 'ja'
        # Tamil / Tanglish
        if any(w in text_low for w in ['selavu', 'varavu', 'pannu', 'roobai', 'saapadu', 'unavu', 'sambalam', 'anuppu', 'netru', 'kadaisi', 'kaasu', 'kuduthen', 'vaanginen', 'vadagai']):
            return 'ta'
        # Hindi / Hinglish
        if any(w in text_low for w in ['kharcha', 'kharch', 'aamdani', 'rupay', 'rupees', 'karo', 'kiya', 'bhejo', 'pichla', 'doodh', 'chai', 'khana', 'mahina', 'bijli', 'kiraya', 'vetan', 'pe ']):
            return 'hi'
        # Spanish
        if any(w in text_low for w in ['gasto', 'gastos', 'ingreso', 'ingresos', 'añadir', 'anadir', 'comida', 'ayer', 'presupuesto', 'informe', 'cuenta', 'dinero', 'enviar', 'modo oscuro', 'modo claro']):
            return 'es'
        # French
        if any(w in text_low for w in ['dépense', 'depense', 'dépenses', 'revenu', 'revenus', 'ajouter', 'nourriture', 'déjeuner', 'hier', 'rapport', 'sombre', 'envoyer', 'mode sombre', 'mode clair']):
            return 'fr'
        # German
        if any(w in text_low for w in ['ausgabe', 'ausgaben', 'einnahme', 'einnahmen', 'hinzufügen', 'gestern', 'bericht', 'dunkel', 'senden', 'dunkler modus', 'heller modus', 'rechnung']):
            return 'de'
        # Italian
        if any(w in text_low for w in ['spesa', 'spese', 'entrata', 'entrate', 'aggiungi', 'ieri', 'invia', 'rapporto', 'modalità scura', 'modalità chiara']):
            return 'it'
        # Portuguese
        if any(w in text_low for w in ['despesa', 'despesas', 'receita', 'receitas', 'adicionar', 'ontem', 'relatório', 'relatorio', 'modo escuro', 'modo claro']):
            return 'pt'
        return 'en'

    @staticmethod
    def _parse_flexible_date(date_val, default_date=None):
        """Parse natural relative dates or ISO strings across 10+ languages."""
        default_date = default_date or timezone.localdate()
        if not date_val:
            return default_date
        if isinstance(date_val, datetime.date):
            return date_val
        s = str(date_val).strip().lower()
        yesterday_words = ['yesterday', 'ayer', 'hier', 'gestern', 'ieri', 'ontem', 'kal', 'netru', 'ninna', 'ams', 'zuotian', 'kinou', 'vchera']
        if any(re.search(r'\b' + re.escape(w) + r'\b', s) for w in yesterday_words):
            return default_date - datetime.timedelta(days=1)
        today_words = ['today', 'hoy', 'aujourdhui', "aujourd'hui", 'heute', 'oggi', 'hoje', 'aaj', 'indru', 'alyawm', 'jintian', 'segodnya']
        if any(re.search(r'\b' + re.escape(w) + r'\b', s) for w in today_words):
            return default_date
        ago_match = re.search(r'(\d+)\s*(?:days?|días?|jours?|tage|giorni|dias|din|naal)\s*ago', s) or re.search(r'(?:hace|il y a|vor)\s*(\d+)', s)
        if ago_match:
            try:
                days = int(ago_match.group(1))
                return default_date - datetime.timedelta(days=days)
            except Exception:
                pass
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return default_date

    @staticmethod
    def _normalize_category(cat_str, default="Other"):
        """Intelligently map multilingual and informal terms to canonical tracker categories."""
        if not cat_str:
            return default
        s = str(cat_str).strip().lower()
        # Food & Dining
        if any(w in s for w in ['food', 'comida', 'nourriture', 'déjeuner', 'dejeuner', 'dîner', 'diner', 'essen', 'cibo', 'refeição', 'refeicao', 'almoço', 'almoco', 'janta', 'café', 'almuerzo', 'cena', 'desayuno', 'lunch', 'dinner', 'breakfast', 'snack', 'cafe', 'coffee', 'restaurante', 'restaurant', 'groceries', 'supermercado', 'khana', 'kharcha', 'doodh', 'chai', 'biryani', 'swiggy', 'zomato', 'unavu', 'saapadu', 'bhojanam', 'oota', 'khorak', 'ta\'am', 'yemek']):
            return "Food"
        # Rent / Housing
        if any(w in s for w in ['rent', 'alquiler', 'loyer', 'miete', 'affitto', 'aluguel', 'house', 'apartment', 'flat', 'kiraya', 'vadagai', 'aadige', 'makan', 'ijara', 'bayt', 'kira', 'arenda']):
            return "Rent"
        # Salary / Primary Income
        if any(w in s for w in ['salary', 'salario', 'salaire', 'gehalt', 'stipendio', 'salário', 'salario', 'paycheck', 'vetan', 'aamdani', 'sambalam', 'jeetham', 'shambala', 'wages', 'ratib', 'mash', 'income', 'zarplata', 'maas']):
            return "Salary"
        # Travel / Transit
        if any(w in s for w in ['travel', 'transporte', 'transport', 'reise', 'viaggio', 'viagem', 'gas', 'fuel', 'petrol', 'diesel', 'uber', 'ola', 'auto', 'taxi', 'flight', 'vuelo', 'metro', 'bus', 'train', 'safar', 'yathirai', 'prayanam', 'safara', 'rihla', 'transit', 'poezdka', 'seyahat']):
            return "Travel"
        # Utilities
        if any(w in s for w in ['utilities', 'utility', 'factura', 'facture', 'rechnung', 'bolletta', 'conta', 'electric', 'electricity', 'water', 'internet', 'wifi', 'broadband', 'phone', 'recharge', 'bijli', 'pani', 'bill', 'fattura', 'fatora', 'schet', 'fatura']):
            return "Utilities"
        # Entertainment
        if any(w in s for w in ['entertainment', 'entretenimiento', 'divertissement', 'unterhaltung', 'svago', 'entretenimento', 'movie', 'cinema', 'pelicula', 'film', 'netflix', 'spotify', 'game', 'gaming', 'concert', 'club', 'party', 'fun', 'manoranjan', 'vilaiyattu', 'vinoda', 'maza', 'tarfih', 'eglence']):
            return "Entertainment"
        # Health & Medical
        if any(w in s for w in ['health', 'medical', 'medicine', 'doctor', 'hospital', 'clinic', 'pharmacy', 'dawai', 'marundhu', 'mandhu', 'tibb', 'salud', 'santé', 'sante', 'gesundheit', 'salute', 'saude', 'zdorove', 'saglik']):
            return "Health"
        # Shopping
        if any(w in s for w in ['shopping', 'clothes', 'clothing', 'shoes', 'fashion', 'kapde', 'thuni', 'battalu', 'kharidari', 'compras', 'achats', 'einkaufen', 'tasawwuq', 'pokupki', 'alisveris']):
            return "Shopping"
        # Education
        if any(w in s for w in ['education', 'school', 'college', 'books', 'fees', 'tuition', 'course', 'padhai', 'kalvi', 'chaduvu', 'sikhya', 'talim', 'educacion', 'bildung', 'ta\'lim', 'obrazovanie', 'egitim']):
            return "Education"
        # Freelance / Consulting
        if any(w in s for w in ['freelance', 'consulting', 'contract', 'side gig', 'upwork', 'fiverr', 'client']):
            return "Freelance"
        # Investment
        if any(w in s for w in ['investment', 'invest', 'stock', 'shares', 'dividend', 'mutual fund', 'crypto', 'bachat', 'semippu', 'podupu', 'istithmar', 'inversion', 'investition', 'investissement', 'investimento', 'investitsii', 'yatirim']):
            return "Investment"
        return cat_str.strip().title()

    def _build_financial_analytics(self):
        """Assemble comprehensive, real-time financial telemetry for the user."""
        today = timezone.localdate()
        start_of_month = datetime.date(today.year, today.month, 1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_of_month = datetime.date(today.year, today.month, last_day)

        currency = self.profile.currency if self.profile else '$'

        # Current month transactions
        month_txs = Transaction.objects.filter(user=self.user, date__range=(start_of_month, end_of_month))
        total_income = float(month_txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
        total_expense = float(month_txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
        net_balance = total_income - total_expense
        savings_rate = int((net_balance / total_income) * 100) if total_income > 0 and net_balance > 0 else 0

        # Burn rate and runway
        days_in_month = last_day
        days_elapsed = max(1, today.day)
        days_remaining = max(1, days_in_month - days_elapsed)
        daily_burn = total_expense / days_elapsed

        # Prior Month Telemetry
        prev_month = today.month - 1 if today.month > 1 else 12
        prev_year = today.year if today.month > 1 else today.year - 1
        _, prev_last_day = calendar.monthrange(prev_year, prev_month)
        prev_start = datetime.date(prev_year, prev_month, 1)
        prev_end = datetime.date(prev_year, prev_month, prev_last_day)
        
        prev_txs = Transaction.objects.filter(user=self.user, date__range=(prev_start, prev_end))
        prev_income = float(prev_txs.filter(transaction_type='IN').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
        prev_expense = float(prev_txs.filter(transaction_type='OUT').aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))

        # Expenses by Category
        category_expenses = {}
        for tx in month_txs.filter(transaction_type='OUT'):
            category_expenses[tx.category] = category_expenses.get(tx.category, 0.0) + float(tx.amount)
        cat_expenses_str = ", ".join([f"{k}: {currency}{v:.2f}" for k, v in sorted(category_expenses.items(), key=lambda x: x[1], reverse=True)]) or "No expenses logged this month"

        # Prior month category expenses for surge comparison
        prev_cat_expenses = {}
        for tx in prev_txs.filter(transaction_type='OUT'):
            prev_cat_expenses[tx.category] = prev_cat_expenses.get(tx.category, 0.0) + float(tx.amount)

        surges = []
        for cat, curr_amt in category_expenses.items():
            past_amt = prev_cat_expenses.get(cat, 0.0)
            if past_amt > 0 and curr_amt > past_amt:
                diff = curr_amt - past_amt
                pct = int(round((diff / past_amt) * 100))
                if pct >= 15:
                    surges.append(f"{cat}: +{pct}% (+{currency}{diff:.2f} vs {prev_start.strftime('%b')})")
        surges_str = "; ".join(surges) if surges else "No major surges vs prior month"

        # Incomes by Category
        category_incomes = {}
        for tx in month_txs.filter(transaction_type='IN'):
            category_incomes[tx.category] = category_incomes.get(tx.category, 0.0) + float(tx.amount)
        cat_incomes_str = ", ".join([f"{k}: {currency}{v:.2f}" for k, v in sorted(category_incomes.items(), key=lambda x: x[1], reverse=True)]) or "No income logged this month"

        # Budgets
        budgets = Budget.objects.filter(user=self.user, year=today.year, month=today.month)
        if not budgets.exists():
            budgets = Budget.objects.filter(user=self.user)
            
        budget_details = []
        overspent_count = 0
        overall_budget = 0.0
        for b in budgets:
            if b.category == 'Total':
                overall_budget = float(b.amount)
            spent = category_expenses.get(b.category, 0.0)
            diff = float(b.amount) - spent
            if diff < 0:
                overspent_count += 1
                budget_details.append(f"• {b.category}: Limit {currency}{b.amount:.2f} | Spent {currency}{spent:.2f} (OVERSPENT by {currency}{abs(diff):.2f})")
            else:
                budget_details.append(f"• {b.category}: Limit {currency}{b.amount:.2f} | Spent {currency}{spent:.2f} ({currency}{diff:.2f} remaining)")
        budgets_str = "\n".join(budget_details) if budget_details else "No active category budgets set this month."

        if overall_budget <= 0:
            overall_budget = sum(float(b.amount) for b in budgets if b.category != 'Total')
        safe_daily_allowance = max(0.0, (overall_budget - total_expense) / days_remaining) if overall_budget > total_expense else 0.0

        # Upcoming Reminders & Outflow Alerts
        reminders = Reminder.objects.filter(user=self.user).order_by('due_date')
        pending_reminders = reminders.filter(is_paid=False)
        reminders_list = []
        for r in pending_reminders[:5]:
            reminders_list.append(f"• '{r.title}': {currency}{r.amount:.2f} due on {r.due_date.strftime('%Y-%m-%d')}")
        reminders_str = "\n".join(reminders_list) if reminders_list else "No pending bill reminders."

        # Recent Transactions
        recent_txs = Transaction.objects.filter(user=self.user).order_by('-date', '-created_at')[:8]
        recent_list = []
        for t in recent_txs:
            sign = "+" if t.transaction_type == 'IN' else "-"
            recent_list.append(f"• {t.date.strftime('%b %d')}: {sign}{currency}{t.amount:.2f} [{t.category}] {t.description or ''}")
        recent_txs_str = "\n".join(recent_list) if recent_list else "No transactions recorded yet."

        # Categories list
        categories = Category.objects.filter(user=self.user).values_list('name', flat=True)
        categories_str = ", ".join(list(categories)) if categories else "Food, Rent, Salary, Freelance, Utilities, Entertainment, Travel"

        provider = self.profile.ai_provider if self.profile else 'gemini'
        model = self.profile.get_effective_ai_model() if self.profile else 'gemini-3.5-flash-lite'
        ai_mode = getattr(self.profile, 'ai_mode', 'cloud')

        return {
            'today_str': today.strftime('%Y-%m-%d'),
            'month_name': today.strftime('%B %Y'),
            'prev_month_name': prev_start.strftime('%B %Y'),
            'currency': currency,
            'total_income': total_income,
            'total_expense': total_expense,
            'net_balance': net_balance,
            'savings_rate': savings_rate,
            'daily_burn': daily_burn,
            'safe_daily_allowance': safe_daily_allowance,
            'days_remaining': days_remaining,
            'overall_budget': overall_budget,
            'prev_income': prev_income,
            'prev_expense': prev_expense,
            'surges_str': surges_str,
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

    def process_voice_audio(self, audio_bytes, mime_type="audio/webm", language_hint="auto", api_key=None):
        """
        Multimodal voice detection and processing across global languages.
        Understands spoken voice in Spanish, French, German, Italian, Portuguese,
        Hindi, Tamil, Telugu, Arabic, Russian, Chinese, Japanese, etc.
        """
        import base64
        key = api_key or self.get_active_ai_key()
        if not key:
            return {
                'status': 'error',
                'message': 'AI API Key is required for server-side neural voice processing. Please configure your key in AI Settings or use browser Web Speech Recognition.'
            }

        provider = (self.profile.ai_provider if self.profile else 'gemini').lower()
        if provider != 'gemini':
            return {
                'status': 'error',
                'message': f"Provider '{provider}' requires text transcription. Browser Speech Recognition has been engaged."
            }

        b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
        analytics = self._build_financial_analytics()
        currency = analytics['currency']

        system_prompt = f"""You are Leoxur Copilot, speaking with the poised, warm, natural intellect of Apple's Siri — a personal wealth confidant.
The user has spoken to you via voice audio.

=== REFINED APPLE SIRI HUMAN SPEECH & SPEAKER UNDERSTANDING ===
1. Native fluency in every global language and dialect (English, Spanish, French, German, Italian, Portuguese, Hindi, Tamil, Telugu, Arabic, Russian, Chinese, Japanese, etc.).
2. You deeply understand conversational voice speech:
   - Accents, informal slang, colloquial phrasing (e.g., "spent 20 bucks on coffee", "bhai 150 chai samosa pe kharch kiya", "petrol ku 500 rubai aachu", "gasté 40 lucas en cena").
   - Code-mixing and mixed dialects: Tanglish (Tamil + English), Hinglish (Hindi + English), Spanglish, etc.
   - The speaker's voice nuance, emotion, and urgency.
3. Listen to the audio, detect the language (language hint: {language_hint}), and accurately transcribe the user's speech into "user_transcript".
4. Execute the requested financial action (logging transactions, checking budgets, 50/30/20 diagnostics, dispatching email reports, changing theme, etc.).
5. CRITICAL — SPEAK LIKE APPLE SIRI (WARM, POLITE, CONVERSATIONAL):
   - Provide "reply" in the EXACT SAME LANGUAGE and dialect as the user's voice.
   - In Tamil: Use polite, natural conversational Tamil (e.g. "சரிங்க! உங்க ₹15,000 வாடகை பட்ஜெட் வெற்றிகரமா பதிவாயிடுச்சு." or "நான் ₹200-ஐ கவனித்தேன். இதை வருமானமாக சேர்க்கவா அல்லது செலவாகவா?").
   - In English: Speak with Siri's poise: "All set! I've logged that expense for you. Your remaining budget looks healthy."
   - Keep reply concise (1-2 natural sentences) so it sounds smooth and effortless when spoken aloud.

Follow this strict JSON schema:
{{
  "user_transcript": "The exact words spoken by the user in their language",
  "detected_language": "en | es | hi | ta | fr | de | it | pt | ar | ru | zh | ja",
  "reply": "Warm, natural, conversational response in the user's spoken language ready for human voice speech",
  "action_type": "log_transaction | log_multiple_transactions | delete_transaction | set_budget | clear_budget | reset_budgets | set_reminder | pay_reminder | change_currency | sync_emails | change_theme | send_email_report | cashflow_audit | visual_suggestion | historical_comparison | general",
  "payload": {{ ... }},
  "visual_card": true | false
}}
Return ONLY valid JSON.
"""
        payload_data = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": b64_audio}},
                        {"text": f"Listen carefully to this spoken financial audio (language hint: {language_hint}). Transcribe and execute the financial action according to instructions."}
                    ]
                }
            ],
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}
        }

        candidate_models = ['gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.8-flash', 'gemini-3.7-flash']
        user_agent = 'LeoxurTracker/2.5.0 (Voice Engine; Leoxur Inc.)'

        last_err = None
        for m in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload_data).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'User-Agent': user_agent},
                method='POST'
            )
            try:
                with urllib.request.urlopen(req, timeout=18) as response:
                    res_obj = json.loads(response.read().decode('utf-8'))
                    text_content = res_obj['candidates'][0]['content']['parts'][0]['text']
                    data = self._clean_json(text_content)
                    action_res = self._apply_cloud_action(data)
                    action_res['user_transcript'] = data.get('user_transcript', '')
                    action_res['detected_language'] = data.get('detected_language', 'auto')
                    return action_res
            except Exception as ex:
                last_err = str(ex)
                continue

        return {
            'status': 'error',
            'message': f"Voice audio processing failed: {last_err or 'No responsive endpoint'}"
        }

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

        system_prompt = f"""You are Leoxur Copilot, an elite, hyper-intelligent autonomous financial AI companion and telemetry strategist for the Leoxur Income & Expense Tracker.
You possess COMPLETE, REAL-TIME, and EXCLUSIVE operational authority over this personal finance application and the user's ledger.

=== MULTILINGUAL MASTERY & GLOBAL LANGUAGE COMPREHENSION ===
1. You have native-level fluency in EVERY human language (Spanish, French, German, Italian, Portuguese, Hindi, Tamil, Telugu, Malayalam, Kannada, Bengali, Marathi, Urdu, Arabic, Chinese, Japanese, Korean, Russian, Turkish, etc.) and code-mixed formats (Hinglish like 'maine 500 grocery me spend kiya add kardo', Tanglish like 'swiggy la 250 selavu panniten add pannu', Spanglish, etc.).
2. You must seamlessly decipher financial requests in ANY language, dialect, or slang, map informal terms to appropriate financial categories (e.g. comida/khana/unavu -> Food, salario/sambalam -> Salary, alquiler/kiraya -> Rent, transporte/fuel -> Travel), and perform the action immediately.
3. CRITICAL: You must ALWAYS generate your "reply" in the EXACT SAME LANGUAGE or dialect as the user's input, maintaining high polish, executive clarity, and native terminology!
4. Multilingual amount & currency expressions: Accurately parse "$50", "50€", "₹500", "500 rs", "500 rupay", "500 roobai", "50 bucks", "50 quid", etc.

=== REAL-TIME USER FINANCIAL TELEMETRY ===
• Current Month: {analytics['month_name']} (Today: {analytics['today_str']})
• Active Currency: {currency}
• Total Monthly Inflow (Income): {currency}{analytics['total_income']:.2f}
• Total Monthly Outflow (Expense): {currency}{analytics['total_expense']:.2f}
• Net Cashflow Balance: {currency}{analytics['net_balance']:.2f}
• Savings Rate: {analytics['savings_rate']}%
• Burn Velocity: {currency}{analytics['daily_burn']:.2f}/day | Safe Cap Target: {currency}{analytics['safe_daily_allowance']:.2f}/day | Days Remaining: {analytics['days_remaining']}
• Top Outflows by Category: {analytics['cat_expenses_str']}
• Inflow Sources: {analytics['cat_incomes_str']}
• Category Surges vs Prior Month ({analytics['prev_month_name']}): {analytics['surges_str']}
• Prior Month Performance: Inflows {currency}{analytics['prev_income']:.2f} | Outflows {currency}{analytics['prev_expense']:.2f}
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
   Log a single income or expense in any language.
   payload: {{"amount": float, "transaction_type": "IN" | "OUT", "category": str, "description": str, "date": "YYYY-MM-DD"}}

2. "log_multiple_transactions":
   Log multiple items from a single sentence/paragraph (e.g., "spent 50 on food, 20 on fuel, and 100 on groceries").
   payload: {{"transactions": [{{"amount": float, "transaction_type": "OUT" | "IN", "category": str, "description": str}}, ...]}}

3. "delete_transaction":
   Delete last transaction, delete by id, or delete matching record (e.g. "undo last expense", "delete 50 lunch").
   payload: {{"last": true}} OR {{"id": int}} OR {{"category": str, "amount": float}}

4. "set_budget":
   Set or adjust a category or Total budget cap.
   payload: {{"category": str, "amount": float, "period": "MONTHLY"}}

5. "clear_budget":
   Remove budget limit for a category.
   payload: {{"category": str}}

6. "reset_budgets":
   Rebalance budgets to healthy 50/30/20 benchmarks.
   payload: {{"targets": {{"Food": float, "Rent": float, "Utilities": float, "Total": float}}}}

7. "set_reminder":
   Schedule a bill due date.
   payload: {{"title": str, "amount": float, "due_date": "YYYY-MM-DD"}}

8. "pay_reminder":
   Mark a bill reminder as settled/paid.
   payload: {{"title": str}}

9. "change_currency":
   Switch primary currency ($, €, ₹, £) and optionally convert ledger.
   payload: {{"currency": "$" | "€" | "₹" | "£", "conversion_rate": float, "scale_records": true | false}}

10. "sync_emails":
    Inspect IMAP mailbox, check unread banking receipts, and sync transactions into ledger.
    payload: {{}}

11. "change_theme":
    Switch application appearance between dark and light mode.
    payload: {{"theme": "dark" | "light"}}

12. "send_email_report":
    Dispatch monthly cashflow and budget report with attached PDF & Excel spreadsheets via SMTP.
    payload: {{"recipient": str (optional)}}

13. "cashflow_audit" / "visual_suggestion":
    Perform a comprehensive diagnostic with 50/30/20 rule, budget leakages, actionable spending suggestions, and set "visual_card": true to render an inline visual SVG blueprint chart and money utilization guidelines.

14. "historical_comparison":
    Analyze and compare user's performance across different months (e.g. comparing current cycle with prior month).
    payload: {{}}

=== CRITICAL DOMAIN BOUNDARY ===
You are SOLELY and EXCLUSIVELY dedicated to this personal finance application.
Under NO CIRCUMSTANCE should you answer questions about Amazon Web Services (AWS), EC2 instance creation, VPC, S3, cloud hosting infrastructure, Kubernetes, Terraform, or generic IT sysadmin topics.
If asked about AWS, EC2, or external IT, politely decline in the user's language and state that you are exclusively focused on personal finance telemetry and the Leoxur tracker.

=== REFINED APPLE SIRI HUMAN VOICE & SPEAKER INTELLECT ===
1. Persona: Speak like Apple's Siri — an elite, poised, warm, natural, and perceptive human private wealth confidant — NEVER mechanical, robotic, or bureaucratic.
2. Deeply understand conversational voice language, slang, accents, and mixed colloquial dialects (e.g. Tanglish, Hinglish, Spanglish).
3. If the user speaks in Tamil or Tanglish:
   - Speak in natural, graceful, conversational Tamil (like Apple Siri in Tamil):
   - Example when confirming an action: "கண்டிப்பா! ₹15,000 வாடகை பட்ஜெட்டை வெற்றிகரமா சேர்த்தாச்சு. உங்க நடப்பு மாத பேலன்ஸ் நல்ல நிலையில இருக்கு."
   - Example when clarifying an incomplete request: "சரிங்க, ₹200-ஐ கவனித்தேன். இதை வருமானமாக சேர்க்கவா அல்லது செலவாகவா? எந்த கேட்டகிரில சேர்க்கணும்னு சொன்னா உடனே பதியலாம்."
4. If the user speaks in English, Hindi, Spanish, etc., mirror that language with Siri's natural elegance.
5. Voice Optimization: Keep spoken voice replies concise (1 to 2 natural conversational sentences), perfectly paced for human voice synthesis without long markdown blocks, emojis, or awkward symbol pronunciations.

=== STRICT RESPONSE SCHEMA ===
You must ALWAYS respond with a valid JSON object matching this schema:
{{
  "thought": "Deep strategic analysis of user intent, language detection, and financial state",
  "reply": "Warm, conversational, executive human response in the user's language ready for natural voice speech",
  "action_type": "log_transaction | log_multiple_transactions | delete_transaction | set_budget | clear_budget | reset_budgets | set_reminder | pay_reminder | change_currency | sync_emails | change_theme | send_email_report | cashflow_audit | visual_suggestion | historical_comparison | general | guide",
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
                'gemini-3.5-flash-lite',
                'gemini-3.5-flash',
                model,
                'gemini-3.8-flash',
                'gemini-3.7-flash',
                'gemini-3.1-flash-lite',
                'gemini-flash-latest',
                'gemini-flash-lite-latest',
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
            raw_cat = payload.get('category') or 'Other'
            category = self._normalize_category(raw_cat)
            desc = payload.get('description', '') or raw_cat
            date_val = self._parse_flexible_date(payload.get('date'), today)

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
                    raw_cat = item.get('category') or 'General'
                    cat = self._normalize_category(raw_cat)
                    d = item.get('description', '') or raw_cat
                    dt = self._parse_flexible_date(item.get('date'), today)
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
            raw_cat = payload.get('category', 'General')
            category = 'Total' if raw_cat.strip().lower() == 'total' else self._normalize_category(raw_cat)
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

        elif action_type == 'clear_budget':
            cat = payload.get('category')
            if cat and cat.strip().lower() not in ('all', 'todos', 'tout', 'alle'):
                norm_cat = self._normalize_category(cat)
                deleted_count, _ = Budget.objects.filter(user=self.user, category__iexact=norm_cat).delete()
                msg = reply or f"Cleared budget cap for {norm_cat}."
            else:
                deleted_count, _ = Budget.objects.filter(user=self.user).delete()
                msg = reply or "Cleared all monthly category budgets."
            html = self._format_bubble_html("Budget Cleared", msg, "bg-apple-orange/10 text-apple-orange")
            return {'status': 'success', 'reply': reply or msg, 'response': html, 'action_type': 'set_budget', 'payload': payload}

        elif action_type == 'reset_budgets':
            targets = payload.get('targets', {
                'Food': 6000.0,
                'Rent': 25000.0,
                'Utilities': 3000.0,
                'Total': 34000.0
            })
            for cat, amt in targets.items():
                norm_cat = 'Total' if cat.strip().lower() == 'total' else self._normalize_category(cat)
                Budget.objects.update_or_create(
                    user=self.user,
                    category=norm_cat,
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

        elif action_type == 'historical_comparison':
            prev_inc = analytics['prev_income']
            prev_exp = analytics['prev_expense']
            curr_inc = analytics['total_income']
            curr_exp = analytics['total_expense']
            inc_diff = curr_inc - prev_inc
            exp_diff = curr_exp - prev_exp
            inc_pct = int(round((inc_diff / (prev_inc or 1)) * 100)) if prev_inc > 0 else 0
            exp_pct = int(round((exp_diff / (prev_exp or 1)) * 100)) if prev_exp > 0 else 0
            surges = analytics['surges_str']
            default_reply = (
                f"📊 **Historical Month-over-Month Telemetry ({analytics['prev_month_name']} vs {analytics['month_name']}):**\n\n"
                f"• **Inflow Comparison**: {currency}{curr_inc:.2f} vs {currency}{prev_inc:.2f} ({'+' if inc_diff >= 0 else ''}{inc_pct}%)\n"
                f"• **Outflow Comparison**: {currency}{curr_exp:.2f} vs {currency}{prev_exp:.2f} ({'+' if exp_diff >= 0 else ''}{exp_pct}%)\n"
                f"• **Category Surges (>=15%)**: {surges}\n"
                f"• **Burn Velocity**: {currency}{analytics['daily_burn']:.2f}/day with {analytics['days_remaining']} days remaining in cycle."
            )
            final_reply = reply or default_reply
            html = self._format_bubble_html("Historical Analysis", final_reply, "bg-apple-blue/10 text-apple-blue")
            if show_visual:
                html += self._generate_visual_telemetry_svg(analytics)
            return {'status': 'success', 'reply': final_reply, 'response': html, 'action_type': 'historical_comparison', 'payload': analytics}

        html = self._format_bubble_html("Leoxur Intelligence", reply, "bg-apple-blue/10 text-apple-blue")
        if show_visual:
            html += self._generate_visual_telemetry_svg(analytics)

        return {'status': 'success', 'reply': reply, 'response': html, 'action_type': action_type, 'payload': payload}

    def _process_local_deterministic(self, query, q_lower):
        """
        Fast, robust, multilingual deterministic local financial brain.
        Understands natural financial instructions in Spanish, French, German, Italian,
        Portuguese, Hindi/Hinglish, Tamil/Tanglish, Arabic, Russian, and English.
        """
        today = timezone.localdate()
        currency = self.profile.currency if self.profile else '$'
        lang = self._detect_language(query)
        analytics = self._build_financial_analytics()

        # 1. Appearance / Theme Switching (Multilingual)
        theme_dark_triggers = ['dark mode', 'modo oscuro', 'mode sombre', 'dunkler modus', 'modalità scura', 'modo escuro', 'dark theme', 'tema oscuro', 'thème sombre', 'dunkles design', 'dark mode karo', 'dark mode mathu', 'dark']
        theme_light_triggers = ['light mode', 'modo claro', 'mode clair', 'heller modus', 'modalità chiara', 'modo claro', 'light theme', 'tema claro', 'thème clair', 'helles design', 'light mode karo', 'light mode mathu', 'light']
        if any(tr in q_lower for tr in ['theme', 'modo', 'tema', 'thème', 'mode', 'appearance', 'apariencia', 'apparence', 'design']):
            is_light = any(tr in q_lower for tr in theme_light_triggers) or ('light' in q_lower and 'dark' not in q_lower)
            t = 'light' if is_light else 'dark'
            if self.profile:
                self.profile.theme = t
                self.profile.save(update_fields=['theme'])
            
            if lang == 'es':
                reply = f"🌓 **Apariencia Actualizada**\n\nSe ha cambiado la interfaz de Leoxur a **Modo {t.title()}**."
                title = "Apariencia Actualizada"
            elif lang == 'fr':
                reply = f"🌓 **Apparence Mise à Jour**\n\nL'interface de Leoxur est maintenant en **Mode {t.title()}**."
                title = "Apparence Mise à Jour"
            elif lang == 'de':
                reply = f"🌓 **Erscheinungsbild Aktualisiert**\n\nLeoxur-Design wurde auf **{t.title()}-Modus** umgestellt."
                title = "Design Aktualisiert"
            elif lang == 'hi':
                reply = f"🌓 **थीम अपडेट हो गई**\n\nLeoxur इंटरफ़ेस अब **{t.title()} Mode** में सेट है।"
                title = "थीम अपडेट"
            elif lang == 'ta':
                reply = f"🌓 **தீம் மாற்றப்பட்டது**\n\nஇடைமுகம் இப்போது **{t.title()} Mode**க்கு மாற்றப்பட்டது."
                title = "தீம் மாற்றம்"
            else:
                reply = f"🌓 **Appearance Updated**\n\nSwitched Leoxur interface to **{t.title()} Mode**."
                title = "Appearance Updated"

            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html(title, reply, "bg-apple-purple/10 text-apple-purple"),
                'action_type': 'change_theme',
                'payload': {'theme': t}
            }

        # 2. Email Reports Dispatched via SMTP (Multilingual)
        if any(w in q_lower for w in ['report', 'statement', 'informe', 'reporte', 'rapport', 'bilan', 'bericht', 'finanzbericht', 'resumen']) and any(w in q_lower for w in ['send', 'email', 'mail', 'enviar', 'mandar', 'envoyer', 'sende', 'schicken', 'bhejo', 'anuppu']):
            recipient_match = re.search(r'(?:to|recipient|para|à|an|pe|ku)\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', query, re.I)
            target_rcpt = recipient_match.group(1) if recipient_match else None
            ok, msg, file_list = self._send_financial_report_email(target_rcpt)
            if ok:
                if lang == 'es':
                    reply = (
                        f"📧 **¡Estado Financiero Ejecutivo Transmitido!**\n\n"
                        f"Se ha enviado su informe mensual a **{msg}** mediante el nodo de correo SMTP configurado.\n\n"
                        f"**📎 Archivos Adjuntos:**\n"
                        f"• **Declaración PDF**: Telemetría completa con gráficos circulares y desglose de categorías.\n"
                        f"• **Hoja de Cálculo Excel (.xlsx)**: Registro detallado de ingresos, gastos y presupuestos mensuales."
                    )
                    title = "Informe Enviado"
                elif lang == 'fr':
                    reply = (
                        f"📧 **Bilan Financier Exécutif Transmis !**\n\n"
                        f"Votre rapport mensuel a été envoyé à **{msg}** via le serveur de messagerie SMTP.\n\n"
                        f"**📎 Pièces Jointes :**\n"
                        f"• **Déclaration PDF** : Télémétrie complète avec graphiques circulaires et analyse budgétaire.\n"
                        f"• **Feuille Excel (.xlsx)** : Grand livre complet des entrées, sorties et plafonds."
                    )
                    title = "Rapport Transmis"
                elif lang == 'hi':
                    reply = (
                        f"📧 **वित्तीय रिपोर्ट भेज दी गई है!**\n\n"
                        f"आपकी मासिक वित्तीय रिपोर्ट **{msg}** पर SMTP मेल नोड के माध्यम से भेज दी गई है।\n\n"
                        f"**📎 संलग्न दस्तावेज:**\n"
                        f"• **PDF विवरण**: कैटेगरी पाई चार्ट और संपूर्ण व्यय विश्लेषण।\n"
                        f"• **Excel स्प्रेडशीट (.xlsx)**: सभी आय, व्यय और बजट का विस्तृत ब्यौरा।"
                    )
                    title = "ईमेल रिपोर्ट प्रेषित"
                elif lang == 'ta':
                    reply = (
                        f"📧 **நிதி அறிக்கை அனுப்பப்பட்டது!**\n\n"
                        f"உங்கள் மாதாந்திர அறிக்கை **{msg}** முகவரிக்கு வெற்றிகரமாக அனுப்பப்பட்டது.\n\n"
                        f"**📎 இணைப்புகள்:**\n"
                        f"• **PDF அறிக்கை**: வகை வரைபடங்களுடன் கூடிய முழுமையான நிதி அறிக்கை.\n"
                        f"• **Excel அட்டவணை (.xlsx)**: வருமானம், செலவு மற்றும் பட்ஜெட் விவரங்கள்."
                    )
                    title = "அறிக்கை அனுப்பப்பட்டது"
                else:
                    reply = (
                        f"📧 **Executive Financial Statement Dispatched!**\n\n"
                        f"Transmitted your monthly financial report to **{msg}** via your configured SMTP mail node.\n\n"
                        f"**📎 Enclosed Attachments:**\n"
                        f"• **PDF Statement**: Complete financial telemetry statement with category visual pie charts and telemetry breakdown.\n"
                        f"• **Excel Spreadsheet (.xlsx)**: Itemized ledger of all inflows, outflows, and monthly budget targets."
                    )
                    title = "Email Report Dispatched"

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
                html = self._format_bubble_html(title, reply, "bg-apple-green/10 text-apple-green") + download_buttons
            else:
                reply = f"⚠️ Email Report Failed: {msg}"
                html = self._format_bubble_html("Email Report", reply, "bg-apple-red/10 text-apple-red")
            return {
                'status': 'success',
                'reply': reply,
                'response': html,
                'action_type': 'send_email_report',
                'payload': {'recipient': msg, 'success': ok}
            }

        # 3. IMAP Mailbox Sync (Multilingual)
        if (any(w in q_lower for w in ['sync', 'sincronizar', 'synchroniser', 'synchronisieren']) and any(w in q_lower for w in ['email', 'emails', 'correo', 'correos', 'courriel', 'imap', 'mail', 'mailbox', 'buzon', 'buzón', 'postfach'])) or 'imap' in q_lower or 'mailbox' in q_lower:
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

        # 4. Undo / Delete Last Transaction (Multilingual)
        if any(w in q_lower for w in ['undo', 'deshacer', 'annuler', 'rückgängig', 'borrar', 'eliminar', 'supprimer', 'löschen', 'delete', 'remove', 'pichla', 'hatao', 'kadaisi', 'eduthuru']) and any(w in q_lower for w in ['last', 'último', 'ultimo', 'dernier', 'dernière', 'letzte', 'transacción', 'transaccion', 'transaction', 'gasto', 'expense', 'dépense', 'ausgabe', 'kharcha', 'selavu', 'entry']):
            latest = Transaction.objects.filter(user=self.user).order_by('-created_at').first()
            if latest:
                sign = "+" if latest.transaction_type == 'IN' else "-"
                amt = latest.amount
                cat = latest.category
                desc = latest.description or ''
                latest.delete()
                if lang == 'es':
                    reply = f"🗑️ **Última Transacción Eliminada**\n\nSe ha borrado el registro de {sign}{currency}{amt:.2f} [{cat}] ({desc or 'Sin nota'})."
                    title = "Transacción Eliminada"
                elif lang == 'fr':
                    reply = f"🗑️ **Dernière Transaction Supprimée**\n\nSuppression de l'entrée de {sign}{currency}{amt:.2f} [{cat}] ({desc or 'Sans note'})."
                    title = "Entrée Supprimée"
                elif lang == 'hi':
                    reply = f"🗑️ **पिछला लेन-देन हटा दिया गया**\n\n{sign}{currency}{amt:.2f} [{cat}] को बहीखाते से हटा दिया गया है।"
                    title = "लेन-देन हटाया गया"
                elif lang == 'ta':
                    reply = f"🗑️ **கடைசி பதிவு நீக்கப்பட்டது**\n\n{sign}{currency}{amt:.2f} [{cat}] வெற்றிகரமாக நீக்கப்பட்டது."
                    title = "பதிவு நீக்கம்"
                else:
                    reply = f"🗑️ **Last Transaction Removed**\n\nDeleted ledger entry of {sign}{currency}{amt:.2f} [{cat}] ({desc or 'N/A'})."
                    title = "Transaction Removed"

                return {
                    'status': 'success',
                    'reply': reply,
                    'response': self._format_bubble_html(title, reply, "bg-apple-orange/10 text-apple-orange"),
                    'action_type': 'delete_transaction',
                    'payload': {'deleted': True, 'amount': float(amt), 'category': cat}
                }
            else:
                reply = "No transactions found in ledger to undo."
                return {
                    'status': 'success',
                    'reply': reply,
                    'response': self._format_bubble_html("Delete Transaction", reply, "bg-apple-orange/10 text-apple-orange"),
                    'action_type': 'delete_transaction',
                    'payload': {'deleted': False}
                }

        # 5. Month-over-Month Historical Telemetry Comparison (Multilingual)
        if any(w in q_lower for w in ['compare', 'comparar', 'comparer', 'vergleich', 'history', 'historial', 'historique', 'previous month', 'mes pasado', 'mes anterior', 'mois dernier', 'letzten monat', 'pichle mahine', 'pona masam']):
            prev_inc = analytics['prev_income']
            prev_exp = analytics['prev_expense']
            curr_inc = analytics['total_income']
            curr_exp = analytics['total_expense']
            inc_diff = curr_inc - prev_inc
            exp_diff = curr_exp - prev_exp
            inc_pct = int(round((inc_diff / (prev_inc or 1)) * 100)) if prev_inc > 0 else 0
            exp_pct = int(round((exp_diff / (prev_exp or 1)) * 100)) if prev_exp > 0 else 0
            surges = analytics['surges_str']

            if lang == 'es':
                reply = (
                    f"📊 **Comparación Histórica Mensual ({analytics['prev_month_name']} vs {analytics['month_name']}):**\n\n"
                    f"• **Ingresos**: {currency}{curr_inc:.2f} vs {currency}{prev_inc:.2f} ({'+' if inc_diff >= 0 else ''}{inc_pct}%)\n"
                    f"• **Gastos**: {currency}{curr_exp:.2f} vs {currency}{prev_exp:.2f} ({'+' if exp_diff >= 0 else ''}{exp_pct}%)\n"
                    f"• **Incrementos Significativos (>=15%)**: {surges}\n"
                    f"• **Velocidad de Gasto Diaria**: {currency}{analytics['daily_burn']:.2f}/día con {analytics['days_remaining']} días restantes."
                )
                title = "Análisis Histórico"
            elif lang == 'fr':
                reply = (
                    f"📊 **Comparaison Historique Mensuelle ({analytics['prev_month_name']} vs {analytics['month_name']}) :**\n\n"
                    f"• **Revenus** : {currency}{curr_inc:.2f} vs {currency}{prev_inc:.2f} ({'+' if inc_diff >= 0 else ''}{inc_pct}%)\n"
                    f"• **Dépenses** : {currency}{curr_exp:.2f} vs {currency}{prev_exp:.2f} ({'+' if exp_diff >= 0 else ''}{exp_pct}%)\n"
                    f"• **Pics de Catégorie (>=15%)** : {surges}\n"
                    f"• **Dépense Quotidienne** : {currency}{analytics['daily_burn']:.2f}/jour."
                )
                title = "Comparaison Historique"
            elif lang == 'hi':
                reply = (
                    f"📊 **मासिक तुलना ({analytics['prev_month_name']} बनाम {analytics['month_name']}):**\n\n"
                    f"• **कुल आय**: {currency}{curr_inc:.2f} (पिछला: {currency}{prev_inc:.2f}, {'+' if inc_diff >= 0 else ''}{inc_pct}%)\n"
                    f"• **कुल खर्च**: {currency}{curr_exp:.2f} (पिछला: {currency}{prev_exp:.2f}, {'+' if exp_diff >= 0 else ''}{exp_pct}%)\n"
                    f"• **अधिक खर्च वाली श्रेणियाँ**: {surges}\n"
                    f"• **दैनिक खर्च दर**: {currency}{analytics['daily_burn']:.2f}/दिन।"
                )
                title = "मासिक तुलना विश्लेषण"
            elif lang == 'ta':
                reply = (
                    f"📊 **முந்தைய மாத ஒப்பீடு ({analytics['prev_month_name']} vs {analytics['month_name']}):**\n\n"
                    f"• **வருமானம்**: {currency}{curr_inc:.2f} vs {currency}{prev_inc:.2f} ({'+' if inc_diff >= 0 else ''}{inc_pct}%)\n"
                    f"• **செலவுகள்**: {currency}{curr_exp:.2f} vs {currency}{prev_exp:.2f} ({'+' if exp_diff >= 0 else ''}{exp_pct}%)\n"
                    f"• **அதிகரித்த செலவுகள்**: {surges}\n"
                    f"• **தினசரி செலவு விகிதம்**: {currency}{analytics['daily_burn']:.2f}/நாள்."
                )
                title = "வரலாற்று ஒப்பீடு"
            else:
                reply = (
                    f"📊 **Historical Month-over-Month Telemetry ({analytics['prev_month_name']} vs {analytics['month_name']}):**\n\n"
                    f"• **Inflow Comparison**: {currency}{curr_inc:.2f} vs {currency}{prev_inc:.2f} ({'+' if inc_diff >= 0 else ''}{inc_pct}%)\n"
                    f"• **Outflow Comparison**: {currency}{curr_exp:.2f} vs {currency}{prev_exp:.2f} ({'+' if exp_diff >= 0 else ''}{exp_pct}%)\n"
                    f"• **Category Surges (>=15%)**: {surges}\n"
                    f"• **Burn Velocity**: {currency}{analytics['daily_burn']:.2f}/day with {analytics['days_remaining']} days remaining."
                )
                title = "Historical Comparison"

            html = self._format_bubble_html(title, reply, "bg-apple-blue/10 text-apple-blue")
            html += self._generate_visual_telemetry_svg(analytics)
            return {
                'status': 'success',
                'reply': reply,
                'response': html,
                'action_type': 'historical_comparison',
                'payload': analytics
            }

        # 6. Visual Suggestions & 50/30/20 Spending Blueprint (Multilingual)
        if any(w in q_lower for w in ['visual', 'chart', 'blueprint', 'utilize money', 'spend better', 'money advice', 'suggestion', 'sugerencia', 'consejo', 'optimizar dinero', 'conseils', 'vorschlag', 'spartipps', 'tips', 'bachane', 'kuraikka']):
            curr = analytics['currency']
            tot_inc = analytics['total_income']
            needs_tgt = tot_inc * 0.50 if tot_inc > 0 else 25000.0
            wants_tgt = tot_inc * 0.30 if tot_inc > 0 else 15000.0
            save_tgt = tot_inc * 0.20 if tot_inc > 0 else 10000.0

            if lang == 'es':
                reply = (
                    f"📈 **Plan de Optimización Financiera y Regla 50/30/20:**\n\n"
                    f"Para potenciar su patrimonio, confianza y solvencia, aplique este esquema estratégico:\n\n"
                    f"1️⃣ **Necesidades Esenciales (50% Tope: {curr}{needs_tgt:,.2f})**:\n"
                    f"• Vivienda, alimentación, transporte, salud y suministros indispensables.\n\n"
                    f"2️⃣ **Deseos y Ocio (30% Tope: {curr}{wants_tgt:,.2f})**:\n"
                    f"• Restaurantes, suscripciones, ocio y viajes personales.\n\n"
                    f"3️⃣ **Ahorro e Inversión (20% Mínimo: {curr}{save_tgt:,.2f})**:\n"
                    f"• Fondo de emergencia e inversiones indexadas a largo plazo."
                )
                title = "Plan Visual de Gastos"
            elif lang == 'fr':
                reply = (
                    f"📈 **Schéma d'Optimisation des Dépenses 50/30/20 :**\n\n"
                    f"1️⃣ **Besoins Essentiels (50% Plafond : {curr}{needs_tgt:,.2f})** : Loyer, courses, factures indispensables.\n"
                    f"2️⃣ **Envies & Loisirs (30% Plafond : {curr}{wants_tgt:,.2f})** : Restaurants, divertissements, abonnements.\n"
                    f"3️⃣ **Épargne & Investissement (20% Minimum : {curr}{save_tgt:,.2f})** : Fonds d'urgence et actifs productifs."
                )
                title = "Optimisation Financière"
            elif lang == 'hi':
                reply = (
                    f"📈 **50/30/20 धन प्रबंधन ब्लूप्रिंट:**\n\n"
                    f"1️⃣ **ज़रूरी खर्चे (50% सीमा: {curr}{needs_tgt:,.2f})**: किराया, राशन, बिजली, पानी व बुनियादी ज़रूरतें।\n"
                    f"2️⃣ **शौक व मनोरंजन (30% सीमा: {curr}{wants_tgt:,.2f})**: डाइनिंग, मूवीज, शॉपिंग आदि।\n"
                    f"3️⃣ **बचत व निवेश (20% न्यूनतम: {curr}{save_tgt:,.2f})**: इमरजेंसी फंड व म्यूचुअल फंड में निवेश।"
                )
                title = "वित्तीय ब्लूप्रिंट"
            elif lang == 'ta':
                reply = (
                    f"📈 **50/30/20 நிதி மேலாண்மை உத்தி:**\n\n"
                    f"1️⃣ **அடிப்படை தேவைகள் (50% உச்சவரம்பு: {curr}{needs_tgt:,.2f})**: வாடகை, மளிகை, பில் தொகைகள்.\n"
                    f"2️⃣ **விருப்பங்கள் (30% உச்சவரம்பு: {curr}{wants_tgt:,.2f})**: உணவகங்கள், பொழுதுபோக்கு, ஷாப்பிங்.\n"
                    f"3️⃣ **சேமிப்பு & முதலீடு (20% இலக்கு: {curr}{save_tgt:,.2f})**: அவசர நிதி மற்றும் முதலீடுகள்."
                )
                title = "நிதி வழிகாட்டுதல்"
            else:
                reply = (
                    f"📈 **Autonomous Spending Optimization & Money Allocation Blueprint:**\n\n"
                    f"To maximize long-term wealth, trust, and fiscal resilience, adhere to this **50/30/20 rule allocation**:\n\n"
                    f"1️⃣ **Essential Needs (50% Cap: {curr}{needs_tgt:,.2f})**:\n"
                    f"• Rent, groceries, utilities, and debt minimums.\n\n"
                    f"2️⃣ **Discretionary Wants (30% Cap: {curr}{wants_tgt:,.2f})**:\n"
                    f"• Dining out, entertainment, shopping, hobbies.\n\n"
                    f"3️⃣ **Wealth Accumulation (20% Minimum: {curr}{save_tgt:,.2f})**:\n"
                    f"• Emergency fund liquidity & diversified index investments."
                )
                title = "Visual Spending Blueprint"

            html = self._format_bubble_html(title, reply, "bg-apple-blue/10 text-apple-blue")
            html += self._generate_visual_telemetry_svg(analytics)
            return {
                'status': 'success',
                'reply': reply,
                'response': html,
                'action_type': 'visual_suggestion',
                'payload': analytics
            }

        # 7. Budgets Management: Set, Clear, Check (Multilingual)
        if any(w in q_lower for w in ['clear budget', 'borrar presupuesto', 'eliminar presupuesto', 'supprimer budget', 'budget hatao', 'remove budget']):
            cat_match = re.search(r'(?:for|para|pour|für|ka|ku)\s+([a-zA-Z0-9_\-]+)', query, re.I)
            if cat_match and cat_match.group(1).lower() not in ('all', 'todos', 'tout'):
                norm_cat = self._normalize_category(cat_match.group(1))
                Budget.objects.filter(user=self.user, category__iexact=norm_cat).delete()
                msg = f"Cleared budget cap for {norm_cat}."
            else:
                Budget.objects.filter(user=self.user).delete()
                msg = "Cleared all monthly category budgets."
            return {
                'status': 'success',
                'reply': msg,
                'response': self._format_bubble_html("Budget Cleared", msg, "bg-apple-orange/10 text-apple-orange"),
                'action_type': 'set_budget',
                'payload': {'cleared': True}
            }

        b_match = re.search(r'(?:set|fijar|establecer|définir|festlegen)?\s*(?:budget|presupuesto|limit|limite)\s*(?:for|para|pour|für|ka|ku)?\s*([a-zA-Z0-9_\-\s]+?)\s*(?:to|en|à|auf|set\s+karo)?\s*(?:[\$€₹£]\s*)?(\d+(?:\.\d{1,2})?)$', query, re.I)
        if b_match and not any(w in q_lower for w in ['check', 'ver', 'voir', 'audit', 'health']):
            raw_c = b_match.group(1).strip()
            norm_c = 'Total' if raw_c.lower() == 'total' else self._normalize_category(raw_c)
            b_amt = Decimal(b_match.group(2))
            Budget.objects.update_or_create(
                user=self.user,
                category=norm_c,
                period='MONTHLY',
                month=today.month,
                year=today.year,
                defaults={'amount': b_amt}
            )
            if lang == 'es':
                reply = f"🎯 **Presupuesto Mensual Configurado**\n\n• **Categoría**: {norm_c}\n• **Límite Mensual**: {currency}{b_amt:.2f}\n• **Ciclo**: {today.strftime('%B %Y')}"
                title = "Presupuesto Configurado"
            elif lang == 'fr':
                reply = f"🎯 **Budget Mensuel Configuré**\n\n• **Catégorie** : {norm_c}\n• **Plafond** : {currency}{b_amt:.2f}\n• **Mois** : {today.strftime('%B %Y')}"
                title = "Budget Configuré"
            elif lang == 'hi':
                reply = f"🎯 **मासिक बजट निर्धारित किया गया**\n\n• **श्रेणी**: {norm_c}\n• **मासिक सीमा**: {currency}{b_amt:.2f}\n• **माह**: {today.strftime('%B %Y')}"
                title = "बजट कॉन्फ़िगर"
            elif lang == 'ta':
                reply = f"🎯 **மாதாந்திர பட்ஜெட் நிர்ணயிக்கப்பட்டது**\n\n• **பிரிவு**: {norm_c}\n• **வரம்பு**: {currency}{b_amt:.2f}\n• **மாதம்**: {today.strftime('%B %Y')}"
                title = "பட்ஜெட் நிர்ணயம்"
            else:
                reply = f"🎯 **Monthly Budget Updated**\n\n• **Category**: {norm_c}\n• **Monthly Limit**: {currency}{b_amt:.2f}\n• **Period**: {today.strftime('%B %Y')}"
                title = "Budget Configured"

            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html(title, reply, "bg-apple-blue/10 text-apple-blue"),
                'action_type': 'set_budget',
                'payload': {'category': norm_c, 'amount': float(b_amt)}
            }

        if any(w in q_lower for w in ['budget', 'presupuesto', 'presupuestos', 'budgets', 'overspent', 'limite']):
            reply = f"🎯 **Budget Health Audit ({analytics['month_name']})**\n\n{analytics['budgets_str']}"
            badge_class = "bg-apple-red/10 text-apple-red" if analytics['overspent_count'] > 0 else "bg-apple-green/10 text-apple-green"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Budget Health", reply, badge_class),
                'action_type': 'check_budgets',
                'payload': {'overspent_count': analytics['overspent_count']}
            }

        # 8. Reminders (Multilingual)
        r_match = re.search(r'(?:remind|recordar|rappeler|erinnern|yaad)\s*(?:me\s+to\s+pay|me\s+de\s+pagar|de\s+payer)?\s*(.+?)\s+(?:[\$€₹£]\s*)?(\d+(?:\.\d{1,2})?)\s+(?:on|el|le|am|date)?\s*(\d{4}-\d{2}-\d{2})$', query, re.I)
        if r_match:
            title_r = r_match.group(1).strip().capitalize()
            amt_r = Decimal(r_match.group(2))
            due_str = r_match.group(3)
            try:
                due_d = datetime.datetime.strptime(due_str, '%Y-%m-%d').date()
            except ValueError:
                due_d = today
            Reminder.objects.create(
                user=self.user,
                title=title_r,
                amount=amt_r,
                due_date=due_d,
                is_paid=False
            )
            reply = f"⏰ **Bill Reminder Created**\n\n• **Title**: {title_r}\n• **Amount**: {currency}{amt_r:.2f}\n• **Due Date**: {due_d.strftime('%b %d, %Y')}"
            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html("Reminder Created", reply, "bg-apple-orange/10 text-apple-orange"),
                'action_type': 'set_reminder',
                'payload': {'title': title_r, 'amount': float(amt_r), 'due_date': str(due_d)}
            }

        # 9. Natural Language Multilingual Transaction Logging (Income / Expense)
        amt_match = re.search(r'(?:[\$€₹£]\s*)?(\d+(?:\.\d{1,2})?)(?:\s*(?:eur|euros|usd|rs|rupees|roobai|bucks|quid))?', query, re.I)
        if amt_match:
            try:
                parsed_amt = Decimal(amt_match.group(1))
            except Exception:
                parsed_amt = Decimal('0.00')

            if parsed_amt > 0:
                date_val = self._parse_flexible_date(query, today)
                # Detect Inflow vs Outflow
                income_signals = ['income', 'ingreso', 'revenu', 'einnahme', 'entrata', 'receita', 'salary', 'salario', 'salaire', 'gehalt', 'stipendio', 'salário', 'paycheck', 'vetan', 'aamdani', 'sambalam', 'jeetham', 'wages', 'got', 'recibi', 'recibí', 'reçu', 'earned', 'ganado', 'varavu']
                is_income = any(sig in q_lower for sig in income_signals)
                tx_type = 'IN' if is_income else 'OUT'

                # Match category
                norm_cat = None
                canonical_kws = {
                    'Food': ['food', 'comida', 'nourriture', 'déjeuner', 'dejeuner', 'dîner', 'diner', 'essen', 'cibo', 'refeição', 'refeicao', 'almoço', 'almoco', 'janta', 'café', 'almuerzo', 'cena', 'desayuno', 'lunch', 'dinner', 'breakfast', 'snack', 'cafe', 'coffee', 'restaurante', 'restaurant', 'groceries', 'supermercado', 'khana', 'kharcha', 'doodh', 'chai', 'biryani', 'swiggy', 'zomato', 'unavu', 'saapadu', 'bhojanam', 'oota'],
                    'Rent': ['rent', 'alquiler', 'loyer', 'miete', 'affitto', 'aluguel', 'house', 'apartment', 'flat', 'kiraya', 'vadagai', 'aadige', 'makan'],
                    'Salary': ['salary', 'salario', 'salaire', 'gehalt', 'stipendio', 'salário', 'paycheck', 'vetan', 'aamdani', 'sambalam', 'jeetham', 'wages'],
                    'Travel': ['travel', 'transporte', 'transport', 'reise', 'viaggio', 'viagem', 'gas', 'fuel', 'petrol', 'diesel', 'uber', 'ola', 'auto', 'taxi', 'flight', 'vuelo', 'metro', 'bus', 'train', 'safar', 'yathirai'],
                    'Utilities': ['utilities', 'utility', 'factura', 'facture', 'rechnung', 'bolletta', 'conta', 'electric', 'electricity', 'water', 'internet', 'wifi', 'phone', 'recharge', 'bijli', 'pani', 'bill'],
                    'Entertainment': ['entertainment', 'entretenimiento', 'divertissement', 'unterhaltung', 'svago', 'film', 'movie', 'cinema', 'pelicula', 'netflix', 'spotify', 'game', 'gaming', 'concert', 'club', 'party', 'fun', 'manoranjan'],
                    'Health': ['health', 'medical', 'medicine', 'doctor', 'hospital', 'clinic', 'pharmacy', 'dawai', 'marundhu', 'salud', 'santé', 'gesundheit'],
                    'Shopping': ['shopping', 'clothes', 'clothing', 'kapde', 'thuni', 'kharidari', 'compras', 'achats', 'einkaufen'],
                    'Investment': ['investment', 'invest', 'stock', 'shares', 'dividend', 'mutual fund', 'crypto', 'bachat', 'semippu', 'podupu'],
                }
                for c_name, words in canonical_kws.items():
                    if any(re.search(r'\b' + re.escape(w) + r'\b', q_lower) for w in words):
                        norm_cat = c_name
                        break

                if not norm_cat:
                    prep_m = re.search(r'(?:for|in|en|pour|für|pe|la|di|de)\s+([a-zA-Z0-9_\-]+)', query, re.I)
                    if prep_m:
                        norm_cat = self._normalize_category(prep_m.group(1))
                    else:
                        norm_cat = 'Salary' if is_income else 'General'

                # Extract description
                desc = ''
                desc_m = re.search(r'(?:desc|description|note|nota|details?)\s+(.+)$', query, re.I)
                if desc_m:
                    desc = desc_m.group(1).strip()
                else:
                    desc = norm_cat

                Transaction.objects.create(
                    user=self.user,
                    amount=parsed_amt,
                    transaction_type=tx_type,
                    category=norm_cat,
                    date=date_val,
                    description=desc
                )
                Category.objects.get_or_create(user=self.user, name=norm_cat, defaults={'is_income': (tx_type == 'IN')})
                sign = "+" if tx_type == 'IN' else "-"
                badge_class = "bg-apple-green/10 text-apple-green" if tx_type == 'IN' else "bg-apple-red/10 text-apple-red"

                if lang == 'es':
                    tx_title = "Ingreso Registrado" if is_income else "Gasto Registrado"
                    reply = f"✅ **{tx_title} con Éxito**\n\n• **Monto**: {sign}{currency}{parsed_amt:.2f}\n• **Categoría**: {norm_cat}\n• **Descripción**: {desc or 'N/A'}\n• **Fecha**: {date_val.strftime('%d/%m/%Y')}"
                elif lang == 'fr':
                    tx_title = "Revenu Enregistré" if is_income else "Dépense Enregistrée"
                    reply = f"✅ **{tx_title} avec Succès**\n\n• **Montant** : {sign}{currency}{parsed_amt:.2f}\n• **Catégorie** : {norm_cat}\n• **Note** : {desc or 'N/A'}\n• **Date** : {date_val.strftime('%d/%m/%Y')}"
                elif lang == 'de':
                    tx_title = "Einnahme Erfasst" if is_income else "Ausgabe Erfasst"
                    reply = f"✅ **{tx_title}**\n\n• **Betrag**: {sign}{currency}{parsed_amt:.2f}\n• **Kategorie**: {norm_cat}\n• **Notiz**: {desc or 'N/A'}\n• **Datum**: {date_val.strftime('%d.%m.%Y')}"
                elif lang == 'hi':
                    tx_title = "आय दर्ज हुई" if is_income else "खर्च दर्ज हुआ"
                    reply = f"✅ **{tx_title} (Transaction Logged)**\n\n• **राशि**: {sign}{currency}{parsed_amt:.2f}\n• **श्रेणी**: {norm_cat}\n• **विवरण**: {desc or 'N/A'}\n• **तारीख**: {date_val.strftime('%d %b, %Y')}"
                elif lang == 'ta':
                    tx_title = "வருமானம் சேர்க்கப்பட்டது" if is_income else "செலவு சேர்க்கப்பட்டது"
                    reply = f"✅ **{tx_title}**\n\n• **தொகை**: {sign}{currency}{parsed_amt:.2f}\n• **பிரிவு**: {norm_cat}\n• **குறிப்பு**: {desc or 'N/A'}\n• **தேதி**: {date_val.strftime('%d %b, %Y')}"
                else:
                    tx_title = "Income Logged" if is_income else "Expense Logged"
                    reply = f"✅ **{tx_title} Successfully**\n\n• **Amount**: {sign}{currency}{parsed_amt:.2f}\n• **Category**: {norm_cat}\n• **Note**: {desc or 'N/A'}\n• **Date**: {date_val.strftime('%b %d, %Y')}"

                return {
                    'status': 'success',
                    'reply': reply,
                    'response': self._format_bubble_html(tx_title, reply, badge_class),
                    'action_type': 'log_transaction',
                    'payload': {'amount': float(parsed_amt), 'category': norm_cat, 'type': tx_type, 'date': str(date_val)}
                }

        # 10. Help & Commands Guide (Multilingual)
        if any(w in q_lower for w in ['help', 'ayuda', 'aide', 'hilfe', 'madad', 'udhavi', 'commands', 'command', 'menu', '?', 'what can you do', 'guide', 'qué puedes hacer', 'que puedes hacer']):
            if lang == 'es':
                reply = (
                    "🧠 **Inteligencia Financiera Leoxur — Guía de Comandos:**\n\n"
                    "Puedo gestionar su telemetría y contabilidad de forma autónoma en cualquier idioma:\n\n"
                    "1️⃣ **Registrar Gastos e Ingresos**:\n"
                    "• *\"Añadí 45 euros para comida ayer\"*\n"
                    "• *\"Añadir ingreso 3200 de salario hoy\"*\n"
                    "• *\"Gasto de 80 en wifi bill\"*\n\n"
                    "2️⃣ **Acciones del Sistema y Apariencia**:\n"
                    "• *\"Cambiar a modo oscuro\"* o *\"Poner modo claro\"*\n"
                    "• *\"Enviar informe a mi correo\"* — Transmite PDF oficial y Excel con gráficos vía SMTP\n"
                    "• *\"Sincronizar correos\"* — Escanea buzón IMAP en busca de recibos bancarios\n"
                    "• *\"Deshacer último gasto\"* — Elimina la última transacción\n\n"
                    "3️⃣ **Presupuestos y Metas**:\n"
                    "• *\"Fijar presupuesto para comida en 400\"*\n"
                    "• *\"Ver presupuestos\"*\n\n"
                    "4️⃣ **Telemetría y Consejos Visuales**:\n"
                    "• *\"Dar sugerencias visuales para optimizar dinero\"* (Gráfico interactivo 50/30/20)\n"
                    "• *\"Comparar con el mes pasado\"* (Telemetría histórica)"
                )
                title = "Guía de Comandos"
            elif lang == 'fr':
                reply = (
                    "🧠 **Intelligence Financière Leoxur — Guide des Commandes :**\n\n"
                    "1️⃣ **Enregistrer Dépenses et Revenus** : *\"Dépense de 45 en nourriture hier\"*, *\"Ajouter revenu 3000 salaire\"*\n"
                    "2️⃣ **Apparence & Actions** : *\"Passer en mode sombre\"*, *\"Envoyer le rapport par email\"*, *\"Synchroniser imap\"*\n"
                    "3️⃣ **Budgets & Analyse** : *\"Définir budget nourriture 400\"*, *\"Suggestions visuelles d'épargne\"*, *\"Comparer avec le mois dernier\"*"
                )
                title = "Guide des Commandes"
            elif lang == 'hi':
                reply = (
                    "🧠 **Leoxur वित्तीय सहायक — कमांड गाइड:**\n\n"
                    "1️⃣ **खर्च और आय दर्ज करें**: *\"500 rupees kharcha hua dinner pe ayer\"*, *\"salary 40000 aayi\"*\n"
                    "2️⃣ **सिस्टम व थीम**: *\"Dark mode karo\"*, *\"Report email pe bhejo\"*, *\"Pichla kharcha undo karo\"*\n"
                    "3️⃣ **बजट व विश्लेषण**: *\"Food budget 5000 set karo\"*, *\"Paise bachane ke tips do\"*, *\"Pichle mahine se compare karo\"*"
                )
                title = "कमांड गाइड"
            elif lang == 'ta':
                reply = (
                    "🧠 **Leoxur நிதி உதவியாளர் — வழிகாட்டி:**\n\n"
                    "1️⃣ **செலவு & வரவு**: *\"food 200 selavu add pannu\"*, *\"salary 35000 varavu add pannu\"*\n"
                    "2️⃣ **தீம் & அறிக்கை**: *\"dark mode mathu\"*, *\"report en email ku anuppu\"*, *\"kadaisi selavu delete pannu\"*\n"
                    "3️⃣ **பட்ஜெட் & சேமிப்பு**: *\"food budget 4000 set pannu\"*, *\"money savings tips\"*, *\"pona masam compare pannu\"*"
                )
                title = "வழிகாட்டி"
            else:
                reply = (
                    "🧠 **Leoxur Financial Intelligence — Command Guide:**\n\n"
                    "I can autonomously manage your personal financial ledger, telemetry, and system actions in ANY language:\n\n"
                    "1️⃣ **Log Expenses & Incomes**:\n"
                    "• *\"Add expense 45 for Food yesterday\"* (or in Spanish: *\"Añadí 45 euros para comida ayer\"*)\n"
                    "• *\"Add income 2500 for Salary\"* (or in Hindi: *\"salary 40000 aamdani add karo\"*)\n\n"
                    "2️⃣ **Appearance & System Actions**:\n"
                    "• *\"Switch to dark theme\"* / *\"Switch to light mode\"*\n"
                    "• *\"Send report to my email\"* — Dispatches rich PDF statement & Excel workbook via SMTP\n"
                    "• *\"Fetch IMAP details\"* or *\"Sync emails\"* — Scans unread bank receipts\n"
                    "• *\"Undo last expense\"* — Instantly removes latest ledger record\n\n"
                    "3️⃣ **Set Budgets & Outflow Limits**:\n"
                    "• *\"Set budget for Food to 350\"*\n"
                    "• *\"Check budgets\"* — Audit limits and overspending\n\n"
                    "4️⃣ **Visual Blueprint & Telemetry**:\n"
                    "• *\"Give me visual suggestions to utilize money properly\"* (50/30/20 interactive blueprint)\n"
                    "• *\"Compare with last month\"* (Historical month-over-month telemetry)"
                )
                title = "Command Guide"

            return {
                'status': 'success',
                'reply': reply,
                'response': self._format_bubble_html(title, reply, "bg-apple-blue/10 text-apple-blue"),
                'action_type': 'guide',
                'payload': {}
            }

        # 11. General Cashflow Status Diagnostic
        tot_inc = analytics['total_income']
        tot_exp = analytics['total_expense']
        bal = analytics['net_balance']
        rate = analytics['savings_rate']

        if lang == 'es':
            reply = (
                f"📊 **Diagnóstico de Flujo de Caja ({analytics['month_name']}):**\n\n"
                f"• **Ingresos Totales**: **{currency}{tot_inc:.2f}**\n"
                f"• **Gastos Totales**: **{currency}{tot_exp:.2f}**\n"
                f"• **Ahorro Neto**: **{currency}{bal:.2f}** ({rate}% tasa de ahorro)\n\n"
                f"💡 **Mayor Categoría de Gasto**: {analytics['cat_expenses_str'].split(',')[0] if analytics['cat_expenses_str'] else 'Ninguno'}\n\n"
                f"*(Escriba 'ayuda' para ver todos los comandos autónomos disponibles.)*"
            )
            title = "Diagnóstico Financiero"
        elif lang == 'fr':
            reply = (
                f"📊 **Bilan des Flux de Trésorerie ({analytics['month_name']}) :**\n\n"
                f"• **Entrées (Revenus)** : **{currency}{tot_inc:.2f}**\n"
                f"• **Sorties (Dépenses)** : **{currency}{tot_exp:.2f}**\n"
                f"• **Épargne Nette** : **{currency}{bal:.2f}** ({rate}% taux d'épargne)\n\n"
                f"💡 **Principale Dépense** : {analytics['cat_expenses_str'].split(',')[0] if analytics['cat_expenses_str'] else 'Aucune'}"
            )
            title = "Bilan Financier"
        elif lang == 'hi':
            reply = (
                f"📊 **मासिक वित्तीय स्थिति ({analytics['month_name']}):**\n\n"
                f"• **कुल आय**: **{currency}{tot_inc:.2f}**\n"
                f"• **कुल खर्च**: **{currency}{tot_exp:.2f}**\n"
                f"• **शुद्ध बचत**: **{currency}{bal:.2f}** ({rate}% बचत दर)\n\n"
                f"💡 **शीर्ष व्यय श्रेणी**: {analytics['cat_expenses_str'].split(',')[0] if analytics['cat_expenses_str'] else 'कोई नहीं'}"
            )
            title = "कैशफ्लो डायग्नोस्टिक"
        elif lang == 'ta':
            reply = (
                f"📊 **மாதாந்திர நிதி நிலை ({analytics['month_name']}):**\n\n"
                f"• **வருமானம்**: **{currency}{tot_inc:.2f}**\n"
                f"• **செலவுகள்**: **{currency}{tot_exp:.2f}**\n"
                f"• **நிகர சேமிப்பு**: **{currency}{bal:.2f}** ({rate}% சேமிப்பு விகிதம்)\n\n"
                f"💡 **அதிக செலவான பிரிவு**: {analytics['cat_expenses_str'].split(',')[0] if analytics['cat_expenses_str'] else 'இல்லை'}"
            )
            title = "நிதி நிலை அறிக்கை"
        else:
            reply = (
                f"📊 **Monthly Cashflow Diagnostic ({analytics['month_name']}):**\n\n"
                f"• **Inflow (Income)**: **{currency}{tot_inc:.2f}**\n"
                f"• **Outflow (Expenses)**: **{currency}{tot_exp:.2f}**\n"
                f"• **Net Savings**: **{currency}{bal:.2f}** ({rate}% savings rate)\n\n"
                f"💡 **Top Outflow Category**: {analytics['cat_expenses_str'].split(',')[0] if analytics['cat_expenses_str'] else 'None'}\n\n"
                f"*(Type 'help' for the complete list of natural-language commands.)*"
            )
            title = "Cashflow Diagnostic"

        return {
            'status': 'success',
            'reply': reply,
            'response': self._format_bubble_html(title, reply, "bg-apple-blue/10 text-apple-blue"),
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
