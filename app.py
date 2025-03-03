from flask import Flask, request, redirect
from yookassa import Configuration
from notifier import TelegramNotifier 
from utils import create_payment, get_payment_status, schedule_retry, capture_payment, cancel_payment
import os
from dotenv import load_dotenv
import telegram
import time

load_dotenv()

app = Flask(__name__)


Configuration.account_id = os.getenv("YOOKASSA_SHOP_ID")
Configuration.secret_key = os.getenv("YOOKASSA_SECRET_KEY")


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID_FILE = "chat_id.txt"  

def get_chat_id():
    """Получает Chat ID из файла или через getUpdates (если файла нет)."""
    try:
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        bot = telegram.Bot(token=BOT_TOKEN)
        print("Ожидание сообщения от пользователя для получения Chat ID...")
        for i in range(30):  
            updates = bot.get_updates()
            if updates:
                chat_id = updates[-1].message.chat_id
                with open(CHAT_ID_FILE, "w") as f:
                    f.write(str(chat_id))
                print(f"Chat ID получен и сохранен: {chat_id}")
                return str(chat_id)
            time.sleep(1)
        print("Не удалось получить Chat ID: пользователь не отправил сообщение.")
        return None  
CHAT_ID = get_chat_id()

if not CHAT_ID:
    print("Не удалось получить Chat ID. Завершение работы.")
    exit()

notifier = TelegramNotifier(bot_token=BOT_TOKEN)

@app.route('/create_payment', methods=['POST'])
def create_payment_handler():
    """Обработчик для создания платежа."""
    data = request.form
    amount = float(data['amount'])
    currency = data.get('currency', 'RUB')
    description = data.get('description', 'Оплата товара')
    user_id = data['user_id']
    return_url = data.get("return_url", f"http://localhost:5000/payment_result/{user_id}")

    payment = create_payment(amount, currency, description, return_url, metadata={'user_id': user_id}, capture=True)
    return redirect(payment.confirmation.confirmation_url)

@app.route('/payment_result/<user_id>', methods=['GET'])
def payment_result_handler(user_id):
    """Обработчик для получения результата платежа (после редиректа)."""
    payment_id = request.args.get("orderId")
    if not payment_id:
        return "Ошибка: Не указан ID платежа", 400

    payment = get_payment_status(payment_id)


    if payment.status == 'succeeded':
        message = f"Платеж {payment.id} на сумму {payment.amount.value} {payment.amount.currency} успешно завершен."
        notifier.send_message(CHAT_ID, message)  
        return "Платеж успешно завершен!"
    elif payment.status == 'pending':
        return "Платеж ожидает подтверждения."
    elif payment.status == 'waiting_for_capture':
        message = f"Платеж {payment.id} ожидает списания средств."
        notifier.send_message(CHAT_ID, message)
        capture_result = capture_payment(payment_id)
        if capture_result.status == "succeeded":
            message = f"Средства по платежу {payment.id} успешно списаны."
        else:
            message = f"Не удалось списать средства по платежу {payment.id}."
        notifier.send_message(CHAT_ID, message)
        return "Платеж ожидает списания."
    elif payment.status == 'canceled':
        message = f"Платеж {payment.id} отменен. Причина: {payment.cancellation_details.reason}"
        notifier.send_message(CHAT_ID, message)
        if payment.cancellation_details.reason != "canceled_by_merchant":
            retry_payment = schedule_retry(create_payment, payment.amount.value, payment.amount.currency,
                                             payment.description, f"http://localhost:5000/payment_result/{user_id}",
                                             payment.metadata)
            if retry_payment:
                return redirect(retry_payment.confirmation.confirmation_url)
            else:
                return "Платеж отменен, и повторные попытки не удались."
        return "Платеж отменен."
    else:
        return f"Неизвестный статус платежа: {payment.status}", 500

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    """Обработчик вебхуков от ЮKassa."""
    event_json = request.get_json()

    try:
        if event_json['event'] == 'payment.succeeded':
            payment_id = event_json['object']['id']
            payment = get_payment_status(payment_id)
            message = f"Платеж {payment.id} успешно завершен (через webhook)."
            notifier.send_message(CHAT_ID, message)

        elif event_json['event'] == 'payment.waiting_for_capture':
            payment_id = event_json['object']['id']
            payment = get_payment_status(payment_id)
            message = f"Платеж {payment.id} ожидает списания средств (webhook)."
            notifier.send_message(CHAT_ID, message)

        elif event_json['event'] == 'payment.canceled':
            payment_id = event_json['object']['id']
            payment = get_payment_status(payment_id)
            message = f"Платеж {payment.id} отменен (через webhook). Причина: {payment.cancellation_details.reason}"
            notifier.send_message(CHAT_ID, message)

    except Exception as e:
        print(f"Ошибка при обработке webhook: {e}")
        return "OK", 200  # Обязательно вернуть 200

    return "OK", 200

@app.route('/create_recurrent_payment', methods=['POST'])
def create_recurrent_payment_handler():
    """Обработчик для создания рекуррентного платежа (первый платеж)."""
    data = request.form
    amount = float(data['amount'])
    currency = data.get('currency', 'RUB')
    description = data.get('description', 'Рекуррентный платеж')
    user_id = data['user_id']
    return_url = f"http://localhost:5000/payment_result/{user_id}"

    first_payment = create_payment(amount, currency, description, return_url,
                                   metadata={'user_id': user_id, 'is_recurrent': 'true'}, capture=True)
    return redirect(first_payment.confirmation.confirmation_url)

if __name__ == '__main__':
    app.run(debug=True)