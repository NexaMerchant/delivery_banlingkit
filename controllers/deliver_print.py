from odoo import http
from odoo.http import request
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import landscape
import io
import os
from datetime import datetime

class DeliverPrintController(http.Controller):
    @http.route('/delivery/print_label', type='http', auth='user')
    def print_label(self, tracking_no=None, **kw):
        if not tracking_no:
            return request.not_found()
        
        font_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'fonts', 'Microsoft_YaHei.ttf')
        )
        if 'Microsoft_YaHei' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('Microsoft_YaHei', font_path))

        # 获取当前打印时间
        print_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 查找 sale.order
        picking = request.env['stock.picking'].sudo().search([('carrier_tracking_ref', '=', tracking_no)], limit=1)
        if not picking or not picking.sale_id:
            return request.not_found()
        order = picking.sale_id

        # 获取信息
        partner = order.partner_shipping_id or order.partner_id
        address = partner.contact_address or ''
        region = partner.state_id.name if partner.state_id else ''
        city = partner.city or ''
        phone = partner.phone or ''
        name = partner.name or ''
        country = partner.country_id.name if partner.country_id else ''

        buffer = io.BytesIO()
        width, height = 150 * mm, 80 * mm  # 横向：宽150mm，高80mm
        pagesize = (width, height)
        c = canvas.Canvas(buffer, pagesize=pagesize)

        # 顶部距离页面上边缘 8mm
        top = height - 8 * mm

        c.setFont("Microsoft_YaHei", 12)
        c.drawString(3 * mm, top, f"面单号: {tracking_no}")

        c.setFont("Microsoft_YaHei", 10)
        line_gap = 7 * mm  # 行间距缩小
        c.drawString(3 * mm, top - line_gap, f"收件人/国家: {name} {country}")
        # 省份和城市合并一行
        c.drawString(3 * mm, top - 2 * line_gap, f"省份/城市: {region} {city}")
        c.drawString(3 * mm, top - 3 * line_gap, f"地址: {address}")
        c.drawString(3 * mm, top - 4 * line_gap, f"打印时间: {print_time}")

        # 商品内容
        y = top - 5 * line_gap
        c.setFont("Microsoft_YaHei", 10)
        c.drawString(3 * mm, y, "商品列表:")
        y -= 5 * mm
        for line in order.order_line:
            product_str = f"{line.product_id.display_name} x {line.product_uom_qty}"
            c.drawString(8 * mm, y, product_str)
            y -= 4 * mm
            if y < 20 * mm:  # 防止内容超出条码区域
                c.drawString(8 * mm, y, "...")
                break

        # 生成一维码，适当减小 barWidth
        barcode = code128.Code128(tracking_no, barHeight=15 * mm, barWidth=1.2)
        barcode_width = barcode.width
        x = (width - barcode_width) / 2  # 居中
        barcode.drawOn(c, x, 5 * mm)

        c.showPage()
        c.save()
        pdf = buffer.getvalue()
        buffer.close()

        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', f'inline; filename="label_{tracking_no}.pdf"')
        ]
        return request.make_response(pdf, headers=headers)