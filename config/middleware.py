"""Security headers, correlation ID tracking, and thread-local audit metadata."""
import threading
import uuid

_request_state = threading.local()


def get_correlation_id() -> str:
    return getattr(_request_state, "correlation_id", "") or str(uuid.uuid4())


def get_client_ip() -> str:
    return getattr(_request_state, "client_ip", "0.0.0.0")


class CorrelationAndSecurityMiddleware:
    """Attach correlation ID and security headers to every HTTP response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        corr_id = request.headers.get("X-Correlation-ID") or f"zarv-{uuid.uuid4().hex[:12]}"
        forwarded = request.headers.get("X-Forwarded-For", "")
        client_ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "127.0.0.1")

        _request_state.correlation_id = corr_id
        _request_state.client_ip = client_ip
        request.correlation_id = corr_id

        response = self.get_response(request)
        response["X-Correlation-ID"] = corr_id
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(self)"
        # Avoid caching authenticated API or private doc responses
        if request.path.startswith("/api/") or request.path.startswith("/private/"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response["Pragma"] = "no-cache"
        return response
