from odoo import http
from odoo.http import request
from reportlab.lib.pagesizes import A6
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
import io
import os

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

        # 生成PDF
        buffer = io.BytesIO()
        width, height = 100 * mm, 150 * mm
        c = canvas.Canvas(buffer, pagesize=(width, height))
        
        # 顶部距离页面上边缘 10mm
        top = height - 10 * mm

        c.setFont("Microsoft_YaHei", 12)
        c.drawString(5 * mm, top, f"面单号: {tracking_no}")

        c.setFont("Microsoft_YaHei", 10)
        c.drawString(5 * mm, top - 12 * mm, f"收件人: {name}")
        c.drawString(5 * mm, top - 22 * mm, f"电话: {phone}")
        c.drawString(5 * mm, top - 32 * mm, f"国家: {country}")
        c.drawString(5 * mm, top - 42 * mm, f"省份: {region}")
        c.drawString(5 * mm, top - 52 * mm, f"城市: {city}")
        c.drawString(5 * mm, top - 62 * mm, f"地址: {address}")

         # 商品内容
        y = top - 72 * mm
        c.setFont("Microsoft_YaHei", 10)
        c.drawString(5 * mm, y, "商品列表:")
        y -= 8 * mm
        for line in order.order_line:
            product_str = f"{line.product_id.display_name} x {line.product_uom_qty}"
            c.drawString(8 * mm, y, product_str)
            y -= 7 * mm
            if y < 30 * mm:  # 防止内容超出条码区域
                c.drawString(8 * mm, y, "...")
                break


        # 生成一维码，减小 barWidth
        barcode = code128.Code128(tracking_no, barHeight=20 * mm, barWidth=0.8)
        barcode_width = barcode.width
        x = (width - barcode_width) / 2  # 居中
        barcode.drawOn(c, x, 20 * mm)

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