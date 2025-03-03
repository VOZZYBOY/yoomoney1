import uuid
import time
from yookassa import Configuration, Payment

def generate_idempotence_key():
    """Генерирует ключ идемпотентности."""
    return str(uuid.uuid4())

def create_payment(amount: float, currency: str, description: str, return_url: str, metadata: dict = None, capture: bool = True):
    """Создает платеж в ЮKassa."""

    payment = Payment.create({
        "amount": {
            "value": str(amount),
            "currency": currency
        },
        "capture": capture,
        "confirmation": {
            "type": "redirect",
            "return_url": return_url
        },
        "description": description,
        "metadata": metadata or {}
    }, generate_idempotence_key())
    return payment
  
def get_payment_status(payment_id: str):
    """Получить статус платежа."""
    return Payment.find_one(payment_id)

def capture_payment(payment_id: str, amount: dict = None):
     """Подтверждает (списывает) платеж (полностью или частично)."""
     if amount is None:
       # Полное списание
        return Payment.capture(payment_id, generate_idempotence_key())
     else:
       #частичное списание
        return Payment.capture(payment_id, amount, generate_idempotence_key())


def cancel_payment(payment_id: str):
    """Отменяет платеж."""
    return Payment.cancel(payment_id, generate_idempotence_key())

def schedule_retry(func, *args, delay=24*60*60, max_retries=3, **kwargs):
    """
    Планирует повторный запуск функции в случае неудачи.

    Args:
        func: Функция, которую нужно выполнить.
        *args: Позиционные аргументы для функции.
        delay: Задержка между повторными попытками в секундах (по умолчанию 24 часа).
        max_retries: Максимальное количество повторных попыток.
        **kwargs: Именованные аргументы для функции.

    Returns:
      Результат выполнения функции, если успешно, иначе None после всех попыток
    """
    retries = 0
    while retries < max_retries:
        try:
            result = func(*args, **kwargs)
            return result  
        except Exception as e:
            print(f"Ошибка при выполнении {func.__name__}: {e}")
            retries += 1
            print(f"Попытка {retries}/{max_retries}.  Ожидание {delay} секунд...")
            time.sleep(delay)
    print(f"Превышено максимальное количество попыток ({max_retries}) для {func.__name__}.")
    return None