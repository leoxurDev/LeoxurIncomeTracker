# Leoxur App Manual & Deployment Guide
This guide is written for both beginners and developers to help you understand, run, customize, and deploy your **Leoxur Income & Expense Tracker** application.

---

## 📖 Table of Contents
1. [🌟 What is Leoxur?](#-what-is-leoxur)
2. [🖥️ Dashboard Walkthrough](#-dashboard-walkthrough)
3. [🤖 Leoxur AI Copilot Manual](#-leoxur-ai-copilot-manual)
4. [📬 Email Sync Configuration Guide (SMTP & IMAP)](#-email-sync-configuration-guide-smtp-imap)
5. [📦 Local Setup & Deployment Guide](#-local-setup-deployment-guide)
6. [🛠️ Useful Terminal Commands Cheat Sheet](#%EF%B8%8F-useful-terminal-commands-cheat-sheet)

---

## 🌟 What is Leoxur?
Leoxur is a personal finance manager designed to give you complete visibility over your cashflow. Inspired by modern macOS/iOS glassmorphism designs, it displays real-time animated charts, aggregates category budgets, lists statements, and logs upcoming bills. It features an interactive **AI Copilot** at the bottom-right corner of the screen to process financial entries and query analytics using natural language.

---

## 🖥️ Dashboard Walkthrough

### 1. Stats Grid
Located at the top of the dashboard, this panel aggregates your monthly data:
- **Net Portfolio Balance**: Your total monthly surplus (Inflows minus Outflows).
- **Total Inflows**: Cumulative incoming funds.
- **Total Outflows**: Cumulative expenses.
- **Monthly Savings Rate**: Percentage of inflow kept as savings (calculated automatically).

### 2. Trend Telemetry
An interactive line chart showing the monthly progression of incoming vs. outgoing cashflow. Moving the cursor over the lines displays exact points.

### 3. Categories Breakdown
A doughnut graph displaying the share of your expenses. Hovering slices displays their shares and percentage contributions.

### 4. Interactive Ledger (Transactions List)
Displays your transaction ledger.
- **Filters**: Search ledger entries instantly by typing descriptions or categories.
- **Sort**: Re-order entries by date, lowest values, or highest values.
- **Bulk Delete**: Check multiple checkboxes next to transaction rows and click "Delete Selected" to batch-remove records.

### 5. Bill Reminders List
Displays upcoming bill payments. Click **"Settle"** next to any due reminder to mark it as paid. If it is recurring (e.g. monthly), a new unpaid reminder is automatically created for the next cycle.

---

## 🤖 Leoxur AI Copilot Manual
The **Leoxur AI Copilot** is your virtual financial manager. You can access it via the trigger bubble at the bottom-right corner of the screen or by clicking **"Open Savings Copilot"** in the left sidebar.

### UI Controls
- **Maximize Button (expand icon)**: Expands the chatbot panel into a full-screen console for heavy analysis.
- **Minimize Button (minus icon)**: Slides the chatbot window back down into the trigger bubble.
- **Clear Button (trash icon)**: Resets the chat logs.
- **Enter Key Submission**: Simply type your query and press **Enter** to talk to the Copilot.

### Natural Language Command Cheat Sheet
Simply text the following commands to log transactions, target budgets, and query stats:

| Action / Goal | Command Format | Example |
| :--- | :--- | :--- |
| **Log Expense** | `add expense [amount] [Category] desc [description]` | `add expense 45 Food desc dinner at diner` |
| **Log Income** | `add income [amount] [Category] desc [description]` | `add income 3000 Salary desc salary payment` |
| **Set Budget Limit** | `set [Category] budget to [amount]` | `set Food budget to 350` |
| **Schedule Bill Alert**| `remind me to pay [title] [amount] on [YYYY-MM-DD]` | `remind me to pay internet bill 60 on 2026-08-01` |
| **Verify Budget Health**| `check budgets` | `check budgets` |
| **Search Transaction Ledger**| `find [category/keyword]` | `find rent` |
| **Forecast Savings** | `predict savings` or `forecast` | `predict savings` |
| **Scan Email Transactions**| `sync emails` or `fetch transactions` | `sync emails` |
| **Command Help Menu** | `help` | `help` |

---

## 📬 Email Sync Configuration Guide (SMTP & IMAP)
Leoxur connects to your mail accounts to automatically log transaction entries sent from your registered email address and to email you daily PDF statements and bill alerts.

### 🔐 How to Create a Google App Password (Required for Gmail)
For security, Google prevents applications from logging in with your main password. You must generate an App Password:
1. Go to your **Google Account Settings** (https://myaccount.google.com).
2. Navigate to **Security** on the left menu.
3. Enable **2-Step Verification** (if not already enabled).
4. Search for or select **App Passwords**.
5. Type an application name (e.g. `Leoxur Finance`) and click **Create**.
6. Google will display a **16-character code** (e.g. `abcd efgh ijkl mnop`). Copy this code.

### ✉️ Setting Up in Leoxur UI
1. Log in to the Leoxur web application.
2. In the left sidebar, click the **Settings (gear icon)** next to your username.
3. In the settings panel:
   - **SMTP Host**: `smtp.gmail.com` (Port: `587`)
   - **SMTP User**: Your Gmail address.
   - **SMTP Password**: The 16-character App Password.
   - **IMAP Host**: `imap.gmail.com` (Port: `993`)
   - **IMAP User**: Your Gmail address.
   - **IMAP Password**: The 16-character App Password.
4. Check **Auto-Fetch on Dashboard Load** if you want the ledger to search your inbox for transactions automatically whenever you log in.
5. Click **Save Configurations**.

---

## 📦 Local Setup & Deployment Guide

### 💻 Local Run (Beginners Setup)
1. **Open Terminal** (macOS/Linux) or Command Prompt (Windows).
2. **Install Python Packages**:
   ```bash
   pip3 install django openpyxl reportlab
   ```
3. **Download Code & Setup Database**:
   Navigate to the project directory in your terminal and run:
   ```bash
   python3 manage.py makemigrations
   ```
   ```bash
   python3 manage.py migrate
   ```
4. **Launch Server**:
   ```bash
   python3 manage.py runserver
   ```
5. Open your web browser and go to `http://127.0.0.1:8000/`. Use the credentials:
   - **Username**: `superuser`
   - **Password**: `adminpass123`

---

### ☁️ Cloud Production Deployment Guide (Ubuntu/Linux Server)
To run Leoxur in a production environment as a background service:

#### 1. Setup Gunicorn
Install Gunicorn to serve the Django site in production:
```bash
pip3 install gunicorn
```

#### 2. Configure Systemd background service
Create a background service configuration:
```bash
sudo nano /etc/systemd/system/leoxur.service
```
Paste the following configurations (adjust path `/home/ubuntu/Income-Tracker` to your actual folder path):
```ini
[Unit]
Description=Gunicorn daemon for Leoxur Financial Core
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/Income-Tracker
ExecStart=/usr/local/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 income_tracker.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```
Enable and launch the background service:
```bash
sudo systemctl daemon-reload
sudo systemctl start leoxur
sudo systemctl enable leoxur
```

#### 3. Automating Daily Email Statements (Cron Setup)
To configure the server to automatically send out the **Daily PDF Statement** and **Bill Reminders** every day at 8:00 AM:
1. Open the crontab configuration editor:
   ```bash
   crontab -e
   ```
2. Add the following lines at the bottom (replace path with your actual application folder):
   ```cron
   # Send daily PDF/Excel reports to users at 8:00 AM daily
   0 8 * * * cd /home/ubuntu/Income-Tracker && python3 manage.py send_daily_report >> /home/ubuntu/Income-Tracker/cron_reports.log 2>&1

   # Scan for bill reminders due today and send alerts at 8:05 AM daily
   5 8 * * * cd /home/ubuntu/Income-Tracker && python3 manage.py send_bill_reminders >> /home/ubuntu/Income-Tracker/cron_reminders.log 2>&1
   ```
3. Save and close. The scripts will run in the background automatically.

---

## 🛠️ Useful Terminal Commands Cheat Sheet

| Command Goal | Terminal Command Line |
| :--- | :--- |
| **Start Development Server** | `python3 manage.py runserver` |
| **Apply Database Migrations** | `python3 manage.py migrate` |
| **Create Custom Admin User** | `python3 manage.py createsuperuser` |
| **Manually Trigger Email Ingest** | `python3 manage.py fetch_emails` |
| **Manually Dispatch Daily Reports**| `python3 manage.py send_daily_report` |
| **Manually Send Bill Reminders** | `python3 manage.py send_bill_reminders` |
| **Programmatically Seed Sample Data** | `python3 seed_data.py` |
