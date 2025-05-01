import requests
import time
import os
from dotenv import load_dotenv

# โหลดค่าจากไฟล์ .env
load_dotenv()

bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
chat_id = os.getenv('TELEGRAM_CHAT_ID')
api_url = os.getenv('STOCK_API_URL')

def fetch_stock_from_server():
    try:
        response = requests.get(api_url)
        print("HTTP Status Code:", response.status_code)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error: API returned status code {response.status_code}")
            return {}
    except Exception as e:
        print("❌ ดึง stock ไม่สำเร็จ:", e)
        return {}

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {'chat_id': chat_id, 'text': message}
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print("✅ ส่งข้อความ Telegram แล้ว")
    else:
        print("❌ ส่งไม่สำเร็จ:", response.text)

def total_stock(stock_data):
    return sum(stock_data.values())

previous_stock = fetch_stock_from_server()
print(f"📊 สต็อกเริ่มต้น: {previous_stock} (รวม {total_stock(previous_stock)} ชิ้น)")

while True:
    time.sleep(10)
    current_stock = fetch_stock_from_server()

    for product, current_qty in current_stock.items():
        previous_qty = previous_stock.get(product, 0)

        if current_qty != previous_qty:
            diff = current_qty - previous_qty
            total = total_stock(current_stock)

            if diff > 0:
                message = f"✅ เติมสินค้า: {product} → {current_qty} ชิ้น\\n📦 สต็อกทั้งหมดในระบบตอนนี้: {total} ชิ้น"
            else:
                message = f"📦 ขายสินค้า: {product} → เหลือ {current_qty} ชิ้น\\n📦 สต็อกทั้งหมดในระบบตอนนี้: {total} ชิ้น"

            send_telegram_message(message)

    previous_stock = current_stock.copy()
