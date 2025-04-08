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

# ตั้งค่า logger
# logger setup with UTF-8 encoding
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

@csrf_exempt
def processOrder(request):
    try:
        transaction_id = datetime.datetime.now().timestamp()
        data = json.loads(request.body)
        logger.info(f"Received data from Checkout: {data}")

        # ตรวจสอบการสร้างคำสั่งซื้อ
        if request.user.is_authenticated:
            customer = request.user.customer
            order, created = Order.objects.get_or_create(customer=customer, complete=False)
            logger.info(f"Order fetched: {order.id}, New Order: {created}")
        else:
            customer, order = guestOrder(request, data)

        # ตรวจสอบว่า name และ email มีอยู่ในข้อมูลหรือไม่
        if "name" not in data.get("form", {}) or "email" not in data.get("form", {}):
            logger.warning("Missing required fields (name or email)")
            return JsonResponse({"error": "Missing required fields (name or email)"}, status=422)

        # คำนวณยอดรวมจากรายการในคำสั่งซื้อ
        total = sum(item.product.price * item.quantity for item in order.orderitem_set.all())
        logger.info(f"Order Total: {total}")  

        if total <= 0:
            logger.warning("Invalid total amount")
            return JsonResponse({'error': 'Invalid total amount'}, status=422)

        # ตั้งค่า transaction_id และสถานะคำสั่งซื้อ
        order.transaction_id = transaction_id
        order.complete = False
        order.save()

        logger.info(f"Order {order.id} is now created with transaction ID: {transaction_id}")
        
        # สร้าง QR Code สำหรับการชำระเงิน
        return create_qr_payment(order)

    except Exception as e:
        logger.error(f"❌ ERROR in processOrder: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

import requests
import base64
import datetime
from django.http import JsonResponse
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def create_qr_payment(order):
    try:
        # คำนวณจำนวนเงิน (เป็นสตางค์)
        amount = int(order.get_cart_total() * 100)  # เรียก method get_cart_total() แทน
        logger.info(f"Amount in cents: {amount}")

        # URL สำหรับการสร้าง charge ผ่าน Omise API
        url = "https://api.omise.co/charges"
        auth_token = base64.b64encode(f"{settings.OPN_SECRET_KEY}:".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_token}",
            "Content-Type": "application/json"
        }

        # ตรวจสอบ URL ที่จะใช้เป็น return_uri
        if order.payment_status == "failed":
            return_uri = f"{get_base_url()}/payment_failed/{order.id}/"
        else:
            return_uri = f"{get_base_url()}/payment_success/{order.id}/"
        
        logger.info(f"Return URI: {return_uri}")

        payload = {
            "amount": amount,
            "currency": "thb",
            "source": {"type": "installment_kbank"},  # เปลี่ยนประเภทเป็นแบบผ่อนชำระที่ต้องการ
            "description": f"Order {order.id}",
            "return_uri": return_uri,
            "metadata": {"orderId": order.id},
            "version": "2019-05-29"
        }

        logger.info(f"🔍 ส่งข้อมูลไปที่ Omise API: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        logger.info(f"🔍 ตอบกลับจาก Omise API: {data}")

        # ตรวจสอบว่าได้รับข้อมูล scannable_code หรือไม่
        if "source" in data and "scannable_code" in data["source"]:
            qr_url = data["source"]["scannable_code"]["image"]["download_uri"]
            return JsonResponse({
                "message": "ชำระเงินสำเร็จ",
                "qr_code_url": qr_url,
                "order_id": order.id,
                "amount": order.get_cart_total()  # เรียก method get_cart_total() แทน
            })

        # หากไม่มี scannable_code ใน response
        logger.warning(f"❌ QR Code not found in the response data: {data}")
        return JsonResponse({"error": "ไม่สามารถสร้าง QR Code ได้"}, status=422)

    except requests.exceptions.RequestException as e:
        # จัดการข้อผิดพลาดจากการเชื่อมต่อ
        logger.error(f"❌ Network error: {str(e)}")
        return JsonResponse({"error": "Error connecting to the payment gateway. Please try again."}, status=500)

    except Exception as e:
        logger.error(f"❌ ERROR ใน create_qr_payment: {str(e)}")
        return JsonResponse({"error": f"Error: {str(e)}"}, status=500)

from django.http import HttpResponseRedirect

@csrf_exempt
def opn_webhook(request):
    try:
        # Only handle POST requests
        if request.method == 'POST':
            # Parse the incoming JSON data
            body = json.loads(request.body)
            logger.info("Received webhook: %s", body)

            # Handle charge.create event
            if body.get('key') == 'charge.create':
                # Handle charge.create as you did before
                pass

            # Handle charge.complete event (payment complete)
            elif body.get('key') == 'charge.complete':
                payment_data = body.get('data')
                charge_id = payment_data.get('id')
                order_id = payment_data.get('metadata', {}).get('orderId')

                logger.info(f"Received charge.complete for charge_id: {charge_id}, order_id: {order_id}")

                try:
                    order = Order.objects.get(id=order_id)
                    if order.payment_status == 'pending' and order.charge_id == charge_id:
                        order.payment_status = payment_data.get('status')
                        order.save()
                        logger.info(f"Updated order {order_id} with status: {order.payment_status}")

                        # Redirect based on the payment status
                        if order.payment_status == 'successful':
                            logger.info(f"Redirecting to payment success page for order {order.id}")
                            return HttpResponseRedirect(f"{get_base_url()}/payment_success/{order.id}/")
                        else:
                            logger.info(f"Redirecting to payment failed page for order {order.id}")
                            return HttpResponseRedirect(f"{get_base_url()}/payment_failed/{order.id}/")

                except Order.DoesNotExist:
                    logger.error(f"Order with id {order_id} not found.")

            else:
                logger.warning(f"Unexpected event type: {body.get('key')}")
                return JsonResponse({"message": "Invalid event type."}, status=400)

            return JsonResponse({"message": "Webhook processed successfully."}, status=200)

        else:
            return JsonResponse({"message": "Invalid HTTP method."}, status=405)

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return JsonResponse({"message": "Error processing webhook."}, status=500)

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

def payment_success(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'store/payment_success.html', {'order': order})

def payment_failed(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'store/payment_failed.html', {'order': order})



