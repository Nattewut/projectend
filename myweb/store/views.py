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

@csrf_exempt  # ✅ แก้ปัญหา CSRF Forbidden (403)
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

        # คำนวณยอดรวมออเดอร์
        calculated_total = sum(
            item.product.price * item.quantity for item in order.orderitem_set.all()
        )

        print(f"🛒 Order Total: {calculated_total}")

        if calculated_total <= 0:
            return JsonResponse({'error': 'Invalid total amount'}, status=400)

        order.transaction_id = transaction_id
        order.complete = True
        order.save()

        # บันทึกที่อยู่การจัดส่ง
        if order.shipping:
            ShippingAddress.objects.create(
                customer=customer,
                order=order,
                address=data['shipping']['address'],
                city=data['shipping']['city'],
                state=data['shipping']['state'],
                zipcode=data['shipping']['zipcode'],
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
