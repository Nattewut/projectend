from django.shortcuts import render
from django.http import JsonResponse
import json
import datetime
from .models import * 
from .utils import cookieCart, cartData, guestOrder
import requests
from django.conf import settings
import base64
from django.views.decorators.csrf import csrf_exempt
import os
from .models import Order
import time
from django.shortcuts import redirect
from .models import Product
import RPi.GPIO as GPIO
import logging

logger = logging.getLogger(__name__)

def get_base_url():
    """ ใช้ฟังก์ชันนี้เพื่อกำหนด base URL ให้ถูกต้อง """
    return "https://gnat-crucial-partly.ngrok-free.app"

def store(request):
    data = cartData(request)
    cartItems = data['cartItems']
    order = data['order']
    items = data['items']
    products = Product.objects.all()
    context = {'products': products, 'cartItems': cartItems}
    return render(request, 'store/store.html', context)

def cart(request):
    data = cartData(request)
    cartItems = data['cartItems']
    order = data['order']
    items = data['items']
    context = {'items': items, 'order': order, 'cartItems': cartItems}
    return render(request, 'store/cart.html', context)

def checkout(request):
    data = cartData(request)
    cartItems = data['cartItems']
    order = data['order']
    items = data['items']
    context = {
        'items': items,
        'order': order,
        'cartItems': cartItems,
        'OPN_PUBLIC_KEY': settings.OPN_PUBLIC_KEY
    }
    return render(request, 'store/checkout.html', context)

def process_order(request):
    if request.method == "POST":
        # ตัวอย่างการสร้างสินค้าใหม่
        product1 = Product.objects.create(
            name="Shoes",
            price=15.0,
            motor_control_id=1,  # เชื่อมโยงกับมอเตอร์ 1
            image="path_to_image"
        )

        product2 = Product.objects.create(
            name="Headphones",
            price=10.0,
            motor_control_id=2,  # เชื่อมโยงกับมอเตอร์ 2
            image="path_to_image"
        )

        product3 = Product.objects.create(
            name="Poster",
            price=5.0,
            motor_control_id=3,  # เชื่อมโยงกับมอเตอร์ 3
            image="path_to_image"
        )

        # คุณสามารถเพิ่ม logic ที่เชื่อมโยงมอเตอร์ตามสินค้าในคำสั่งซื้อ
        # เช่น เมื่อลูกค้าซื้อสินค้า:
        items = request.POST.get("items")  # รับข้อมูลสินค้า

        # ตัวอย่างเชื่อมโยงสินค้าและควบคุมมอเตอร์
        for item in items:
            product = Product.objects.get(id=item["product_id"])
            motor_id = product.motor_control_id

            # สมมุติว่าเราเรียกฟังก์ชันที่เชื่อมโยงกับมอเตอร์
            control_motor(motor_id)

        return JsonResponse({"message": "Order processed successfully"})
    
    return JsonResponse({"error": "Invalid request"}, status=400)


@csrf_exempt
def processOrder(request):
    try:
        transaction_id = datetime.datetime.now().timestamp()
        data = json.loads(request.body)
        print("✅ รับข้อมูลจาก Checkout:", data)

        if request.user.is_authenticated:
            customer = request.user.customer
            order, created = Order.objects.get_or_create(customer=customer, complete=False)
        else:
            customer, order = guestOrder(request, data)

        if "name" not in data.get("form", {}) or "email" not in data.get("form", {}):
            return JsonResponse({"error": "Missing required fields (name or email)"}, status=422)  # ใช้ 422 แทน 400

        calculated_total = sum(item.product.price * item.quantity for item in order.orderitem_set.all())
        print(f"🛒 Order Total: {calculated_total}")

        # ✅ อนุญาตให้ QR Code ถูกสร้างได้ทุกยอดเงินที่มากกว่า 0 บาท
        if calculated_total <= 0:
            return JsonResponse({'error': 'Invalid total amount'}, status=422)  # ใช้ 422 แทน 400

        order.transaction_id = transaction_id
        order.complete = False
        order.save()

        return create_qr_payment(order)
    except Exception as e:
        print(f"❌ ERROR in processOrder: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)  # ใช้ 500 สำหรับ Server Error

# เช็คว่าโค้ดอยู่ใน Test Mode หรือ Live Mode
# ตรวจสอบว่าโค้ดอยู่ใน Test Mode หรือ Live Mode
MODE = os.getenv('MODE', 'TEST')

def create_qr_payment(order):
    try:
        amount = int(order.get_cart_total * 100)  # จำนวนเงินที่ต้องการในสตางค์
        base_url = get_base_url()
        url = "https://api.omise.co/charges"

        secret_key = settings.OPN_SECRET_KEY
        auth_token = base64.b64encode(f"{secret_key}:".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "amount": amount,
            "currency": "thb",
            "source": {"type": "promptpay"},
            "description": f"Order {order.id}",
            "return_uri": f"{base_url}/payment_success/{order.id}/"
        }

        print(f"🔍 ส่งข้อมูลไปที่ Opn API: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        print(f"🔍 ตอบกลับจาก Opn API: {data}")

        # เช็คว่าโค้ดอยู่ใน Test Mode หรือ Live Mode
        if MODE == 'TEST':
            # หากเป็น Test Mode, ระบบจะจำลองการชำระเงิน
            if "source" not in data:
                data = {
                    "source": {
                        "scannable_code": {
                            "image": {
                                "download_uri": data.get('scannable_code', {}).get('image', {}).get('download_uri', 'https://some/fake/qr-code-image.png')
                            }
                        }
                    }
                }
                print("🔍 จำลองสถานะการชำระเงินสำเร็จใน Test Mode")
        
        if "source" in data and "scannable_code" in data["source"]:
            qr_code_url = data["source"]["scannable_code"]["image"]["download_uri"]
            
            # หากใน Test Mode ก็ให้ส่ง QR Code ที่จำลองขึ้น
            if MODE == 'TEST':
                return JsonResponse({
                    "message": "ชำระเงินสำเร็จ",  # ข้อความที่จะแสดงเมื่อสถานะเป็น Test Mode
                    "qr_code_url": qr_code_url,
                    "order_id": order.id,
                    "amount": order.get_cart_total
                })
            return JsonResponse({"qr_code_url": qr_code_url, "order_id": order.id, "amount": order.get_cart_total})

        else:
            return JsonResponse({"error": "ไม่สามารถสร้าง QR Code ได้"}, status=422)  # ใช้ 422 แทน 400

    except Exception as e:
        print(f"❌ ERROR ใน create_qr_payment: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def opn_webhook(request):
    """ ตรวจสอบสถานะการชำระเงินจาก Opn Payments """
    try:
        # แปลงข้อมูลจาก JSON
        data = json.loads(request.body)
        
        # บันทึกข้อมูลที่ได้รับจาก Webhook ลงใน logs
        logger.info(f"Received Webhook Data: {data}")
        
        # ตรวจสอบว่า JSON ที่ได้รับมีข้อมูลครบถ้วนหรือไม่
        if not validate_json(data):
            logger.error("Invalid JSON format. Missing required keys.")
            return JsonResponse({"error": "Invalid JSON format. Missing required keys."}, status=422)  # ใช้ 422 แทน 400
        
        # ตรวจสอบข้อมูลที่ได้รับจาก Opn
        event = data.get("event")
        charge_id = data.get("data", {}).get("id")
        status = data.get("data", {}).get("status")

        # ตรวจสอบว่า charge_id ถูกต้อง
        if not charge_id:
            logger.error("Charge ID is missing in the request.")
            return JsonResponse({"error": "Charge ID missing"}, status=422)  # ใช้ 422 แทน 400

        # ตรวจสอบว่า event และ status ถูกต้อง
        if event == "charge.complete" and status == "successful":
            try:
                # ค้นหา Order โดยใช้ charge_id
                order = Order.objects.get(charge_id=charge_id)
                order.complete = True
                order.save()

                # ควบคุมมอเตอร์
                for item in order.items.all():
                    motor_id = item.product.motor_control_id
                    control_motor(motor_id)

                logger.info(f"Order {order.id} successfully updated.")
                return JsonResponse({"message": "Payment verified, order updated."})
            except Order.DoesNotExist:
                logger.error(f"Order with charge_id {charge_id} not found.")
                return JsonResponse({"error": "Order not found"}, status=404)  # ใช้ 404 เมื่อไม่พบคำสั่งซื้อ

        # ถ้า event ไม่ใช่ charge.complete หรือสถานะไม่สำเร็จ
        logger.warning("Payment not successful")
        return JsonResponse({"error": "Payment not successful"}, status=422)  # ใช้ 422 แทน 400

    except json.JSONDecodeError:
        logger.error("Failed to decode JSON.")
        return JsonResponse({"error": "Invalid JSON data"}, status=400)  # 400 ใช้สำหรับ JSON Decode Error
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)  # ใช้ 500 สำหรับ Server Error


def validate_json(data):
    """ ตรวจสอบว่า JSON ที่ได้รับมีข้อมูลครบถ้วนหรือไม่ """
    # ตรวจสอบว่า 'event' และ 'data' มีใน JSON
    if 'event' not in data or 'data' not in data:
        logger.error("Missing 'event' or 'data' key")
        return False
    
    # ตรวจสอบว่าใน 'data' มี key 'id' และ 'status'
    if 'id' not in data['data'] or 'status' not in data['data']:
        logger.error("Missing 'id' or 'status' in 'data' key")
        return False
    
    return True


# ตั้งค่า GPIO
GPIO.setmode(GPIO.BOARD)  # ใช้หมายเลขขา GPIO ตามแบบ BOARD (ตัวเลขพิน)

# กำหนดขา GPIO ที่จะควบคุมมอเตอร์ 3 ตัว
motor_pin_1 = 11  # GPIO pin สำหรับมอเตอร์ 1
motor_pin_2 = 13  # GPIO pin สำหรับมอเตอร์ 2
motor_pin_3 = 15  # GPIO pin สำหรับมอเตอร์ 3

# ตั้งค่าขา GPIO เป็น OUT
GPIO.setup(motor_pin_1, GPIO.OUT)
GPIO.setup(motor_pin_2, GPIO.OUT)
GPIO.setup(motor_pin_3, GPIO.OUT)

# ตั้งค่า feedback pin สำหรับตรวจสอบการหมุนของมอเตอร์
motor_feedback_pin_1 = 16  # สมมุติว่ามี feedback pin สำหรับมอเตอร์ 1
motor_feedback_pin_2 = 18  # สมมุติว่ามี feedback pin สำหรับมอเตอร์ 2
motor_feedback_pin_3 = 22  # สมมุติว่ามี feedback pin สำหรับมอเตอร์ 3

# ตั้งค่าขา feedback pins เป็น INPUT
GPIO.setup(motor_feedback_pin_1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(motor_feedback_pin_2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(motor_feedback_pin_3, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def control_motor(motor_id):
    """ ฟังก์ชันควบคุมมอเตอร์ตาม id """
    print(f"Controlling motor {motor_id}")  # พิมพ์ว่าเริ่มควบคุมมอเตอร์ตัวไหน

    # การควบคุมมอเตอร์ตาม id
    if motor_id == 1:
        print("Starting Motor 1...")  # พิมพ์ว่าเริ่มมอเตอร์ 1
        GPIO.output(motor_pin_1, GPIO.HIGH)  # เปิดมอเตอร์ 1
        while GPIO.input(motor_feedback_pin_1) == GPIO.HIGH:
            time.sleep(0.1)  # รอให้มอเตอร์หมุนจนกว่าจะครบ 1 รอบ
        GPIO.output(motor_pin_1, GPIO.LOW)  # ปิดมอเตอร์ 1
        print("Motor 1 stopped")  # พิมพ์ว่า มอเตอร์ 1 หยุดแล้ว

    elif motor_id == 2:
        print("Starting Motor 2...")  # พิมพ์ว่าเริ่มมอเตอร์ 2
        GPIO.output(motor_pin_2, GPIO.HIGH)  # เปิดมอเตอร์ 2
        while GPIO.input(motor_feedback_pin_2) == GPIO.HIGH:
            time.sleep(0.1)
        GPIO.output(motor_pin_2, GPIO.LOW)  # ปิดมอเตอร์ 2
        print("Motor 2 stopped")  # พิมพ์ว่า มอเตอร์ 2 หยุดแล้ว

    elif motor_id == 3:
        print("Starting Motor 3...")  # พิมพ์ว่าเริ่มมอเตอร์ 3
        GPIO.output(motor_pin_3, GPIO.HIGH)  # เปิดมอเตอร์ 3
        while GPIO.input(motor_feedback_pin_3) == GPIO.HIGH:
            time.sleep(0.1)
        GPIO.output(motor_pin_3, GPIO.LOW)  # ปิดมอเตอร์ 3
        print("Motor 3 stopped")  # พิมพ์ว่า มอเตอร์ 3 หยุดแล้ว

# ทดสอบการควบคุมมอเตอร์
control_motor(1)  # สั่งให้มอเตอร์ 1 ทำงาน
control_motor(2)  # สั่งให้มอเตอร์ 2 ทำงาน
control_motor(3)  # สั่งให้มอเตอร์ 3 ทำงาน

# ปิด GPIO
GPIO.cleanup()

def updateItem(request):
    data = json.loads(request.body)
    productId = data.get('productId')
    action = data.get('action')
    
    print(f"✅ Action: {action}, Product: {productId}")

    customer = request.user.customer
    product = Product.objects.get(id=productId)
    order, created = Order.objects.get_or_create(customer=customer, complete=False)

    orderItem, created = OrderItem.objects.get_or_create(order=order, product=product)

    if action == 'add':
        orderItem.quantity += 1
    elif action == 'remove':
        orderItem.quantity -= 1

    orderItem.save()

    if orderItem.quantity <= 0:
        orderItem.delete()

    return JsonResponse("Item was updated", safe=False)

def payment_success(request, order_id):
    order = Order.objects.get(id=order_id)
    return render(request, 'payment_success.html', {'order': order})

def success(request):
    return render(request, 'success.html')  

def cancel(request):
    return render(request, 'cancel.html')


