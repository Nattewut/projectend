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
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler('app.log')
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

        if request.user.is_authenticated:
            customer = request.user.customer
            order, _ = Order.objects.get_or_create(customer=customer, complete=False)
        else:
            customer, order = guestOrder(request, data)

        if "name" not in data.get("form", {}) or "email" not in data.get("form", {}):
            logger.warning("Missing required fields (name or email)")
            return JsonResponse({"error": "Missing required fields (name or email)"}, status=422)

        total = sum(item.product.price * item.quantity for item in order.orderitem_set.all())
        logger.info(f"🛒 Order Total: {total}")

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
        amount = int(order.get_cart_total * 100)
        url = "https://api.omise.co/charges"
        auth_token = base64.b64encode(f"{settings.OPN_SECRET_KEY}:".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "amount": amount,
            "currency": "thb",
            "source": {"type": "promptpay"},
            "description": f"Order {order.id}",
            "return_uri": f"{get_base_url()}/payment_success/{order.id}/",
            "metadata": { "orderId": order.id }  # 👈 สำคัญสุดสำหรับ Webhook
        }

        logger.info(f"🔍 ส่งข้อมูลไปที่ Opn API: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        logger.info(f"🔍 ตอบกลับจาก Opn API: {data}")

        if "source" in data and "scannable_code" in data["source"]:
            qr_url = data["source"]["scannable_code"]["image"]["download_uri"]
            return JsonResponse({
                "message": "ชำระเงินสำเร็จ",
                "qr_code_url": qr_url,
                "order_id": order.id,
                "amount": order.get_cart_total
            })

        logger.warning("❌ ไม่สามารถสร้าง QR Code ได้")
        return JsonResponse({"error": "ไม่สามารถสร้าง QR Code ได้"}, status=422)

    except Exception as e:
        logger.error(f"❌ ERROR ใน create_qr_payment: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

import json
from django.http import JsonResponse

def opn_webhook(request):
    try:
        # ตรวจสอบว่า Webhook ใช้ method POST และ Content-Type เป็น application/json
        if request.method == 'POST' and request.content_type == 'application/json':
            # อ่านข้อมูล raw ที่ได้รับจาก body ของ request
            raw_data = request.body.decode('utf-8')
            print(f"Raw data received: {raw_data}")  # Log raw data ที่ได้รับ

            try:
                # แปลง JSON string เป็น dictionary
                data = json.loads(raw_data)
                print(f"Parsed data: {data}")  # Log ข้อมูลที่แปลงแล้วเป็น dict
            except json.JSONDecodeError as e:
                print(f"JSON Decode Error: {e}")  # ถ้าไม่สามารถแปลง JSON ได้
                return JsonResponse({'error': 'Invalid JSON format'}, status=400)

            # ตรวจสอบว่า 'data' มี 'object' และ 'id' หรือไม่
            if 'data' in data and 'object' in data['data']:
                charge = data['data']['object']
                # ตรวจสอบว่า 'charge' เป็น dict และมี 'id'
                if isinstance(charge, dict):
                    charge_id = charge.get("id")
                    print(f"Charge ID: {charge_id}")  # Log charge ID

                    # ทำงานต่อไป เช่น บันทึกข้อมูลลงในฐานข้อมูล
                    return JsonResponse({'message': 'Webhook processed successfully'}, status=200)
                else:
                    print("Error: 'charge' is not a dictionary")
                    return JsonResponse({'error': "'charge' is not a valid dictionary"}, status=400)
            else:
                print("Error: 'data' or 'object' key missing in the payload")
                return JsonResponse({'error': "'data' or 'object' key missing in the payload"}, status=400)

        else:
            print("Error: Invalid request method or content type")
            return JsonResponse({'error': 'Invalid request method or content type'}, status=400)

    except Exception as e:
        print(f"Error processing webhook: {e}")  # Log error ที่เกิดขึ้น
        return JsonResponse({'error': 'Internal Server Error'}, status=500)


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



