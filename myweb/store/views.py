from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
import json
import datetime
import requests
from django.conf import settings
import base64
from django.views.decorators.csrf import csrf_exempt
import os
import logging
from .models import *
from .utils import cookieCart, cartData, guestOrder
from .models import Order
from .utils import get_base_url
import queue
import threading

# ตั้งค่า logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler('app.log', encoding='utf-8')  # ใช้ UTF-8 แทน cp874
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

def get_base_url():
    return "https://gnat-crucial-partly.ngrok-free.app"

def store(request):
    data = cartData(request)
    cartItems = data['cartItems']
    products = Product.objects.all()
    logger.info(f"Store page rendered with {len(products)} products")
    return render(request, 'store/store.html', {'products': products, 'cartItems': cartItems})

def cart(request):
    data = cartData(request)
    cartItems = data['cartItems']
    order = data['order']
    items = data['items']
    logger.info(f"Cart page rendered with {len(items)} items in the cart")
    return render(request, 'store/cart.html', {'items': items, 'order': order, 'cartItems': cartItems})

def checkout(request):
    data = cartData(request)
    cartItems = data['cartItems']
    order = data['order']
    items = data['items']
    logger.info(f"Checkout page rendered with {len(items)} items in the cart")
    return render(request, 'store/checkout.html', {
        'items': items,
        'order': order,
        'cartItems': cartItems,
        'OPN_PUBLIC_KEY': settings.OPN_PUBLIC_KEY
    })

def updateItem(request):
    data = json.loads(request.body)
    productId = data.get('productId')
    action = data.get('action')
    logger.info(f"Action: {action}, Product: {productId}")

    customer = request.user.customer
    product = Product.objects.get(id=productId)
    order, _ = Order.objects.get_or_create(customer=customer, complete=False)
    orderItem, _ = OrderItem.objects.get_or_create(order=order, product=product)

    if action == 'add':
        orderItem.quantity += 1
    elif action == 'remove':
        orderItem.quantity -= 1

    orderItem.save()

    if orderItem.quantity <= 0:
        orderItem.delete()

    return JsonResponse("Item was updated", safe=False)

@csrf_exempt
def processOrder(request):
    try:
        transaction_id = datetime.datetime.now().timestamp()
        data = json.loads(request.body)
        logger.info(f"Received data from Checkout: {data}")

        if request.user.is_authenticated:
            customer = request.user.customer
            order, _ = Order.objects.get_or_create(customer=customer, complete=False)
        else:
            customer, order = guestOrder(request, data)

        if "name" not in data.get("form", {}) or "email" not in data.get("form", {}):
            logger.warning("Missing required fields (name or email)")
            return JsonResponse({"error": "Missing required fields (name or email)"}, status=422)

        total = sum(item.product.price * item.quantity for item in order.orderitem_set.all())
        logger.info(f"Order Total: {total}")  

        if total <= 0:
            logger.warning("Invalid total amount")
            return JsonResponse({'error': 'Invalid total amount'}, status=422)

        order.transaction_id = transaction_id
        order.complete = False
        order.save()

        return create_qr_payment(order)
    except Exception as e:
        logger.error(f"❌ ERROR in processOrder: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

def create_qr_payment(order):
    try:
        # คำนวณจำนวนเงินที่ต้องการชำระในหน่วยสตางค์
        amount = int(order.get_cart_total * 100)
        logger.info(f"Amount in cents: {amount}")

        # URL สำหรับการสร้าง charge ผ่าน Opn API
        url = "https://api.omise.co/charges"
        auth_token = base64.b64encode(f"{settings.OPN_SECRET_KEY}:".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_token}",
            "Content-Type": "application/json"
        }

        # กำหนด return_uri ว่าจะไปที่หน้าไหนหลังจากชำระเงินสำเร็จหรือไม่สำเร็จ
        if order.payment_status == "failed":
            return_uri = f"{get_base_url()}/payment_failed/{order.id}/"
        else:
            return_uri = f"{get_base_url()}/payment_success/{order.id}/"
        
        logger.info(f"Return URI: {return_uri}")

        # ดึงข้อมูลมอเตอร์จากคำสั่งซื้อ
        motor_data = [
            {"motor_id": item.product.motor.id, "motor_rounds": item.quantity}
            for item in order.orderitem_set.all() if item.product.motor
        ]

        # ข้อมูลที่ต้องส่งไปยัง Opn API
        payload = {
            "amount": amount,
            "currency": "thb",
            "source": {"type": "promptpay"},
            "description": f"Order {order.id}",
            "return_uri": return_uri,
            "metadata": { 
                "orderId": order.id,
                "motor_data": motor_data  # เพิ่มข้อมูลมอเตอร์ใน metadata
            },
            "version": "2019-05-29"
        }

        # ส่งข้อมูลไปที่ Opn API
        logger.info(f"🔍 ส่งข้อมูลไปที่ Opn API: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        logger.info(f"🔍 ตอบกลับจาก Opn API: {data}")

        # ตรวจสอบว่าได้รับข้อมูล scannable_code หรือไม่
        if "source" in data and "scannable_code" in data["source"]:
            qr_url = data["source"]["scannable_code"]["image"]["download_uri"]

            order.charge_id = data["id"]  # ✅ เพิ่มตรงนี้
            order.save()

            return JsonResponse({
                "message": "ชำระเงินสำเร็จ",
                "qr_code_url": qr_url,
                "order_id": order.id,
                "amount": order.get_cart_total
            })

        logger.warning(f"❌ QR Code not found in the response data: {data}")
        return JsonResponse({"error": "ไม่สามารถสร้าง QR Code ได้"}, status=422)

    except Exception as e:
        logger.error(f"❌ ERROR ใน create_qr_payment: {str(e)}")
        return JsonResponse({"error": f"Error: {str(e)}"}, status=500)

@csrf_exempt
def opn_webhook(request):
    try:
        if request.method == 'POST':
            try:
                raw_body = request.body.decode('utf-8')
                logger.info(f"📥 Raw request body: {raw_body}")
                body = json.loads(raw_body)
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON decode error in webhook: {e}")
                return JsonResponse({"message": "Invalid JSON"}, status=400)

            logger.info("✅ Webhook received with key: %s", body.get('key'))

            event_key = body.get('key')
            payment_data = body.get('data')
            charge_id = payment_data.get('id')
            order_id = payment_data.get('metadata', {}).get('orderId')

            try:
                order = Order.objects.get(id=order_id)

                if event_key == 'charge.create':
                    logger.info(f"Received charge.create for charge_id: {charge_id}, order_id: {order_id}")
                    order.payment_status = 'created'
                    order.charge_id = charge_id  # ✅ บันทึก charge_id ด้วย
                    order.save()
                    logger.info(f"✅ Updated order {order_id} with status: {order.payment_status}")

                elif event_key == 'charge.complete':
                    logger.info("✅ Webhook: charge.complete ถูกเรียกแล้ว")
                    logger.info(f"💾 Payload: {json.dumps(body, indent=2)}")

                    if order.charge_id == charge_id and order.payment_status != 'successful':
                        order.payment_status = payment_data.get('status')
                        order.save()
                        logger.info(f"🎉 Updated order {order_id} to: {order.payment_status}")

                        # ตรวจสอบสถานะการชำระเงินก่อนเรียกใช้งานมอเตอร์
                        if order.payment_status == 'successful':
                            logger.info(f"🔧 Calling motor control for order {order_id} after payment success.")
                            send_motor_control_request(order_id)
                        else:
                            logger.warning(f"❌ Payment failed for Order {order_id}, motor control will not be triggered.")
                    
                elif event_key == 'charge.failed':
                    # การชำระเงินล้มเหลว
                    logger.warning(f"❌ Payment failed for Order {order_id}, charge_id: {charge_id}")
                    order.payment_status = 'failed'
                    order.save()
                    logger.info(f"❌ Updated order {order_id} to status: failed")

                elif event_key == 'charge.cancelled':
                    # การชำระเงินถูกยกเลิก
                    logger.warning(f"❌ Payment cancelled for Order {order_id}, charge_id: {charge_id}")
                    order.payment_status = 'cancelled'
                    order.save()
                    logger.info(f"❌ Updated order {order_id} to status: cancelled")

                else:
                    logger.warning(f"❌ Unexpected event type: {event_key}")
                    return JsonResponse({"message": "Invalid event type."}, status=400)

            except Order.DoesNotExist:
                logger.error(f"Order with id {order_id} not found.")

            return JsonResponse({"message": "Webhook processed successfully."}, status=200)

        return JsonResponse({"message": "Invalid HTTP method."}, status=405)

    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}")
        return JsonResponse({"message": "Error processing webhook."}, status=500)

from django.views.decorators.http import require_GET

import threading

motor_lock = threading.Lock()

@require_GET
def check_payment_status(request):
    order_id = request.GET.get('order_id')
    try:
        order = Order.objects.get(id=order_id)
        logger.info(f"🔍 ตรวจสถานะ Order #{order_id} => {order.payment_status}")
        return JsonResponse({'status': order.payment_status})
    except Order.DoesNotExist:
        logger.warning(f"❌ ไม่พบ Order #{order_id}")
        return JsonResponse({'status': 'not_found'}, status=404)

def get_motor_data_from_order(order_id):
    # ดึงข้อมูลคำสั่งซื้อจากฐานข้อมูล
    order = get_object_or_404(Order, id=order_id)
    motor_data = []
    
    for item in order.orderitem_set.all():
        motor_data.append({
            'motor_id': item.product.motor.id,  # ใช้ motor.id จากสินค้า
            'motor_rounds': item.quantity  # ใช้จำนวนสินค้าที่ซื้อเป็นจำนวนรอบ
        })
    
    return motor_data

def send_motor_control_request(order_id):
    order = get_object_or_404(Order, id=order_id)

    # ตรวจสอบสถานะการชำระเงินก่อนการส่งคำขอควบคุมมอเตอร์
    if order.payment_status == 'successful':
        motor_data = get_motor_data_from_order(order_id)  # ดึงข้อมูลมอเตอร์จากคำสั่งซื้อ
        raspberry_pi_url = "http://172.20.10.3:5000/control_motor/"

        payload = {
            "motor_data": motor_data
        }

        logger.info(f"กำลังส่งคำขอไปที่ Raspberry Pi: {payload}")

        # ใช้ Lock เพื่อป้องกันการทำงานพร้อมกัน
        with motor_lock:
            try:
                response = requests.post(raspberry_pi_url, json=payload)
                logger.info(f"Response from Raspberry Pi: {response.status_code} - {response.text}")
                response.raise_for_status()
                logger.info(f"✅ มอเตอร์ทั้งหมดควบคุมเสร็จสิ้นสำหรับ order {order_id}")
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ เกิดข้อผิดพลาดในการควบคุมมอเตอร์สำหรับ order {order_id}: {e}")
    else:
        logger.warning(f"❌ Payment not successful for Order #{order_id}, motor control will not be triggered.")


def payment_success(request, order_id):
    logger.info(f"🔁 payment_success view ถูกเรียกด้วย order_id: {order_id}")
    order = get_object_or_404(Order, id=order_id)

    # ตรวจสอบสถานะการชำระเงินก่อนส่งคำขอควบคุมมอเตอร์
    if order.payment_status == 'successful':
        # เพิ่มคำขอควบคุมมอเตอร์เข้าไปในคิว
        add_motor_request(order_id)
    else:
        logger.warning(f"❌ Payment failed for Order #{order_id}, motor will not be controlled.")

    return render(request, 'store/payment_success.html', {'order': order})

def payment_failed(request, order_id):
    logger.info(f"🔁 payment_failed view ถูกเรียกด้วย order_id: {order_id}")
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'store/payment_failed.html', {'order': order})

# คิวสำหรับเก็บคำขอควบคุมมอเตอร์
motor_queue = queue.Queue()

# ตัวแปร Lock เพื่อป้องกันการทำงานพร้อมกัน
motor_lock = threading.Lock()

def process_motor_request(order_id):
    """
    ฟังก์ชันนี้จะควบคุมมอเตอร์สำหรับออเดอร์หนึ่งๆ
    """
    logger.info(f"กำลังควบคุมมอเตอร์สำหรับออเดอร์ {order_id}...")
    time.sleep(5)  # จำลองการควบคุมมอเตอร์ที่ใช้เวลา
    logger.info(f"ควบคุมมอเตอร์เสร็จสิ้นสำหรับออเดอร์ {order_id}")

def motor_controller():
    """
    ฟังก์ชันนี้จะทำงานตลอดเวลาเพื่อตรวจสอบคำขอในคิว
    """
    while True:
        # รอคำขอจากคิว
        order_id = motor_queue.get()  # รอให้มีคำขอมา
        if order_id is None:  # ถ้าเจอ None ให้หยุดทำงาน
            break
        # ใช้ Lock เพื่อควบคุมการทำงานให้ทำทีละคำขอ
        with motor_lock:
            process_motor_request(order_id)
        motor_queue.task_done()  # แจ้งว่าเสร็จสิ้นการทำงาน

def add_motor_request(order_id):
    """
    ฟังก์ชันนี้จะเพิ่มคำขอควบคุมมอเตอร์เข้าสู่คิว
    """
    motor_queue.put(order_id)
    logger.info(f"เพิ่มคำขอควบคุมมอเตอร์สำหรับออเดอร์ {order_id} เข้าคิว")

# สร้างและเริ่มต้น Thread สำหรับการควบคุมมอเตอร์
motor_thread = threading.Thread(target=motor_controller)
motor_thread.start()






