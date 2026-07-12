import imaplib
import email
from email.header import decode_header
import re
from decimal import Decimal
from datetime import date
from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth.models import User
from tracker.models import Transaction, Category, ProcessedEmail
from tracker.views import send_user_mail, render_html_email, render_compact_transaction_email

class Command(BaseCommand):
    help = 'Fetches unread emails from IMAP inbox and parses them into Transaction records.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop',
            action='store_true',
            help='Run the email synchronization in an infinite background loop polling every 15 seconds.',
        )

    def handle(self, *args, **options):
        loop = options.get('loop', False)
        if loop:
            self.stdout.write("Starting IMAP synchronization loop service (press Ctrl+C to terminate)...")
            import time
            while True:
                try:
                    self.sync_emails()
                except Exception as loop_err:
                    self.stderr.write(f"Sync loop error: {loop_err}")
                time.sleep(15)
        else:
            self.sync_emails()

    def sync_emails(self):
        # Find all users with email address configured
        users = User.objects.exclude(email='')
        if not users.exists():
            self.stdout.write("No registered user email addresses found in database.")
            return

        for user in users:
            profile = user.profile
            imap_host = profile.imap_host or getattr(settings, 'IMAP_HOST', None)
            imap_port = profile.imap_port or getattr(settings, 'IMAP_PORT', 993)
            imap_user = profile.imap_user or getattr(settings, 'IMAP_USER', None)
            imap_pass = profile.imap_password or getattr(settings, 'IMAP_PASSWORD', None)

            if not imap_host or not imap_user or not imap_pass:
                self.stdout.write(f"Skipping user '{user.username}': IMAP credentials not fully configured.")
                continue

            self.stdout.write(f"Connecting to IMAP server {imap_host} for user '{user.username}'...")
            try:
                mail = imaplib.IMAP4_SSL(imap_host, imap_port)
                mail.login(imap_user, imap_pass)
                mail.select("inbox")
                
                # Search for unread emails ONLY from this specific user
                status, response = mail.search(None, f'(UNSEEN FROM "{user.email}")')
                if status != 'OK' or not response[0]:
                    self.stdout.write(f"No new unread emails for user '{user.username}'.")
                    mail.close()
                    mail.logout()
                    continue
                    
                email_ids = response[0].split()
                self.stdout.write(f"Found {len(email_ids)} unread transaction email(s) for user '{user.username}'. Processing...")

                for e_id in email_ids:
                    # 1. Fetch lightweight headers first (Message-ID, Subject, Auto-headers)
                    res_h, data_h = mail.fetch(e_id, '(BODY[HEADER.FIELDS (MESSAGE-ID X-LEOXUR-AUTO AUTO-SUBMITTED SUBJECT)])')
                    msg_id = None
                    is_system_auto = False
                    subj_text = ""
                    if res_h == 'OK' and data_h[0] and isinstance(data_h[0], tuple):
                        header_text = data_h[0][1].decode('utf-8', errors='ignore')
                        match_id = re.search(r'(?i)Message-ID:\s*(<[^>\s]+>)', header_text)
                        if match_id:
                            msg_id = match_id.group(1).strip()
                        if re.search(r'(?i)X-Leoxur-Auto:\s*True', header_text):
                            is_system_auto = True
                        if re.search(r'(?i)Auto-Submitted:\s*auto-generated', header_text):
                            is_system_auto = True
                        match_sub = re.search(r'(?i)Subject:\s*(.*)', header_text)
                        if match_sub:
                            subj_text = match_sub.group(1).strip()

                    # Check for system-generated emails by header or subject prefix
                    subj_lower = subj_text.lower()
                    if is_system_auto or any(prefix in subj_lower for prefix in [
                        'daily financial report',
                        'budget breach alert',
                        'bill due today',
                        'transaction logged',
                        'transaction logging failed',
                        'parser rejected email'
                    ]):
                        # Skip and mark processed so we do not attempt to parse system alerts
                        if msg_id:
                            ProcessedEmail.objects.get_or_create(message_id=msg_id)
                        continue

                    # Deduplicate using Message-ID
                    if msg_id and ProcessedEmail.objects.filter(message_id=msg_id).exists():
                        continue

                    # 2. Check if the email was unseen (unread) on the server (Always True since search is UNSEEN)
                    was_unseen = True

                    # 3. Fetch full email body only for unprocessed messages
                    res, data = mail.fetch(e_id, '(RFC822)')
                    if res != 'OK':
                        continue
                    
                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Double-check Message-ID from full body if header pre-fetch missed it
                    if not msg_id:
                        msg_id = msg.get("Message-ID")
                        if msg_id and ProcessedEmail.objects.filter(message_id=msg_id).exists():
                            continue

                    # Extract Subject and Body
                    subject_header = msg.get("Subject", "")
                    subject = self.decode_header_str(subject_header)
                    body = self.get_email_body(msg)

                    # Try parsing transaction from body or subject
                    parsed_data = self.parse_transaction_payload(body) or self.parse_transaction_payload(subject)
                    
                    if parsed_data:
                        category_name, amount, tx_type, description = parsed_data
                        self.stdout.write(f"Found new transaction: {category_name}, {amount}")
                        
                        try:
                            category_name = category_name.strip().capitalize()
                            
                            # Ensure category choice is registered
                            is_income_bool = (tx_type == 'IN')
                            if not Category.objects.filter(user=user, name__iexact=category_name, is_income=is_income_bool).exists():
                                Category.objects.create(user=user, name=category_name, is_income=is_income_bool)
                            
                            tx = Transaction.objects.create(
                                user=user,
                                amount=amount,
                                transaction_type=tx_type,
                                category=category_name,
                                date=date.today(),
                                description=description
                            )
                            self.stdout.write(self.style.SUCCESS(f"Logged transaction #{tx.id}: {category_name}, {amount}, {tx_type}"))

                            # Send budget alerts if transaction is an Outflow
                            if tx_type == 'OUT':
                                from tracker.views import check_and_send_budget_alerts
                                check_and_send_budget_alerts(user, category_name, date.today())

                            # Save Message-ID to database to prevent double logging
                            if msg_id:
                                ProcessedEmail.objects.get_or_create(message_id=msg_id)

                            # Send Confirmation email acknowledgment back (styled matching app theme)
                            currency = user.profile.currency
                            ack_subject = f"Transaction Logged: {category_name}"
                            tx_type_str = 'Inflow (Income)' if tx_type == 'IN' else 'Outflow (Expense)'
                            flow_color = '#34c759' if tx_type == 'IN' else '#ff3b30'
                            
                            content_html = f"""
                             <div style="background-color: {flow_color}; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 16px; font-weight: 700; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; font-family: -apple-system, sans-serif;">
                                 Transaction Logged Successfully
                             </div>
                             <div style="background-color: #ffffff; padding: 16px; border-radius: 8px; border: 1px solid #e5e5ea; margin-bottom: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.02);">
                                 <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                                     <tr style="border-bottom: 1px solid #e5e5ea;">
                                         <td style="padding: 6px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Category</td>
                                         <td style="padding: 6px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{category_name}</td>
                                     </tr>
                                     <tr style="border-bottom: 1px solid #e5e5ea;">
                                         <td style="padding: 6px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Amount</td>
                                         <td style="padding: 6px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{currency}{amount:.2f}</td>
                                     </tr>
                                     <tr style="border-bottom: 1px solid #e5e5ea;">
                                         <td style="padding: 6px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Flow</td>
                                         <td style="padding: 6px 0; font-size: 11px; color: {flow_color}; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{tx_type_str}</td>
                                     </tr>
                                     <tr style="border-bottom: 1px solid #e5e5ea;">
                                         <td style="padding: 6px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Note</td>
                                         <td style="padding: 6px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{description or 'N/A'}</td>
                                     </tr>
                                     <tr>
                                         <td style="padding: 6px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Date Logged</td>
                                         <td style="padding: 6px 0; font-size: 11px; color: #1c1c1e; font-weight: 600; text-align: right; font-family: -apple-system, sans-serif;">{tx.date.strftime('%Y-%m-%d')}</td>
                                     </tr>
                                 </table>
                             </div>
                             """
                            
                            ack_body = render_html_email(
                                title=f"Telemetry Added: {category_name}",
                                subtitle="Incoming Parser Transmission",
                                content_html=content_html
                            )
                            send_user_mail(user, ack_subject, ack_body, is_html=True)
 
                        except Exception as tx_err:
                            self.stderr.write(f"Failed to save transaction: {tx_err}")
                    else:
                        # Log header mismatch but register Message-ID so we don't spam errors
                        if msg_id:
                            ProcessedEmail.objects.get_or_create(message_id=msg_id)
                            
                        # Only send failure emails for messages that were actually UNREAD/UNSEEN
                        if was_unseen:
                            fail_subject = "Transaction Logging Failed"
                             content_html = f"""
                             <div style="background-color: #ff3b30; color: #ffffff; padding: 10px; border-radius: 8px; margin-bottom: 12px; font-weight: 700; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; font-family: -apple-system, sans-serif;">
                                 Format Mismatch Detected
                             </div>
                             <div style="background-color: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #e5e5ea; font-size: 10px; color: #8e8e93; line-height: 1.5; margin-bottom: 4px; font-family: -apple-system, sans-serif; box-shadow: 0 2px 8px rgba(0,0,0,0.02);">
                                 Format your email payload inside the <strong>Subject</strong> or <strong>Body</strong> as:<br><br>
                                 <code style="background-color: #f5f5f7; padding: 4px 8px; border-radius: 4px; color: #ff3b30; font-family: monospace;">Category, Amount, IN/OUT, Description</code>
                             </div>
                             """
                            fail_body = render_html_email(
                                title="Parser Rejected Email Payload",
                                subtitle="Incoming Parser Error Transmission",
                                content_html=content_html
                            )
                            send_user_mail(user, fail_subject, fail_body, is_html=True)

                mail.close()
                mail.logout()
                self.stdout.write(f"Finished IMAP synchronization for user '{user.username}'.")
                
            except Exception as e:
                self.stderr.write(f"IMAP exception occurred for user '{user.username}': {e}")

    def parse_sender_email(self, from_header):
        match = re.search(r'<([^>]+)>', from_header)
        if match:
            return match.group(1).strip()
        return from_header.strip()

    def decode_header_str(self, val):
        decoded = decode_header(val)
        parts = []
        for text, encoding in decoded:
            if isinstance(text, bytes):
                parts.append(text.decode(encoding or 'utf-8', errors='ignore'))
            else:
                parts.append(str(text))
        return "".join(parts)

    def get_email_body(self, msg):
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except Exception:
                pass
        return body

    def parse_transaction_payload(self, text):
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for line in lines:
            parts = [p.strip() for p in line.split(',') if p.strip()]
            if len(parts) >= 2:
                category = parts[0]
                amt_str = re.sub(r'[^\d\.]', '', parts[1])
                try:
                    amount = Decimal(amt_str)
                except Exception:
                    continue
                
                tx_type = None
                if len(parts) >= 3:
                    t_val = parts[2].strip().upper()
                    if t_val in ['IN', 'INFLOW', 'INCOME', 'CREDIT', '+']:
                        tx_type = 'IN'
                    elif t_val in ['OUT', 'OUTFLOW', 'EXPENSE', 'DEBIT', '-']:
                        tx_type = 'OUT'
                    else:
                        continue
                else:
                    tx_type = 'OUT'
                
                description = "Emailed Transaction"
                if len(parts) >= 4:
                    description = ", ".join(parts[3:])
                    
                return category, amount, tx_type, description
        return None
