from django.urls import path

from . import views

urlpatterns = [
    # Leave as empty string for base URL
    path('', views.store, name="store"),
    path('cart/', views.cart, name="cart"),
    path('checkout/', views.checkout, name="checkout"),
    path('update_item/', views.updateItem, name="update_item"),

    # เพิ่ม URL สำหรับ process_order
    path('process_order/', views.processOrder, name="process_order"),  # สำหรับการประมวลผลคำสั่งซื้อหลังชำระเงิน

    # เพิ่ม URL สำหรับ success และ cancel
    path('success/', views.success, name='success'),  # เมื่อการชำระเงินสำเร็จ
    path('cancel/', views.cancel, name='cancel'),  # เมื่อการชำระเงินถูกยกเลิก
]
