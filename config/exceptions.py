"""Standardized DRF error response format (Section 19)."""
from rest_framework.views import exception_handler
from config.middleware import get_correlation_id


def zarvon_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
        errors = detail
    elif isinstance(detail, list):
        message = str(detail[0]) if detail else "Xatolik yuz berdi"
        errors = {"non_field_errors": detail}
    else:
        message = "Kiritilgan ma'lumotlarni tekshiring"
        errors = detail if isinstance(detail, dict) else {"detail": detail}

    response.data = {
        "ok": False,
        "error": {
            "code": getattr(exc, "default_code", "error"),
            "message": message,
            "details": errors,
            "correlation_id": get_correlation_id(),
        },
    }
    return response
