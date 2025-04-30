from django.contrib import admin
from .models import Product, Motor, Customer, Order, OrderItem, ShippingAddress

class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'stock', 'motor', 'motor_rounds')
    search_fields = ('name',)
    fields = ('name', 'price', 'image', 'digital', 'motor', 'motor_rounds', 'stock')

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('product', 'quantity', 'price', 'total_price')  # แสดงแค่ฟิลด์ชื่อสินค้า, จำนวน, ราคา, และยอดรวม
    readonly_fields = ('product', 'quantity', 'price', 'total_price')  # ทำให้ไม่สามารถแก้ไขฟิลด์เหล่านี้ได้

    def price(self, obj):
        return obj.product.price  # แสดงราคาของสินค้า
    price.short_description = 'Price'

    def total_price(self, obj):
        return obj.product.price * obj.quantity  # คำนวณยอดรวมราคาสินค้าจากราคา * จำนวน
    total_price.short_description = 'Total Price'

class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'customer',  # ชื่อผู้ซื้อ
        'date_ordered',  # เวลา
        'payment_status',  # สถานะการชำระเงิน
        'get_cart_items',  # จำนวนสินค้าในคำสั่งซื้อ
        'total_order_price',  # ยอดรวมราคาสินค้าทั้งหมด
        'sold_items_per_day',  # ขายสินค้าในแต่ละวัน
    )

    search_fields = ('id', 'customer__name', 'customer__email')  # ค้นหาคำสั่งซื้อจาก ID, ชื่อ, หรืออีเมลของลูกค้า
    list_filter = ('payment_status',)  # กรองตามสถานะการชำระเงิน
    ordering = ('-date_ordered',)  # เรียงตามวันที่สั่งซื้อจากใหม่ไปเก่า

    inlines = [OrderItemInline]  # เพิ่ม inline สำหรับ OrderItem

    def total_order_price(self, obj):
        return sum(item.product.price * item.quantity for item in obj.orderitem_set.all())  # คำนวณยอดรวมจากสินค้าทั้งหมดในคำสั่งซื้อ
    total_order_price.short_description = 'Total Order Price'

    def get_cart_items(self, obj):
        return sum(item.quantity for item in obj.orderitem_set.all())  # คำนวณจำนวนสินค้าทั้งหมดในคำสั่งซื้อ
    get_cart_items.short_description = 'Total Items'

    # ฟังก์ชันแสดงสินค้าที่ขายในแต่ละวัน
    def sold_items_per_day(self, obj):
        items = {}
        for item in obj.orderitem_set.all():
            product_name = item.product.name
            if product_name not in items:
                items[product_name] = 0
            items[product_name] += item.quantity
        return ", ".join([f"{key}: {value}" for key, value in items.items()])  # แสดงชื่อสินค้าและจำนวนสินค้าที่ขาย
    sold_items_per_day.short_description = 'Sold Items Per Day'

# ลงทะเบียนโมเดลที่มีการแสดงผลใน Admin
admin.site.register(Customer)
admin.site.register(Product, ProductAdmin)
admin.site.register(Order, OrderAdmin)  # ลงทะเบียน Order พร้อมกับ OrderAdmin
admin.site.register(OrderItem)
admin.site.register(ShippingAddress)
admin.site.register(Motor)









