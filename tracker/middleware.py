"""
Leoxur Financial Telemetry — Enterprise Logging & Defensive Security Middleware
Provides high-granularity request telemetry, execution latency profiling,
sensitive payload sanitization, and strict HTTP defense headers.
"""

import time
import logging
import traceback
from django.utils.deprecation import MiddlewareMixin

req_logger = logging.getLogger('tracker.requests')
sec_logger = logging.getLogger('tracker.security')
err_logger = logging.getLogger('tracker.errors')

SENSITIVE_KEYS = {
    'password', 'new_password', 'current_password', 'old_password',
    'smtp_password', 'imap_password', 'ai_api_key', 'gemini_api_key',
    'secret', 'token', 'csrfmiddlewaretoken'
}


def get_client_ip(request):
    """Safely extracts real client IP behind reverse proxies (Nginx, Cloudflare, etc.)."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or '127.0.0.1'
    return ip


def sanitize_payload(data):
    """Sanitizes sensitive credentials from dictionary payloads before logging."""
    if not isinstance(data, dict):
        return str(data)[:200]
    sanitized = {}
    for k, v in data.items():
        if any(sens in k.lower() for sens in SENSITIVE_KEYS):
            sanitized[k] = '***MASKED***'
        elif isinstance(v, dict):
            sanitized[k] = sanitize_payload(v)
        elif isinstance(v, (list, tuple)):
            sanitized[k] = [sanitize_payload(x) if isinstance(x, dict) else x for x in v[:5]]
        else:
            sanitized[k] = str(v)[:150]
    return sanitized


class LeoxurLoggingMiddleware(MiddlewareMixin):
    """
    High-fidelity telemetry middleware that tracks every inbound HTTP request,
    computes wall-clock execution latency, profiles user activity,
    and isolates anomalies and errors.
    """

    def process_request(self, request):
        request._start_time = time.monotonic()
        client_ip = get_client_ip(request)
        user_str = request.user.username if getattr(request, 'user', None) and request.user.is_authenticated else 'anonymous'
        
        # Log inbound request telemetry
        req_logger.info(
            f"INBOUND [{request.method}] {request.get_full_path()} "
            f"| User: {user_str} | IP: {client_ip} "
            f"| Content-Type: {request.content_type or 'none'}"
        )

    def process_response(self, request, response):
        duration_ms = 0.0
        if hasattr(request, '_start_time'):
            duration_ms = (time.monotonic() - request._start_time) * 1000.0

        client_ip = get_client_ip(request)
        user_str = request.user.username if getattr(request, 'user', None) and request.user.is_authenticated else 'anonymous'
        status = response.status_code

        log_msg = (
            f"OUTBOUND [{request.method}] {request.get_full_path()} "
            f"| Status: {status} | Latency: {duration_ms:.2f}ms "
            f"| User: {user_str} | IP: {client_ip}"
        )

        if status >= 500:
            err_logger.error(log_msg)
        elif status >= 400:
            sec_logger.warning(log_msg)
        else:
            req_logger.info(log_msg)

        # Inject diagnostic latency header into response
        response['X-Response-Time-MS'] = f"{duration_ms:.2f}"
        return response

    def process_exception(self, request, exception):
        client_ip = get_client_ip(request)
        user_str = request.user.username if getattr(request, 'user', None) and request.user.is_authenticated else 'anonymous'
        tb_str = traceback.format_exc()
        
        err_logger.critical(
            f"CRITICAL FAULT [{request.method}] {request.get_full_path()} "
            f"| User: {user_str} | IP: {client_ip} | Exception: {type(exception).__name__}: {exception}\n{tb_str}"
        )
        return None


class LeoxurSecurityHeadersMiddleware(MiddlewareMixin):
    """
    Defensive HTTP headers middleware protecting against XSS, Clickjacking,
    MIME sniffing, and cross-origin leakage.
    """

    def process_response(self, request, response):
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=(self)'
        return response

