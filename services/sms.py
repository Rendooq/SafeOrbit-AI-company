"""TurboSMS delivery shared by manual messages and scheduled reminders."""
import logging

import httpx

from config import DEFAULT_SMS_SENDER

logger = logging.getLogger(__name__)


async def send_sms(client, business, phone, message):
    if not business or not business.sms_token:
        return False, "Вкажіть токен TurboSMS у налаштуваннях."
    try:
        response = await client.post(
            "https://api.turbosms.ua/message/send.json",
            headers={"Authorization": f"Bearer {business.sms_token}"},
            json={"recipients": [phone], "sms": {
                "sender": business.sms_sender_id or DEFAULT_SMS_SENDER, "text": message,
            }},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("response_result")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            accepted = results[0].get("response_code") == 0
        else:
            accepted = data.get("response_code") == 0
        return accepted, "SMS прийнято провайдером." if accepted else "TurboSMS відхилив повідомлення."
    except (httpx.HTTPError, ValueError, AttributeError):
        logger.warning("TurboSMS request failed for business %s", business.id)
        return False, "Не вдалося отримати підтвердження від TurboSMS."
