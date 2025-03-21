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
            return JsonResponse({"error": "Missing required fields (name or email)"}, status=400)

        calculated_total = sum(item.product.price * item.quantity for item in order.orderitem_set.all())
        print(f"🛒 Order Total: {calculated_total}")

        # ✅ อนุญาตให้ QR Code ถูกสร้างได้ทุกยอดเงินที่มากกว่า 0 บาท
        if calculated_total <= 0:
            return JsonResponse({'error': 'Invalid total amount'}, status=400)

        order.transaction_id = transaction_id
        order.complete = False
        order.save()

        return create_qr_payment(order)
    except Exception as e:
        print(f"❌ ERROR in processOrder: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

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

        # ถ้าอยู่ใน Test Mode, จำลองการชำระเงินสำเร็จ
        if MODE == 'TEST':
            if "source" not in data:
                data = {
                    "source": {
                        "scannable_code": {
                            "image": {
                                "download_uri": "https://some/fake/qr-code-image.png"
                            }
                        }
                    }
                }
                print("🔍 จำลองสถานะการชำระเงินสำเร็จ")

        # ส่งคำตอบพร้อมข้อความ "ชำระเงินสำเร็จ" ใน Test Mode
        if "source" in data and "scannable_code" in data["source"]:
            qr_code_url = data["source"]["scannable_code"]["image"]["download_uri"]
            
            # เพิ่มข้อความ "ชำระเงินสำเร็จ" ใน Test Mode
            if MODE == 'TEST':
                return JsonResponse({
                    "message": "ชำระเงินสำเร็จ",  # ข้อความที่จะแสดงเมื่อสถานะเป็น Test Mode
                    "qr_code_url": qr_code_url,
                    "order_id": order.id,
                    "amount": order.get_cart_total
                })
            return JsonResponse({"qr_code_url": qr_code_url, "order_id": order.id, "amount": order.get_cart_total})

        else:
            return JsonResponse({"error": "ไม่สามารถสร้าง QR Code ได้"}, status=400)

    except Exception as e:
        print(f"❌ ERROR ใน create_qr_payment: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

import time
from django.shortcuts import redirect
from django.http import JsonResponse

@csrf_exempt
def opn_webhook(request):
    """จำลองการรับข้อมูลจาก Webhook ของ Opn Payments"""
    try:
        data = json.loads(request.body)
        print(f"Received Webhook Data: {data}")

        event = data.get("event")
        charge_id = data.get("data", {}).get("id")  # ใช้ charge_id
        status = data.get("data", {}).get("status")

        if MODE == 'TEST':
            if event == "charge.create":
                print("🔍 ระบบอยู่ใน Test Mode และสถานะเป็น 'pending' - จำลองการชำระเงิน")

                # รอ 2 วินาทีจำลองสถานะการชำระเงินสำเร็จ
                time.sleep(2)

                # จำลองสถานะเป็น "paid"
                status = "paid"

                # เมื่อสถานะเป็น "paid" ให้ redirect ไปที่หน้าชำระเงินสำเร็จ
                return redirect('payment_success')  # ไปที่หน้า success

        # ตรวจสอบสถานะการชำระเงินจริงใน Live Mode
        if event == "charge.complete" and status == "successful":
            print("🔍 การชำระเงินสำเร็จแล้ว")
            order = Order.objects.get(charge_id=charge_id)  # ใช้ charge_id ในการค้นหาคำสั่งซื้อ
            order.complete = True  # เปลี่ยนสถานะคำสั่งซื้อเป็นสำเร็จ
            order.save()

            return JsonResponse({"message": "Payment verified, order updated."})

        return JsonResponse({"error": "Payment not successful or invalid event"}, status=400)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def payment_success(request):
    """หน้าชำระเงินสำเร็จ"""
    return render(request, 'success.html')  # แสดงหน้า success.html
    
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

def success(request):
    return render(request, 'success.html')  

def cancel(request):
    return render(request, 'cancel.html')

def payment_success(request):
    return render(request, 'payment_success.html')