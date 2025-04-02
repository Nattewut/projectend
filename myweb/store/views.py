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
import logging
from django.shortcuts import render, get_object_or_404


# ตั้งค่า logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# หากต้องการให้ log ข้อมูลออกไปที่ไฟล์
file_handler = logging.FileHandler('app.log')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

# หรือหากต้องการให้ log ข้อมูลไปที่ console ด้วย
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

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
            "return_uri": f"{get_base_url()}/payment_success/{order.id}/"
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

@csrf_exempt
def opn_webhook(request):
    logger.info("📨 Received Webhook")

    try:
        # Step 1: รับข้อมูลจาก Webhook
        logger.info(f"Received Webhook Raw Data: {request.body}")

        # Step 2: ถ้า request.body เป็น bytes, ให้แปลงเป็น string ก่อน
        if isinstance(request.body, bytes):
            request_body_str = request.body.decode('utf-8')  # แปลงจาก bytes เป็น string
        else:
            request_body_str = request.body

        # Step 3: พยายามแปลง JSON string จาก request_body_str เป็น dictionary (dict)
        try:
            data = json.loads(request_body_str)
        except json.JSONDecodeError:
            logger.error("❌ Failed to decode JSON")
            return JsonResponse({"error": "Invalid JSON format"}, status=400)
        
        # Step 4: ตรวจสอบว่า data ที่ได้รับเป็น dict หรือไม่
        if not isinstance(data, dict):
            logger.error("❌ Data is not a dictionary after parsing JSON.")
            return JsonResponse({"error": "Invalid data format, expected a dictionary."}, status=400)

        # Step 5: ตรวจสอบว่า 'data' มีใน dictionary และเป็น dict
        if isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict):
            event_type = data.get("key")
            charge = data['data'].get('object', {})
            charge_status = charge.get('status', '')
            metadata = charge.get('metadata', {})
            order_id = metadata.get("orderId") if isinstance(metadata, dict) else None
        else:
            logger.error("❌ Invalid data format in webhook, 'data' is not a dictionary.")
            return JsonResponse({"error": "'data' field is missing or not a dictionary"}, status=400)

        # Step 6: ตรวจสอบว่า order_id มีค่า
        if not order_id:
            logger.error("❌ Order ID is missing.")
            return JsonResponse({"error": "Order ID is missing"}, status=400)

        # Step 7: ตรวจสอบว่า event_type เป็น charge.complete
        if event_type == "charge.complete":
            from .models import Order
            try:
                # ค้นหาคำสั่งซื้อที่ตรงกับ order_id
                order = Order.objects.get(id=order_id)
                if charge_status == "successful":
                    # อัปเดตสถานะการชำระเงินเป็น successful
                    order.payment_status = "successful"
                    order.complete = True
                    order.save()
                    logger.info(f"✅ Order {order.id} marked as successful")
                    return JsonResponse({"status": "ok"})
                else:
                    logger.error(f"❌ Unexpected charge status: {charge_status}")
                    return JsonResponse({"error": "Unexpected charge status"}, status=400)

            except Order.DoesNotExist:
                logger.error(f"❌ Order {order_id} not found.")
                return JsonResponse({"error": "Order not found"}, status=404)
        else:
            logger.info(f"📦 Received event: {event_type} with status: {charge_status}")
            return JsonResponse({"status": "ok"})

    except Exception as e:
        logger.error(f"❌ Webhook error: {str(e)}")
        return JsonResponse({"error": "Webhook processing failed"}, status=500)

# ฟังก์ชันสำหรับอัปเดตไอเท็มในตะกร้า
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
    order = get_object_or_404(Order, id=order_id)
    context = {
        'order': order
    }
    return render(request, 'store/payment_success.html', context)

def payment_failed(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    context = {
        'order': order
    }
    return render(request, 'store/payment_failed.html', context)


