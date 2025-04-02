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

@csrf_exempt
def opn_webhook(request):
    logger.info("📨 Webhook received")

    try:
        raw = request.body.decode('utf-8')
        logger.info(f"📦 Raw data: {raw}")
        data = json.loads(raw)

        # ตรวจสอบว่า structure ถูกต้องไหม
        if not isinstance(data, dict) or "data" not in data or not isinstance(data["data"], dict):
            logger.error("❌ Webhook format invalid")
            return JsonResponse({"error": "Invalid format"}, status=400)

        event_type = data.get("key")
        charge = data["data"].get("object", {})
        charge_id = charge.get("id")
        charge_status = charge.get("status")

        logger.info(f"🔍 Event: {event_type} | Status: {charge_status} | Charge ID: {charge_id}")

        # ตรวจสอบกับ Omise API อีกครั้ง
        if charge_id:
            confirm_url = f"https://api.omise.co/charges/{charge_id}"
            auth = (settings.OPN_SECRET_KEY, '')
            confirm_resp = requests.get(confirm_url, auth=auth)

            if confirm_resp.status_code == 200:
                confirmed_data = confirm_resp.json()
                confirmed_status = confirmed_data.get("status")
                metadata = confirmed_data.get("metadata", {})
                order_id = metadata.get("orderId")

                logger.info(f"✅ Confirmed charge status: {confirmed_status} for order ID: {order_id}")

                if event_type == "charge.complete" and confirmed_status == "successful":
                    try:
                        order = Order.objects.get(id=order_id)
                        order.payment_status = "successful"
                        order.complete = True
                        order.save()
                        logger.info(f"🎉 Order {order.id} marked as complete")
                        return JsonResponse({"status": "ok"})
                    except Order.DoesNotExist:
                        logger.error(f"❌ Order not found: {order_id}")
                        return JsonResponse({"error": "Order not found"}, status=404)
                else:
                    logger.warning(f"⚠️ Event not handled or charge not successful")
                    return JsonResponse({"status": "ignored"})
            else:
                logger.error(f"❌ Failed to confirm charge with Omise: {confirm_resp.text}")
                return JsonResponse({"error": "Failed to confirm charge"}, status=502)

        logger.error("❌ Charge ID missing in webhook data")
        return JsonResponse({"error": "Missing charge ID"}, status=400)

    except Exception as e:
        logger.exception(f"💥 Webhook handler error: {str(e)}")
        return JsonResponse({"error": "Webhook processing failed"}, status=500)


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



