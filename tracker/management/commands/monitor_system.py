import os
import json
import socket
import http.client
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from tracker.views import send_user_mail, render_html_email

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system_alert_state.json')

class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, unix_socket_path):
        super().__init__('localhost')
        self.unix_socket_path = unix_socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.unix_socket_path)


class Command(BaseCommand):
    help = 'Check server resource usage and Docker container health, sending SMTP email alerts if thresholds are breached.'

    def handle(self, *args, **options):
        try:
            import psutil
        except ImportError:
            self.stderr.write("Error: 'psutil' package is not installed. This command is designed to run inside the Docker container environment.")
            return

        # 1. Fetch Server Metrics
        cpu_pct = psutil.cpu_percent(interval=1)
        mem_pct = psutil.virtual_memory().percent
        disk_pct = psutil.disk_usage('/').percent

        # 2. Check Docker Container Statuses via UNIX Socket
        containers = self.get_docker_containers()
        
        container_breached = False
        container_states = []
        
        if containers is not None:
            for c in containers:
                names = ", ".join(c.get('Names', ['Unknown']))
                state = c.get('State', 'unknown')
                status = c.get('Status', 'unknown')
                container_states.append({
                    'name': names.replace('/', ''),
                    'state': state,
                    'status': status
                })
                # If container is not running, trigger alert
                if state.lower() != 'running':
                    container_breached = True
        else:
            container_states.append({
                'name': 'Docker Daemon',
                'state': 'inaccessible',
                'status': 'Socket read failed'
            })
            container_breached = True

        # 3. Check Resource Thresholds
        threshold_breached = (cpu_pct >= 80 or mem_pct >= 80 or disk_pct >= 80)
        is_breached = (threshold_breached or container_breached)

        # 4. Load Previous Alert State
        state = self.load_state()
        was_alerted = state.get('alert_active', False)

        # 5. Handle Alert State Transitions
        if is_breached and not was_alerted:
            self.stdout.write("Threshold breached! Dispatching critical SMTP alert...")
            self.send_alert_email(cpu_pct, mem_pct, disk_pct, container_states, is_alert=True)
            self.save_state(True)
        elif not is_breached and was_alerted:
            self.stdout.write("Metrics resolved to healthy. Dispatching restoration SMTP email...")
            self.send_alert_email(cpu_pct, mem_pct, disk_pct, container_states, is_alert=False)
            self.save_state(False)
        else:
            self.stdout.write(f"Telemetry healthy. Breach status: {is_breached}, Alert active: {was_alerted}")

    def get_docker_containers(self):
        try:
            # Connect to Docker Unix socket directly to prevent package dependencies
            conn = UnixHTTPConnection('/var/run/docker.sock')
            conn.request('GET', '/containers/json?all=1')
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            return json.loads(data.decode('utf-8'))
        except Exception as e:
            self.stderr.write(f"Docker socket error: {e}")
            return None

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_state(self, alert_active):
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump({'alert_active': alert_active}, f)
        except Exception as e:
            self.stderr.write(f"Failed to write state file: {e}")

    def send_alert_email(self, cpu, mem, disk, containers, is_alert=True):
        users = User.objects.filter(is_superuser=True).exclude(email='')
        if not users.exists():
            users = User.objects.exclude(email='')[:1] # Fallback to first user with email
            
        if not users.exists():
            self.stderr.write("No recipients found with configured email addresses.")
            return

        subject = "[ALERT] Leoxur System Utilization Exceeded" if is_alert else "[RESOLVED] Leoxur System Performance Restored"
        status_title = "System Telemetry Alert" if is_alert else "System Telemetry Restored"
        status_subtitle = "CRITICAL PERFORMANCE BOUNDS BREACH" if is_alert else "PERFORMANCE METRICS RESTORED TO NORMAL"
        
        status_color = "#ff3b30" if is_alert else "#34c759"
        status_text = "CRITICAL BREACH" if is_alert else "HEALTHY"

        container_rows = []
        for c in containers:
            c_color = "#34c759" if c['state'].lower() == 'running' else "#ff3b30"
            container_rows.append(f"""
            <tr style="border-bottom: 1px solid #e5e5ea;">
                <td style="padding: 10px 0; font-size: 11px; color: #1c1c1e; font-family: -apple-system, sans-serif; font-weight: 600;">{c['name']}</td>
                <td style="padding: 10px 0; font-size: 11px; text-align: right; font-family: -apple-system, sans-serif;">
                    <span style="font-size: 8px; font-weight: 700; color: {c_color}; border: 1px solid {c_color}; padding: 1px 4px; border-radius: 4px; text-transform: uppercase;">{c['state']}</span>
                </td>
            </tr>
            """)
        container_table_html = "".join(container_rows)

        content_html = f"""
        <div style="background-color: {status_color}; color: #ffffff; padding: 12px; border-radius: 10px; margin-bottom: 20px; font-weight: 700; font-size: 11px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; font-family: -apple-system, sans-serif;">
            {status_text}
        </div>
        
        <!-- Hardware Host Metrics -->
        <div style="background-color: #ffffff; padding: 18px; border-radius: 14px; border: 1px solid #e5e5ea; margin-bottom: 20px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
            <h3 style="font-size: 11px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-top: 0; margin-bottom: 12px; border-bottom: 1px solid #e5e5ea; padding-bottom: 6px; font-weight: 700;">Host Metrics Summary</h3>
            <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e5ea;">
                    <td style="padding: 10px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">CPU Utilization</td>
                    <td style="padding: 10px 0; font-size: 11px; text-align: right; font-weight: 600; color: {'#ff3b30' if cpu >= 80 else '#1c1c1e'}; font-family: -apple-system, sans-serif;">{cpu:.1f}%</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e5ea;">
                    <td style="padding: 10px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Memory Usage</td>
                    <td style="padding: 10px 0; font-size: 11px; text-align: right; font-weight: 600; color: {'#ff3b30' if mem >= 80 else '#1c1c1e'}; font-family: -apple-system, sans-serif;">{mem:.1f}%</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e5ea;">
                    <td style="padding: 10px 0; font-size: 11px; color: #8e8e93; font-family: -apple-system, sans-serif;">Disk Filesystem</td>
                    <td style="padding: 10px 0; font-size: 11px; text-align: right; font-weight: 600; color: {'#ff3b30' if disk >= 80 else '#1c1c1e'}; font-family: -apple-system, sans-serif;">{disk:.1f}%</td>
                </tr>
            </table>
        </div>

        <!-- Docker Containers Status -->
        <div style="background-color: #ffffff; padding: 18px; border-radius: 14px; border: 1px solid #e5e5ea; margin-bottom: 10px; font-family: -apple-system, sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
            <h3 style="font-size: 11px; text-transform: uppercase; color: #a855f7; letter-spacing: 0.5px; margin-top: 0; margin-bottom: 12px; border-bottom: 1px solid #e5e5ea; padding-bottom: 6px; font-weight: 700;">Docker Containers Status</h3>
            <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                {container_table_html}
            </table>
        </div>
        """

        email_body = render_html_email(
            title=status_title,
            subtitle=status_subtitle,
            content_html=content_html
        )

        for u in users:
            try:
                send_user_mail(u, subject, email_body, is_html=True)
                self.stdout.write(f"Alert mail successfully sent to {u.username} ({u.email}).")
            except Exception as e:
                self.stderr.write(f"Failed to send email to {u.username}: {e}")
