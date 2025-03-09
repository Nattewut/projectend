from django.shortcuts import render
from django.http import JsonResponse
import json
import datetime
from .models import * 
from .utils import cookieCart, cartData, guestOrder
import stripe
from django.conf import settings
import socket
from django.views.decorators.csrf import csrf_exempt

stripe.api_key = settings.STRIPE_SECRET_KEY
print(f"✅ Stripe API Key จาก stripe: {stripe.api_key}")

def get_base_url():
    """ ใช้ฟังก์ชันนี้เพื่อกำหนด base URL ให้ถูกต้อง """
    hostname = socket.gethostname()
    if "localhost" in hostname or "127.0.0.1" in hostname:
        return "http://127.0.0.1:8000"
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
        'STRIPE_PUBLIC_KEY': settings.STRIPE_PUBLIC_KEY
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

        # ✅ ตรวจสอบว่าสั่งซื้อสินค้าหรือไม่
        if not order.orderitem_set.exists():
            return JsonResponse({'error': 'No items in order'}, status=400)

        # ✅ ตรวจสอบ STRIPE_SECRET_KEY ก่อนใช้งาน
        if not stripe.api_key or stripe.api_key.startswith("default"):
            print("❌ ERROR: Stripe API Key ไม่ถูกต้อง")
            return JsonResponse({'error': 'Stripe API Key ไม่ถูกต้อง'}, status=500)

        # ✅ ตรวจสอบข้อมูลที่จำเป็นต้องมี
        if "name" not in data.get("form", {}) or "email" not in data.get("form", {}):
            return JsonResponse({"error": "Missing required fields (name or email)"}, status=400)

        # ✅ คำนวณยอดรวม
        calculated_total = sum(
            item.product.price * item.quantity for item in order.orderitem_set.all()
        )

        print(f"🛒 Order Total: {calculated_total}")

        if calculated_total <= 0:
            return JsonResponse({'error': 'Invalid total amount'}, status=400)

        order.transaction_id = transaction_id
        order.complete = True
        order.save()

        # ✅ ตรวจสอบ `shipping` ก่อนใช้งาน
        shipping_data = data.get('shipping', {})
        if not shipping_data.get('address'):
            return JsonResponse({'error': 'Missing shipping address'}, status=400)

        ShippingAddress.objects.create(
            customer=customer,
            order=order,
            address=shipping_data.get('address', ''),
            city=shipping_data.get('city', ''),
            state=shipping_data.get('state', ''),
            zipcode=shipping_data.get('zipcode', ''),
        )

        base_url = get_base_url()

        # ✅ สร้าง Stripe Checkout Session
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': item.product.name},
                        'unit_amount': int(item.product.price * 100),
                    },
                    'quantity': item.quantity,
                }
                for item in order.orderitem_set.all()
            ],
            mode='payment',
            success_url=f"{base_url}/success/",
            cancel_url=f"{base_url}/cancel/",
        )

        print(f"✅ Stripe Session Created: {session.id}")
        return JsonResponse({'id': session.id})

    except KeyError as e:
        print(f"❌ ERROR: Missing Key - {str(e)}")
        return JsonResponse({'error': f'Missing key: {str(e)}'}, status=400)
    except Exception as e:
        print(f"❌ ERROR in processOrder: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
    
def updateItem(request):
    data = json.loads(request.body)
    productId = data.get('productId')
    action = data.get('action')
    
    print(f"✅ Action: {action}, Product: {productId}")  # Debugging log

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
