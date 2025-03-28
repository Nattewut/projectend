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

# ตั้งค่า logger
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
    logger.info(f"Store page rendered with {len(products)} products")
    context = {'products': products, 'cartItems': cartItems}
    return render(request, 'store/store.html', context)

def cart(request):
    data = cartData(request)
    cartItems = data['cartItems']
    order = data['order']
    items = data['items']
    logger.info(f"Cart page rendered with {len(items)} items in the cart")
    context = {'items': items, 'order': order, 'cartItems': cartItems}
    return render(request, 'store/cart.html', context)

def checkout(request):
    data = cartData(request)
    cartItems = data['cartItems']
    order = data['order']
    items = data['items']
    logger.info(f"Checkout page rendered with {len(items)} items in the cart")
    context = {
        'items': items,
        'order': order,
        'cartItems': cartItems,
        'OPN_PUBLIC_KEY': settings.OPN_PUBLIC_KEY
    }
    return render(request, 'store/checkout.html', context)

def process_order(request):
    if request.method == "POST":
        logger.info("Processing new order...")
        try:
            # ตัวอย่างการสร้างสินค้าใหม่
            product1 = Product.objects.create(
                name="Shoes",
                price=15.0,
                motor_control_id=1,  # เชื่อมโยงกับมอเตอร์ 1
                image="path_to_image"
            )

            # เพิ่มสินค้าอื่นๆ ตามที่ต้องการ
            logger.info(f"Created product: {product1.name}")

            items = request.POST.get("items")  # รับข้อมูลสินค้า
            logger.info(f"Received items: {items}")

            # การควบคุมมอเตอร์ตามสินค้า
            for item in items:
                product = Product.objects.get(id=item["product_id"])
                motor_id = product.motor_control_id
                control_motor(motor_id)

            logger.info(f"Order processed successfully")
            return JsonResponse({"message": "Order processed successfully"})
        
        except Exception as e:
            logger.error(f"Error in processing order: {str(e)}")
            return JsonResponse({"error": "Invalid request"}, status=400)

@csrf_exempt
def processOrder(request):
    try:
        transaction_id = datetime.datetime.now().timestamp()
        data = json.loads(request.body)
        logger.info(f"Received data from Checkout: {data}")

        if request.user.is_authenticated:
            customer = request.user.customer
            order, created = Order.objects.get_or_create(customer=customer, complete=False)
        else:
            customer, order = guestOrder(request, data)

        if "name" not in data.get("form", {}) or "email" not in data.get("form", {}):
            logger.warning("Missing required fields (name or email)")
            return JsonResponse({"error": "Missing required fields (name or email)"}, status=422)

        calculated_total = sum(item.product.price * item.quantity for item in order.orderitem_set.all())
        logger.info(f"🛒 Order Total: {calculated_total}")

        # ✅ อนุญาตให้ QR Code ถูกสร้างได้ทุกยอดเงินที่มากกว่า 0 บาท
        if calculated_total <= 0:
            logger.warning("Invalid total amount")
            return JsonResponse({'error': 'Invalid total amount'}, status=422)

        order.transaction_id = transaction_id
        order.complete = False
        order.save()

        return create_qr_payment(order)
    except Exception as e:
        logger.error(f"❌ ERROR in processOrder: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

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

        logger.info(f"🔍 ส่งข้อมูลไปที่ Opn API: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        logger.info(f"🔍 ตอบกลับจาก Opn API: {data}")

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
                logger.info("🔍 จำลองสถานะการชำระเงินสำเร็จใน Test Mode")
        
        if "source" in data and "scannable_code" in data["source"]:
            qr_code_url = data["source"]["scannable_code"]["image"]["download_uri"]
            if MODE == 'TEST':
                return JsonResponse({
                    "message": "ชำระเงินสำเร็จ",
                    "qr_code_url": qr_code_url,
                    "order_id": order.id,
                    "amount": order.get_cart_total
                })
            return JsonResponse({"qr_code_url": qr_code_url, "order_id": order.id, "amount": order.get_cart_total})

        else:
            logger.warning("Cannot create QR Code")
            return JsonResponse({"error": "ไม่สามารถสร้าง QR Code ได้"}, status=422)

    except Exception as e:
        logger.error(f"❌ ERROR ใน create_qr_payment: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def verify_signature(request):
    """ ตรวจสอบลายเซ็นจาก Omise Webhook """
    signature = request.headers.get('X-Opn-Signature')
    if not signature:
        logger.warning("Signature missing")
        return False

    secret_key = settings.OPN_WEBHOOK_SECRET  # ดึงจาก settings หรือ environment variables
    body = request.body.decode('utf-8')
    computed_signature = hmac.new(secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()

    if signature != computed_signature:
        logger.warning(f"Invalid signature: {signature} != {computed_signature}")
        return False
    return True

@csrf_exempt
def opn_webhook(request):
    """ รับข้อมูล Webhook จาก Omise """
    logger.info("Received webhook request")

    # ตรวจสอบลายเซ็น
    if not verify_signature(request):
        logger.error("Invalid Webhook Signature")
        return JsonResponse({"error": "Invalid Webhook Signature"}, status=400)

    try:
        data = json.loads(request.body)
        logger.info(f"Webhook data: {data}")  # บันทึกข้อมูลที่ได้รับจาก Webhook
        
        event_type = data.get('key')
        charge_status = data.get('data', {}).get('object', {}).get('status')

        # ตรวจสอบว่าเป็น event 'charge.complete' และการชำระเงินสำเร็จ
        if event_type == 'charge.complete' and charge_status == 'successful':
            charge_id = data.get('data', {}).get('object', {}).get('id')
            logger.info(f"Payment successful for charge: {charge_id}")
            # ทำการอัพเดตสถานะการชำระเงินหรือข้อมูลตามความต้องการ

        return JsonResponse({"status": "success"}, status=200)
    
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return JsonResponse({"error": "Internal Server Error"}, status=500)

GPIO.setmode(GPIO.BOARD)  # ใช้หมายเลขขา GPIO ตามแบบ BOARD (ตัวเลขพิน)

motor_pin_1 = 11  # GPIO pin สำหรับมอเตอร์ 1
motor_pin_2 = 13  # GPIO pin สำหรับมอเตอร์ 2
motor_pin_3 = 15  # GPIO pin สำหรับมอเตอร์ 3

GPIO.setup(motor_pin_1, GPIO.OUT)
GPIO.setup(motor_pin_2, GPIO.OUT)
GPIO.setup(motor_pin_3, GPIO.OUT)

motor_feedback_pin_1 = 16
motor_feedback_pin_2 = 18
motor_feedback_pin_3 = 22

GPIO.setup(motor_feedback_pin_1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(motor_feedback_pin_2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(motor_feedback_pin_3, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def control_motor(motor_id):
    """ ฟังก์ชันควบคุมมอเตอร์ตาม id """
    logger.info(f"Controlling motor {motor_id}")  

    if motor_id == 1:
        logger.info("Starting Motor 1...")
        GPIO.output(motor_pin_1, GPIO.HIGH)
        while GPIO.input(motor_feedback_pin_1) == GPIO.HIGH:
            time.sleep(0.1)
        GPIO.output(motor_pin_1, GPIO.LOW)
        logger.info("Motor 1 stopped")

    elif motor_id == 2:
        logger.info("Starting Motor 2...")
        GPIO.output(motor_pin_2, GPIO.HIGH)
        while GPIO.input(motor_feedback_pin_2) == GPIO.HIGH:
            time.sleep(0.1)
        GPIO.output(motor_pin_2, GPIO.LOW)
        logger.info("Motor 2 stopped")

    elif motor_id == 3:
        logger.info("Starting Motor 3...")
        GPIO.output(motor_pin_3, GPIO.HIGH)
        while GPIO.input(motor_feedback_pin_3) == GPIO.HIGH:
            time.sleep(0.1)
        GPIO.output(motor_pin_3, GPIO.LOW)
        logger.info("Motor 3 stopped")

control_motor(1)
control_motor(2)
control_motor(3)

GPIO.cleanup()

def updateItem(request):
    data = json.loads(request.body)
    productId = data.get('productId')
    action = data.get('action')
    
    logger.info(f"Action: {action}, Product: {productId}")

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


