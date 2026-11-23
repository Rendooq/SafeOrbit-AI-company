import bcrypt
import secrets
import hashlib
import base64

_PASSWORD_PREFIX = "bcrypt-sha256$"


def _password_digest(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())

def hash_password(password: str) -> str:
    """Хеширование пароля (bcrypt)."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(_password_digest(password), salt)
    return _PASSWORD_PREFIX + hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Безопасная проверка пароля."""
    try:
        if hashed_password.startswith(_PASSWORD_PREFIX):
            return bcrypt.checkpw(
                _password_digest(plain_password),
                hashed_password[len(_PASSWORD_PREFIX):].encode("utf-8"),
            )
        # Preserve legacy bcrypt hashes, including its old 72-byte truncation.
        return bcrypt.checkpw(plain_password.encode('utf-8')[:72], hashed_password.encode('utf-8'))
    except ValueError:
        return False

def generate_api_key() -> str:
    """Генерация Stripe-like ключа."""
    return f"sk_live_{secrets.token_hex(32)}"
