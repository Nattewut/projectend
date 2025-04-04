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
        # ตรวจสอบ amount ที่คำนวณแล้ว
        amount = int(order.get_cart_total * 100)
        logger.info(f"Amount in cents: {amount}")

        # URL สำหรับการสร้าง charge ผ่าน Opn API
        url = "https://api.omise.co/charges"
        auth_token = base64.b64encode(f"{settings.OPN_SECRET_KEY}:".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_token}",
            "Content-Type": "application/json"
        }

        # ตรวจสอบ URL ที่จะใช้เป็น return_uri
        # เช็คสถานะการชำระเงิน ว่าจะเป็น payment_success หรือ payment_failed
        if order.payment_status == "failed":
            return_uri = f"{get_base_url()}/payment_failed/{order.id}/"
        else:
            return_uri = f"{get_base_url()}/payment_success/{order.id}/"
        
        logger.info(f"Return URI: {return_uri}")

        payload = {
            "amount": amount,
            "currency": "thb",
            "source": {"type": "promptpay"},
            "description": f"Order {order.id}",
            "return_uri": return_uri,
            "metadata": { "orderId": order.id },
            "version": "2019-05-29"
        }

        logger.info(f"🔍 ส่งข้อมูลไปที่ Opn API: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        logger.info(f"🔍 ตอบกลับจาก Opn API: {data}")

        # ตรวจสอบว่าได้รับข้อมูล scannable_code หรือไม่
        if "source" in data and "scannable_code" in data["source"]:
            qr_url = data["source"]["scannable_code"]["image"]["download_uri"]
            return JsonResponse({
                "message": "ชำระเงินสำเร็จ",
                "qr_code_url": qr_url,
                "order_id": order.id,
                "amount": order.get_cart_total
            })

        # หากไม่มี scannable_code ใน response
        logger.warning(f"❌ QR Code not found in the response data: {data}")
        return JsonResponse({"error": "ไม่สามารถสร้าง QR Code ได้"}, status=422)

    except Exception as e:
        logger.error(f"❌ ERROR ใน create_qr_payment: {str(e)}")
        return JsonResponse({"error": f"Error: {str(e)}"}, status=500)

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
                payment_data = body.get('data')
                charge_id = payment_data.get('id')
                order_id = payment_data.get('metadata', {}).get('orderId')

                # Log for debugging
                logger.info(f"Received charge.create for charge_id: {charge_id}, order_id: {order_id}")

                try:
                    order = Order.objects.get(id=order_id)
                    if order.payment_status == 'pending' and order.charge_id == charge_id:
                        order.payment_status = 'created'  # Or whatever status you need
                        order.save()
                        logger.info(f"Updated order {order_id} with status: {order.payment_status}")

                except Order.DoesNotExist:
                    logger.error(f"Order with id {order_id} not found.")

            # Handle charge.complete event
            elif body.get('key') == 'charge.complete':
                payment_data = body.get('data')
                charge_id = payment_data.get('id')
                order_id = payment_data.get('metadata', {}).get('orderId')

                # Log for debugging
                logger.info(f"Received charge.complete for charge_id: {charge_id}, order_id: {order_id}")

                try:
                    order = Order.objects.get(id=order_id)
                    if order.payment_status == 'pending' and order.charge_id == charge_id:
                        order.payment_status = payment_data.get('status')
                        order.save()
                        logger.info(f"Updated order {order_id} with status: {order.payment_status}")

                except Order.DoesNotExist:
                    logger.error(f"Order with id {order_id} not found.")

            else:
                logger.warning(f"Unexpected event type: {body.get('key')}")
                return JsonResponse({"message": "Invalid event type."}, status=400)

            # Respond with success
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



