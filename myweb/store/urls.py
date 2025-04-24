from django.urls import path
from . import views

urlpatterns = [
    path('', views.store, name="store"),
    path('cart/', views.cart, name="cart"),
    path('checkout/', views.checkout, name="checkout"),
    path('update_item/', views.updateItem, name="update_item"),

    # ✅ เปลี่ยนมาใช้ Opn Payments แทน Stripe
    path('process_order/', views.processOrder, name="process_order"),

    # ✅ เพิ่ม URL สำหรับสร้าง QR Code Payment
    path('create_qr_payment/<int:order_id>/', views.create_qr_payment, name="create_qr_payment"),

    # ✅ เพิ่ม Webhook สำหรับ Opn Payments
    path('webhook/', views.opn_webhook, name='webhook'),
    path('webhook/opn/', views.opn_webhook, name='opn_webhook'),
    path('check_payment_status/', views.check_payment_status, name='check_payment_status'),
    path('payment_failed/<int:order_id>/', views.payment_failed, name='payment_failed'),
    path('payment_success/<int:order_id>/', views.payment_success, name='payment_success'),
]
