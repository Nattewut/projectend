from django.contrib import admin
from .models import Product, Motor, Customer, Order, OrderItem, ShippingAddress

class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'motor', 'motor_rounds')  # การแสดงชื่อ ราคา มอเตอร์ และจำนวนรอบ
    search_fields = ('name',)  # ค้นหาสินค้าผ่านชื่อสินค้า
    fields = ('name', 'price', 'image', 'digital', 'motor', 'motor_rounds')  # ฟอร์มในหน้าแก้ไข

# ลงทะเบียนโมเดลที่มีการเพิ่มการแสดงผลใน Admin
admin.site.register(Customer)
admin.site.register(Product, ProductAdmin)  # ลงทะเบียน Product พร้อมกับ ProductAdmin
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(ShippingAddress)
admin.site.register(Motor)
