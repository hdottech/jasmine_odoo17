from odoo import fields, models, api
from odoo.models import ValidationError
import random
import qrcode
import base64
import barcode
from PIL import Image
from barcode.writer import ImageWriter
from io import BytesIO
import logging

_logger = logging.getLogger(__name__)

def generate_qr_code(content):
    """
    生成 QR Code 並返回 base64 編碼的圖片
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=12,
        border=4
    )
    qr.add_data(content)
    qr.make(fit=True)
    
    img = qr.make_image()
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode('utf-8')
def generate_barcode(content):
    """生成條碼並返回 base64 編碼的圖片"""
    try:
        content = content.replace('-', '')  # 移除發票號碼中的 -
        code39 = barcode.get('code39', content, writer=ImageWriter())
        buffer = BytesIO()
        code39.write(buffer, options={'module_width': 0.2, 'module_height': 10})
        return base64.b64encode(buffer.getvalue()).decode('utf-8')  # 確保返回 utf-8
    except Exception as e:
        _logger.error(f"生成條碼發生錯誤: {str(e)}")
        return False

def generate_einvoice_qrcodes(record):
    """生成台灣電子發票左右兩個 QR Code 的內容"""
    try:
        # 處理日期格式（民國年）
        invoice_date = record.einvoice_date
        roc_year = invoice_date.year - 1911
        date_str = f"{roc_year:03d}{invoice_date.month:02d}{invoice_date.day:02d}"
        
        # 處理金額（8位數，補0）
        amount_untaxed = f"{int(record.amount_untaxed):08d}"
        amount_total = f"{int(record.amount_total):08d}"
        
        # 處理發票號碼（移除連字號）
        einvoice_number = record.einvoice_number.replace('-', '')
        
        # 左側 QR Code 內容: 發票號碼(10)|日期(7)|隨機碼(4)|銷售額(8)|總計(8)|買方統編(8)|賣方統編(8)
        left_qr_content = (
            f"{einvoice_number}"
            f"{date_str}"
            f"{record.einvoice_random_number or '0000'}"
            f"{amount_untaxed}"
            f"{amount_total}"
            f"{record.einvoice_buyer_id or '00000000'}"
            f"{record.einvoice_seller_id or '00000000'}"
        )
        
        # 右側 QR Code 內容: 品項數:品名1:數量1:單價1:品名2:數量2:單價2...
        items = []
        for line in record.invoice_line_ids:
            items.extend([
                str(line.product_id.name),
                f"{int(line.quantity)}",
                "{:.0f}".format(line.price_unit)
            ])
        
        right_qr_content = ":".join([
            str(len(record.invoice_line_ids)),  # 品項數量
            ":".join(items),                    # 商品明細
            record.einvoice_seller_id or "00000000",  # 賣方統編
            "1"                                 # 版本號
        ])
        
        return left_qr_content, right_qr_content
        
    except Exception as e:
        _logger.error(f"生成 QR Code 內容時發生錯誤: {str(e)}")
        raise e


class AccountMove(models.Model):
    _inherit = 'account.move'

    employee_user_id = fields.Many2one(
        'hr.employee',
        string="銷售員 (員工)",
        related='partner_id.employee_user_id',
        store=True,
        readonly=False
    )
    employee_buyer_id = fields.Many2one(
        'hr.employee',
        string="買方 (員工)",
        related='partner_id.employee_buyer_id',
        store=True,
        readonly=False
    )
    payment_cash = fields.Float(string='現金', default=0.0)
    payment_credit = fields.Float(string='信用卡', default=0.0)
    is_cash_payment = fields.Boolean(string='現金付款')
    is_credit_payment = fields.Boolean(string='信用卡付款')
    vendor_invoice_number = fields.Char(string='應付憑單發票號碼')

    einvoice_number = fields.Char(string='發票號碼', readonly=True)
    einvoice_date = fields.Datetime(string='發票時間', readonly=True, default=False)
    einvoice_random_number = fields.Char(string='隨機碼', readonly=True, size=4)
    einvoice_certification_number = fields.Char(string='加密驗證碼', size=24)
    einvoice_seller_id = fields.Char(string='賣方統編', related='company_id.vat', readonly=True)
    einvoice_buyer_id = fields.Char(string='買方統編', related='partner_id.vat', readonly=True)
    einvoice_period = fields.Char(
        string='發票週期',
        compute='_compute_einvoice_period',
        store=True
    )
    invoice_title_id = fields.Many2one(
        'invoice.track',
        string='發票抬頭',
        domain="[('is_active', '=', True), ('is_used', '=', False)]",
        help="選擇要使用的發票抬頭及對應的字軌"
    )
    partner_vat_number = fields.Char(
        string='統一編號',
        related='partner_id.vat_number',
        readonly=True,
        store=True
    )
    qr_image = fields.Text(
        string="QR Code",
        compute='_compute_qr_codes',
        store=True
    )
    left_qr_image = fields.Text(
        string="左側 QR Code",
        compute='_compute_qr_codes',
        store=True
    )
    right_qr_image = fields.Text(
        string="右側 QR Code",
        compute='_compute_qr_codes',
        store=True
    )
    barcode_image = fields.Text(string="條碼圖片", compute='_compute_barcode', store=True)

    # _sql_constraints = [
    #     ('barcode_uniq', 'unique(einvoice_barcode)', '發票條碼必須是唯一的！')
    # ]

    def action_print_receipt(self):
        return self.env.ref('jasmine.action_report_pos_style_receipt').report_action(self)
    
    # 處理現金與刷卡的金額
    @api.onchange('is_cash_payment', 'is_credit_payment', 'amount_total')
    def _onchange_payment_method(self):
        if self.is_cash_payment and not self.is_credit_payment:
            self.payment_cash = self.amount_total
            self.payment_credit = 0
        elif self.is_credit_payment and not self.is_cash_payment:
            self.payment_credit = self.amount_total
            self.payment_cash = 0
        elif self.is_cash_payment and self.is_credit_payment:
            # 如果兩個都勾，金額平分
            half_amount = self.amount_total / 2
            self.payment_cash = half_amount
            self.payment_credit = half_amount
        else:
            self.payment_cash = 0
            self.payment_credit = 0

    
    @api.depends('einvoice_number')
    def _compute_barcode(self):
        """生成條碼圖片"""
        for record in self:
            if record.einvoice_number:
                try:
                    # 生成條碼
                    code39 = barcode.Code39(
                        record.einvoice_number.replace('-', ''),
                        writer=ImageWriter(),
                        add_checksum=False
                    )
                    
                    # 生成到 BytesIO
                    buffer = BytesIO()
                    code39.write(buffer)
                    
                    # 打開圖片並裁剪掉底部文字
                    buffer.seek(0)
                    with Image.open(buffer) as img:
                        # 只保留上半部分（條碼部分）
                        width, height = img.size
                        cropped = img.crop((0, 0, width, height * 0.6))  # 裁剪掉底部40%
                        
                        # 保存裁剪後的圖片
                        output = BytesIO()
                        cropped.save(output, format='PNG')
                        record.barcode_image = base64.b64encode(output.getvalue()).decode()
                        
                except Exception as e:
                    _logger.error(f"生成條碼時發生錯誤: {str(e)}")
                    record.barcode_image = False
            else:
                record.barcode_image = False

    @api.depends('invoice_date')
    def _compute_einvoice_period(self):
        """計算發票期別（每兩個月為一期）"""
        for record in self:
            if not record.invoice_date:
                record.einvoice_period = False
                continue

            date = record.invoice_date
            roc_year = date.year - 1911
            month = date.month
            start_month = ((month - 1) // 2) * 2 + 1
            end_month = start_month + 1
            record.einvoice_period = f"{roc_year}年{str(start_month).zfill(2)}-{str(end_month).zfill(2)}月"

    @api.depends('einvoice_number', 'einvoice_date', 'amount_total', 'amount_untaxed',
                 'einvoice_buyer_id', 'einvoice_seller_id', 'einvoice_random_number')
    def _compute_qr_codes(self):
        """計算並生成左右兩個 QR Code"""
        for record in self:
            if not (record.einvoice_number and record.einvoice_date):
                record.left_qr_image = False
                record.right_qr_image = False
                continue

            try:
                # 生成左右 QR Code 的內容
                left_content, right_content = generate_einvoice_qrcodes(record)
                
                # 生成 QR Code 圖片
                record.left_qr_image = generate_qr_code(left_content)
                record.right_qr_image = generate_qr_code(right_content)
                
                _logger.info(f"成功生成雙 QR Code，發票號碼: {record.einvoice_number}")
                
            except Exception as e:
                _logger.error(f"生成 QR Code 時發生錯誤: {str(e)}")
                record.left_qr_image = False
                record.right_qr_image = False

    def action_generate_einvoice_number(self):
        """手動生成電子發票號碼 - 使用選擇的發票抬頭關聯的字軌"""
        self.ensure_one()
        if not (self.is_cash_payment or self.is_credit_payment):
            raise ValidationError('請先選擇付款方式')
        if self.einvoice_number:
            raise ValidationError('此發票已有發票號碼')

        # 檢查是否已選擇發票抬頭
        if not self.invoice_title_id:
            raise ValidationError('請先選擇發票抬頭')

        # 直接使用已選擇的發票字軌記錄
        invoice_track = self.invoice_title_id
        
        # 檢查所選字軌是否可用
        if not invoice_track.is_active:
            raise ValidationError('所選發票字軌未啟用')
        
        if invoice_track.is_used:
            raise ValidationError('所選發票字軌已用完')

        # 取得新發票號碼
        next_number = invoice_track.get_next_number()

        # 更新發票資訊
        self.write({
            'einvoice_number': next_number,
            'einvoice_date': fields.Datetime.now(),
            'einvoice_random_number': ''.join(random.choices('0123456789', k=4))
        })

        _logger.info(f"已生成發票號碼: {next_number} (發票抬頭: {invoice_track.invoice_title_id.name})")

    def write(self, vals):

        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)



