
import requests
import random
import time

# Token / Chat ID จาก BotFather และ getUpdates
bot_token = '8060451496:AAH2q09yz4a_EK0fYsTfflYCcRcvdLJkFbQ'
chat_id = '6802681096'
product_count = 0

# ดึง stock ล่าสุดจาก Django API
def fetch_stock_from_server():
    try:
        response = requests.get('https://gnat-crucial-partly.ngrok-free.app/api/stock/')
        data = response.json()
        return data['stock']
    except Exception as e:
        print("❌ ดึง stock ไม่สำเร็จ:", e)
        return 0

# ส่งข้อความ Telegram
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {'chat_id': chat_id, 'text': message}
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print("✅ ส่งข้อความ Telegram แล้ว")
    else:
        print("❌ ส่งไม่สำเร็จ:", response.text)

# ฟังก์ชันขายสินค้า
def sell_product(quantity):
    global product_count
    if product_count <= 0:
        send_telegram_message("❌ สินค้าหมดแล้ว กรุณาเติมสินค้า!")
        print("❌ สินค้าหมด")
        return

    if quantity > product_count:
        quantity = product_count

    product_count -= quantity
    msg = f"📦 ขายสินค้า {quantity} ชิ้น → เหลือในสต็อก {product_count} ชิ้น"
    print(msg)
    send_telegram_message(msg)

# เริ่มทำงาน
product_count = fetch_stock_from_server()
print(f"📊 สินค้าเริ่มต้นจากระบบ: {product_count} ชิ้น")

# จำลองการขายเรื่อย ๆ
while product_count > 0:
    qty = random.randint(1, 5)  # ลูกค้าซื้อทีละ 1-5 ชิ้น
    sell_product(qty)
    time.sleep(2)
