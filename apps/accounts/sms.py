"""Pluggable SMS OTP transport (Eskiz.uz / PlayMobile in Production, safe no-op in Sandbox)."""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_otp_sms(phone: str, code: str) -> dict:
    """Send 6-digit OTP via Eskiz.uz or PlayMobile when configured outside Sandbox mode."""
    if getattr(settings, "ZARVON_SANDBOX_MODE", True):
        return {"sent": False, "provider": "SANDBOX"}

    clean_phone = "".join(ch for ch in (phone or "") if ch.isdigit())
    message = f"ZARVON platformasiga kirish kodi: {code}. Kodni hech kimga bermang."

    eskiz_email = getattr(settings, "ESKIZ_EMAIL", "")
    eskiz_password = getattr(settings, "ESKIZ_PASSWORD", "")
    eskiz_from = getattr(settings, "ESKIZ_FROM", "4546") or "4546"
    if eskiz_email and eskiz_password:
        try:
            auth_resp = requests.post(
                "https://notify.eskiz.uz/api/auth/login",
                data={"email": eskiz_email, "password": eskiz_password},
                timeout=8,
            )
            auth_resp.raise_for_status()
            token = (auth_resp.json().get("data") or {}).get("token")
            if token:
                send_resp = requests.post(
                    "https://notify.eskiz.uz/api/message/sms/send",
                    headers={"Authorization": f"Bearer {token}"},
                    data={
                        "mobile_phone": clean_phone,
                        "message": message,
                        "from": eskiz_from,
                    },
                    timeout=8,
                )
                send_resp.raise_for_status()
                return {"sent": True, "provider": "ESKIZ"}
        except Exception as exc:
            logger.warning("Eskiz SMS yuborishda xatolik: %s", exc)
            return {"sent": False, "provider": "ESKIZ_ERROR"}

    pm_url = getattr(settings, "PLAYMOBILE_URL", "")
    pm_user = getattr(settings, "PLAYMOBILE_USERNAME", "")
    pm_pass = getattr(settings, "PLAYMOBILE_PASSWORD", "")
    if pm_url and pm_user and pm_pass:
        try:
            pm_resp = requests.post(
                pm_url,
                auth=(pm_user, pm_pass),
                json={
                    "messages": [
                        {
                            "recipient": clean_phone,
                            "message-id": f"zrv-{clean_phone[-4:]}-{code}",
                            "sms": {"originator": "ZARVON", "content": {"text": message}},
                        }
                    ]
                },
                timeout=8,
            )
            pm_resp.raise_for_status()
            return {"sent": True, "provider": "PLAYMOBILE"}
        except Exception as exc:
            logger.warning("PlayMobile SMS yuborishda xatolik: %s", exc)
            return {"sent": False, "provider": "PLAYMOBILE_ERROR"}

    return {"sent": False, "provider": "UNCONFIGURED"}
