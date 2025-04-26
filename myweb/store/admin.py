# ใน admin.py
from django.contrib import admin
from .models import Product, Motor, Customer, Order, OrderItem, ShippingAddress

class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'stock', 'motor', 'motor_rounds')  # เพิ่มฟิลด์ stock
    search_fields = ('name',)  # ค้นหาสินค้าผ่านชื่อสินค้า
    fields = ('name', 'price', 'image', 'digital', 'motor', 'motor_rounds', 'stock')  # เพิ่มฟิลด์ stock ในฟอร์มแก้ไข

# ลงทะเบียนโมเดลที่มีการเพิ่มการแสดงผลใน Admin
admin.site.register(Customer)
admin.site.register(Product, ProductAdmin)  # ลงทะเบียน Product พร้อมกับ ProductAdmin
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(ShippingAddress)
admin.site.register(Motor)
