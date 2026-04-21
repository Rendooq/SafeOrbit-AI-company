import bcrypt
import secrets

def hash_password(password: str) -> str:
    """Хеширование пароля (bcrypt)."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Безопасная проверка пароля."""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except ValueError:
        return False

def generate_api_key() -> str:
    """Генерация Stripe-like ключа."""
    return f"sk_live_{secrets.token_hex(32)}"
