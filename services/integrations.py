import httpx
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

async def push_to_beauty_pro(data: dict, token: str, location_id: str, api_url: str = None):
    url = api_url or "https://api.beautypro.com/v1/appointments"
    logger.info(f"BEAUTY PRO PUSH: Sending to {url} | Data: {data}")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "location_id": location_id,
        "customer_phone": data['phone'],
        "customer_name": data.get('name', ''),
        "service_name": data['service'],
        "start_time": data['datetime'],
        "price": data['cost']
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code in [200, 201]:
                logger.info(f"Beauty Pro PUSH successful: {resp.status_code}")
                return {"status": "success", "msg": "Запис синхронізовано з Beauty Pro"}
            else:
                logger.error(f"Beauty Pro PUSH failed: {resp.status_code} - {resp.text}")
                return {"status": "error", "msg": f"Помилка Beauty Pro: {resp.status_code}"}
        except Exception as e:
            logger.error(f"Beauty Pro Error: {e}")
            return {"status": "error", "msg": "Помилка з'єднання з Beauty Pro"}
            
async def push_to_cleverbox(data: dict, token: str, location_id: str, api_url: str = None):
    url = api_url or "https://cbox.mobi/api/v2/leads"
    logger.info(f"CLEVERBOX PUSH: Sending to {url} | Data: {data}")
    
    # Згідно документації токен передається в спеціальному заголовку "token"
    headers = {"token": token, "Content-Type": "application/json"}
    
    dt_formatted = data['datetime']
    try:
        dt_obj = datetime.fromisoformat(data['datetime'])
        dt_formatted = dt_obj.strftime('%d.%m.%Y %H:%M')
    except: pass
    
    msg_text = f"Запис з AI CRM\nПослуга: {data['service']}\nДата та час: {dt_formatted}\nОчікувана сума: {data['cost']} грн."
    
    # Очищуємо номер телефону від пробілів та дужок для коректного розпізнавання в CRM
    clean_phone = re.sub(r'[^0-9+]', '', data.get('phone', ''))

    payload = {
        "cmd": "newLead",
        "data": {
            "phone": clean_phone,
            "name": data.get('name', '') or 'Клієнт',
            "coment": msg_text,
            "source": "SafeOrbit CRM",
            "message": "Новий запис через AI-Асистента"
        }
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            resp_data = resp.json()
            
            if resp.status_code == 200 and resp_data.get("ok") is True:
                logger.info(f"Cleverbox PUSH successful: {resp_data}")
                return {"status": "success", "msg": "Ліда відправлено в Cleverbox"}
            else:
                error_msg = resp_data.get("error", resp.text)
                logger.error(f"Cleverbox PUSH failed: {resp.status_code} - {error_msg}")
                return {"status": "error", "msg": f"Помилка Cleverbox: {error_msg}"}
        except Exception as e:
            logger.error(f"Cleverbox Error: {e}")
            return {"status": "error", "msg": "Помилка з'єднання з Cleverbox"}
            
async def push_to_integrica(data: dict, token: str, location_id: str, api_url: str = None):
    url = api_url or "https://api.integrica.com/v1/appointments"
    logger.info(f"INTEGRICA PUSH: Sending to {url} | Data: {data}")
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "location_id": location_id,
        "customer_phone": data.get('phone', ''),
        "customer_name": data.get('name', '') or 'Клієнт',
        "service": data['service'],
        "datetime": data['datetime'],
        "price": data['cost']
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code in [200, 201, 204]:
                return {"status": "success", "msg": "Запис синхронізовано з Integrica"}
            else:
                return {"status": "error", "msg": f"Помилка Integrica: {resp.status_code}"}
        except Exception as e:
            logger.error(f"Integrica Error: {e}")
            return {"status": "error", "msg": "Помилка з'єднання з Integrica"}

async def push_to_luckyfit(data: dict, token: str):
    url = "https://my.lucky.fitness/leads"
    logger.info(f"LUCKYFIT PUSH: Sending to {url} | Data: {data}")
    
    headers = {"Api-Key": token, "Content-Type": "application/json"}
    
    full_name = data.get('name', 'Клієнт').split()
    name = full_name[0] if full_name else 'Клієнт'
    surname = ' '.join(full_name[1:]) if len(full_name) > 1 else ''

    dt_obj = datetime.fromisoformat(data['datetime'])
    dt_formatted = dt_obj.strftime('%d.%m.%Y %H:%M')
    
    notes_text = f"Запис з AI CRM (SafeOrbit)\nПослуга: {data['service']}\nДата та час: {dt_formatted}\nОчікувана сума: {data['cost']} грн."

    payload = {
        "name": name,
        "surname": surname,
        "phone": data.get('phone', ''),
        "notes": notes_text,
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            resp_data = resp.json()
            
            if resp.status_code in [200, 201] and resp_data.get("success") is True:
                logger.info(f"LuckyFit PUSH successful: {resp_data}")
                return {"status": "success", "msg": "Лід успішно створено в LuckyFit"}
            else:
                error_msg = resp_data.get("error", resp.text)
                logger.error(f"LuckyFit PUSH failed: {resp.status_code} - {error_msg}")
                return {"status": "error", "msg": f"Помилка LuckyFit: {error_msg}"}
        except Exception as e:
            logger.error(f"LuckyFit Error: {e}")
            return {"status": "error", "msg": "Помилка з'єднання з LuckyFit"}

async def push_to_uspacy(data: dict, token: str, workspace_id: str):
    """
    Mocks pushing data to uSpacy API.
    In a real scenario, this would make an actual API call to uSpacy.
    """
    url = f"https://api.uspacy.com/v1/workspaces/{workspace_id}/leads" # Illustrative endpoint
    logger.info(f"USPACY PUSH: Sending to {url} | Data: {data}")
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    payload = {
        "title": f"Новий запис: {data['service']} для {data.get('name', 'Клієнт')}",
        "customer": {"phone": data.get('phone', ''), "name": data.get('name', '')},
        "appointment_details": {"service": data['service'], "datetime": data['datetime'], "cost": data['cost']},
        "source": "SafeOrbit CRM"
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if resp.status_code in [200, 201]: return {"status": "success", "msg": "Запис синхронізовано з uSpacy"}
            else: return {"status": "error", "msg": f"Помилка uSpacy: {resp.status_code}"}
        except Exception as e: return {"status": "error", "msg": "Помилка з'єднання з uSpacy"}

