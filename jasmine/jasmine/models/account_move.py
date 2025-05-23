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
from datetime import datetime

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
    """生成台灣電子發票左右兩個 QR Code 的內容（防呆強化版）"""
    try:
        if not record.einvoice_number:
            raise ValueError("缺少發票號碼（einvoice_number）")
        if not record.einvoice_date:
            raise ValueError("缺少發票日期（einvoice_date）")

        # 處理發票號碼（移除連字號）
        einvoice_number = (record.einvoice_number or '').replace('-', '')

        # 日期格式（民國年）
        invoice_date = record.einvoice_date
        roc_year = invoice_date.year - 1911
        date_str = f"{roc_year:03d}{invoice_date.month:02d}{invoice_date.day:02d}"

        # 金額處理，防呆為整數後補0
        amount_untaxed = f"{int(record.amount_untaxed or 0):08d}"
        amount_total = f"{int(record.amount_total or 0):08d}"

        # 組左側 QR Code 內容
        left_qr_content = (
            f"{einvoice_number}"
            f"{date_str}"
            f"{record.einvoice_random_number or '0000'}"
            f"{amount_untaxed}"
            f"{amount_total}"
            f"{record.einvoice_buyer_id or '00000000'}"
            f"{record.einvoice_seller_id or '00000000'}"
        )

        # 組右側 QR Code 內容
        items = []
        for line in record.invoice_line_ids.filtered(lambda l: not l.display_type):
            product_name = str(line.product_id.name or line.name or '品項')
            quantity = int(line.quantity or 0)
            unit_price = "{:.0f}".format(line.price_unit or 0)
            items.extend([product_name, str(quantity), unit_price])

        right_qr_content = ":".join([
            str(len(record.invoice_line_ids.filtered(lambda l: not l.display_type))),
            ":".join(items),
            record.einvoice_seller_id or "00000000",
            "1"
        ])

        return left_qr_content, right_qr_content

    except Exception as e:
        _logger.error(f"生成 QR Code 內容失敗：{str(e)}")
        raise


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
    einvoice_seller_id = fields.Char(string='賣方統編', readonly=True, store=True)
    einvoice_buyer_id = fields.Char(string='買方統編', related='partner_id.vat_number', readonly=True)
    einvoice_period = fields.Char(
        string='發票週期',
        compute='_compute_einvoice_period',
        store=True
    )
    invoice_title_id = fields.Many2one(
        'invoice.title',
        string='發票抬頭',
        domain="[('active', '=', True)]"
    )
    invoice_track_id = fields.Many2one(
        'invoice.track',
        string='發票字軌',
        compute='_compute_invoice_track',
        store=True
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

    # 新增欄位 - 關聯到電子發票資訊
    invoice_information_id = fields.Many2one('invoice.information', 
                                           string='電子發票資訊', readonly=True, 
                                           copy=False)

    def action_print_receipt(self):
        return self.env.ref('jasmine.action_report_pos_style_receipt').report_action(self)
    def debug_invoice_track(self):
        """除錯用方法：檢查發票字軌的狀態"""
        self.ensure_one()
        
        if not self.invoice_title_id:
            _logger.info("沒有選擇發票抬頭")
            return
        
        # 檢查所有相關的發票字軌
        all_tracks = self.env['invoice.track'].search([
            ('invoice_title_id', '=', self.invoice_title_id.id)
        ])
        
        _logger.info(f"發票抬頭 {self.invoice_title_id.name} 下的所有字軌:")
        for track in all_tracks:
            _logger.info(f"  字軌: {track.section_code}")
            _logger.info(f"  狀態: {track.status}")
            _logger.info(f"  當前期間有效: {track.is_valid_for_current_period}")
            _logger.info(f"  發票抬頭ID: {track.invoice_title_id.id}")
            _logger.info("  ---")
        
        # 檢查符合條件的字軌
        valid_tracks = self.env['invoice.track'].search([
            ('invoice_title_id', '=', self.invoice_title_id.id),
            ('status', '=', 'in_use'),
            ('is_valid_for_current_period', '=', True)
        ])
        
        _logger.info(f"符合條件的字軌數量: {len(valid_tracks)}")
        for track in valid_tracks:
            _logger.info(f"  有效字軌: {track.section_code}")

    @api.depends('invoice_title_id')
    def _compute_invoice_track(self):
        """根據選擇的發票抬頭，自動找到對應的發票字軌"""
        for record in self:
            if record.invoice_title_id:
                _logger.info(f"開始計算發票字軌，發票抬頭: {record.invoice_title_id.name} (ID: {record.invoice_title_id.id})")
                
                # 尋找該發票抬頭下狀態為"使用中"且為當前期間的發票字軌
                invoice_track = self.env['invoice.track'].search([
                    ('invoice_title_id', '=', record.invoice_title_id.id),
                    ('status', '=', 'in_use'),
                    ('is_valid_for_current_period', '=', True)
                ], limit=1)
                
                if invoice_track:
                    _logger.info(f"找到字軌: {invoice_track.section_code}")
                    record.invoice_track_id = invoice_track.id
                else:
                    _logger.warning(f"找不到符合條件的字軌，發票抬頭ID: {record.invoice_title_id.id}")
                    # 除錯：檢查所有可能的字軌
                    all_tracks = self.env['invoice.track'].search([
                        ('invoice_title_id', '=', record.invoice_title_id.id)
                    ])
                    _logger.info(f"該發票抬頭下的所有字軌: {[t.section_code for t in all_tracks]}")
                    for track in all_tracks:
                        _logger.info(f"字軌 {track.section_code}: status={track.status}, is_valid_for_current_period={track.is_valid_for_current_period}")
                    
                    record.invoice_track_id = False
            else:
                record.invoice_track_id = False
    @api.model
    def _get_invoice_title_domain(self):
        """獲取發票抬頭選擇的domain"""
        domain = [('active', '=', True)]  # 只選擇啟用的發票抬頭
        
        # 查找有使用中字軌的發票抬頭
        active_tracks = self.env['invoice.track'].search([
            ('status', '=', 'in_use'),
            ('is_valid_for_current_period', '=', True)
        ])
        
        if active_tracks:
            title_ids = active_tracks.mapped('invoice_title_id.id')
            if title_ids:
                domain.append(('id', 'in', title_ids))
        
        return domain
    @api.onchange('invoice_date')
    def _onchange_invoice_date_update_titles(self):
        """當發票日期變更時，更新可用的發票抬頭列表"""
        if self.invoice_date and self.move_type in ('out_invoice', 'out_refund'):
            domain = self._get_invoice_title_domain()
            return {'domain': {'invoice_title_id': domain}}
    
    @api.onchange('partner_id')
    def _onchange_partner_id_for_einvoice(self):
        """當合作夥伴變更時，更新買方統編"""
        if self.partner_id and self.partner_id.vat:
            # 如果客戶有統編，則自動填入
            self.einvoice_buyer_id = self.partner_id.vat.replace('TW', '') if self.partner_id.vat.startswith('TW') else self.partner_id.vat
        else:
            # 否則留空，讓用戶可以手動填入
            self.einvoice_buyer_id = False
    
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
            # 優先使用 invoice_date，如果沒有則使用 einvoice_date
            date = record.invoice_date or record.einvoice_date
            if not date:
                record.einvoice_period = False
                continue

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
                
        # 檢查是否已計算出對應的字軌
        if not self.invoice_track_id:
            raise ValidationError('找不到可用的發票字軌，請選擇其他發票抬頭或聯繫管理員')

        # 取得新發票號碼
        next_number = self.invoice_track_id.get_next_number()
        current_time = fields.Datetime.now()
        
        # 記錄同步前的發票號碼
        _logger.info(f"準備更新發票資訊: 號碼={next_number}, 時間={current_time}")
        
        # 更新發票資訊
        self.write({
            'einvoice_number': next_number,
            'einvoice_date': current_time,
            'invoice_date': current_time.date(),
            'einvoice_random_number': ''.join(random.choices('0123456789', k=4)),
            'einvoice_seller_id': self.invoice_title_id.seller_tax_id
        })

        _logger.info(f"已生成發票號碼: {next_number} (發票抬頭: {self.invoice_title_id.name})")
        
        # 同步到電子發票資訊模組
        sync_result = self._sync_to_invoice_information()
        _logger.info(f"同步結果: {'成功' if sync_result else '失敗'}")
        
        # 如果同步失敗但沒有報錯，重新檢查結果
        if sync_result:
            # 獲取關聯的電子發票資訊
            invoice_info = self.invoice_information_id
            if invoice_info:
                if invoice_info.invoice_number != self.einvoice_number:
                    _logger.error(f"發票號碼不匹配: account.move={self.einvoice_number}, invoice.information={invoice_info.invoice_number}")
                    # 嘗試強制更新
                    try:
                        invoice_info.with_context(force_einvoice_edit=True).write({
                            'invoice_number': self.einvoice_number
                        })
                        _logger.info(f"已強制更新電子發票資訊的發票號碼為 {self.einvoice_number}")
                    except Exception as e:
                        _logger.error(f"強制更新發票號碼失敗: {str(e)}")
                else:
                    _logger.info(f"發票號碼匹配: {self.einvoice_number}")
        
        return True
    def get_next_number(self):
        """獲取下一個可用的發票號碼"""
        self.ensure_one()
        
        current = self.current_number or 0
        next_number = f"{self.section_code}-{current+1:08d}"
        
        _logger.info(f"字軌 {self.section_code} 生成下一個號碼: {next_number} (current={current})")
        
        # 更新當前號碼
        self.write({'current_number': current + 1})
        
        return next_number
    
    def _sync_to_invoice_information(self):
        """將發票資訊同步到電子發票資訊模組"""
        self.ensure_one()
        
        # 已經同步過，不再重複同步
        if self.invoice_information_id:
            _logger.info(f"發票 {self.name} 已同步過，invoice_information_id={self.invoice_information_id.id}")
            return True
        
        # 檢查必要欄位
        if not (self.einvoice_number and self.invoice_track_id and self.invoice_title_id):
            _logger.error(f"發票 {self.name} 缺少必要資訊: einvoice_number={self.einvoice_number}, invoice_track_id={self.invoice_track_id}, invoice_title_id={self.invoice_title_id}")
            return False
        
        _logger.info(f"開始同步發票 {self.name}，發票號碼={self.einvoice_number}, 字軌ID={self.invoice_track_id.id}")
        
        # 準備明細行資料
        invoice_lines = []
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')):
            if not line.product_id and not line.name:
                continue
                
            line_vals = {
                'product_name': line.product_id.name or line.name or '',
                'quantity': line.quantity or 0.0,
                'unit_price': line.price_unit or 0.0,
                'unit': line.product_uom_id.name if line.product_uom_id else '',
                'line_remark': line.name if line.name != (line.product_id.name or '') else '',
            }
            invoice_lines.append((0, 0, line_vals))
        
        _logger.info(f"發票 {self.name} 明細行數: {len(invoice_lines)}")
        
        # 獲取買方地址
        buyer_address = self._get_partner_address()
        
        # 獲取稅率
        tax_rate = 0.0
        for tax in self.invoice_line_ids.mapped('tax_ids'):
            if tax.amount > 0:
                tax_rate = tax.amount
                break
        
        # 準備電子發票資訊的資料
        vals = {
            'order_id': self.name or '',  # 加這一行是關鍵，對應 invoice_information 中的 order_id
            'seller_tax_id': self.invoice_title_id.seller_tax_id or '',
            'seller_name': self.invoice_title_id.seller_name or '',
            'seller_address': self.invoice_title_id.seller_address or '',
            'seller_phone': self.invoice_title_id.seller_phone or '',
            'operation_type': '',  # 預設為開立發票
            
            'invoice_number': self.einvoice_number.replace('-', ''),  # 確保這裡有發票號碼
            'invoice_date': self.einvoice_date or fields.Datetime.now(),
            'invoice_type': self.invoice_track_id.invoice_category or '07',
            'buyer_tax_id': self.partner_id.vat_number or '',
            'buyer_name': self.partner_id.name or '',
            'buyer_address': buyer_address,
            
            'tax_type': '1',  # 預設為應稅
            'tax_rate': tax_rate,
            'sales_amount': int(self.amount_untaxed) if self.amount_untaxed else 0,
            'tax_amount': int(self.amount_tax) if self.amount_tax else 0,
            'total_amount': int(self.amount_total) if self.amount_total else 0,
            
            'invoice_track_id': self.invoice_track_id.id,
            'invoice_line_ids': invoice_lines,
            
            'currency': self.currency_id.name if self.currency_id.name in ['TWD', 'USD', 'JPY', 'EUR'] else 'TWD',
            'buyer_customer_number': self.partner_id.ref or '',
        }
        
        _logger.info(f"準備創建電子發票資訊，發票號碼={vals['invoice_number']}, 字軌ID={vals['invoice_track_id']}")
        
        # 創建電子發票資訊記錄
        try:
            # 使用特殊上下文確保不重新生成發票號碼
            special_context = {
                'from_account_move_sync': True, 
                'no_regenerate_invoice_number': True
            }
            
            _logger.info(f"使用上下文 {special_context} 創建電子發票資訊")
            
            invoice_info = self.env['invoice.information'].with_context(**special_context).create(vals)
            
            _logger.info(f"成功創建電子發票資訊，ID={invoice_info.id}, 發票號碼={invoice_info.invoice_number}")
            
            self.invoice_information_id = invoice_info.id
            return True
        except Exception as e:
            _logger.error(f"同步發票 {self.name} 到電子發票資訊模組失敗: {str(e)}")
            import traceback
            _logger.error(traceback.format_exc())
            return False

    
    def _get_partner_address(self):
        """取得合作夥伴完整地址"""
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            return ''
            
        parts = []
        if partner.zip:
            parts.append(partner.zip)
        if partner.state_id:
            parts.append(partner.state_id.name)
        if partner.city:
            parts.append(partner.city)
        if partner.street:
            parts.append(partner.street)
        if partner.street2:
            parts.append(partner.street2)
            
        return ' '.join(filter(None, parts))
    
    def action_view_invoice_information(self):
        """查看關聯的電子發票資訊"""
        self.ensure_one()
        
        if not self.invoice_information_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '提示',
                    'message': '此發票尚未同步到電子發票資訊模組',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        return {
            'name': '電子發票資訊',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.information',
            'view_mode': 'form',
            'res_id': self.invoice_information_id.id,
            'target': 'current',
        }
    
    def action_sync_invoice_information(self):
        """手動同步到電子發票資訊模組"""
        self.ensure_one()
        
        # 已經同步過，不再重複同步
        if self.invoice_information_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '提示',
                    'message': '此發票已同步到電子發票資訊模組',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # 檢查必要條件
        if not self.einvoice_number:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '錯誤',
                    'message': '此發票尚未產生發票號碼，無法同步',
                    'type': 'danger',
                    'sticky': False,
                }
            }
        
        # 使用已選擇的發票字軌記錄
        if not self.invoice_track_id:
            # 尋找關聯的發票字軌
            self.invoice_track_id = self.env['invoice.track'].search([
                # 使用發票號碼中的字軌部分進行匹配
                ('section_code', '=', self.einvoice_number.split('-')[0] if '-' in self.einvoice_number else '')
            ], limit=1).id
        
        if not self.invoice_track_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '錯誤',
                    'message': '找不到匹配的發票字軌，無法同步',
                    'type': 'danger',
                    'sticky': False,
                }
            }
        if not self.invoice_title_id and self.invoice_track_id:
            self.invoice_title_id = self.invoice_track_id.invoice_title_id.id
        
        # 同步到電子發票資訊模組
        result = self._sync_to_invoice_information()
        
        if result:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '成功',
                    'message': '已成功同步到電子發票資訊模組',
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '錯誤',
                    'message': '同步到電子發票資訊模組失敗，請查看日誌',
                    'type': 'danger',
                    'sticky': False,
                }
            }
    def action_view_related_invoice_information(self):
        """查看關聯的電子發票資訊"""
        self.ensure_one()
        
        if self.move_type != 'out_refund':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '提示',
                    'message': '只有貸記單才有關聯的電子發票資訊',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # 查找關聯的電子發票資訊
        invoice_info = self.env['invoice.information'].search([
            ('order_id', '=', self.name),
            ('operation_type', '=', 'CRE_ALW')
        ], limit=1)
        
        if not invoice_info:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '提示',
                    'message': '此貸記單尚未同步到電子發票資訊模組',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # 開啟電子發票資訊表單
        return {
            'name': '電子發票資訊',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.information',
            'view_mode': 'form',
            'res_id': invoice_info.id,
            'target': 'current',
            'context': {'create': False, 'edit': False, 'delete': False}
        }
    
    @api.model
    def sync_all_einvoices(self):
        """批量同步所有未同步的電子發票"""
        # 找出所有已有發票號碼但尚未同步的發票
        moves = self.search([
            ('einvoice_number', '!=', False),
            ('invoice_information_id', '=', False),
            ('state', '=', 'posted'),
            ('move_type', 'in', ['out_invoice', 'out_refund'])
        ])
        
        success_count = 0
        for move in moves:
            try:
                # 更新發票字軌關聯
                if not move.invoice_track_id:
                    track = self.env['invoice.track'].search([
                        ('section_code', '=', move.einvoice_number.split('-')[0] if '-' in move.einvoice_number else '')
                    ], limit=1)
                    if track:
                        move.invoice_track_id = track.id
                        # 確保發票抬頭與字軌一致
                        if not move.invoice_title_id:
                            move.invoice_title_id = track.invoice_title_id.id
                
                # 同步到電子發票資訊模組
                if move.invoice_track_id and move._sync_to_invoice_information():
                    success_count += 1
            except Exception as e:
                _logger.error(f"批量同步發票 {move.name} 失敗: {str(e)}")
                self.env.cr.rollback()
                continue
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '同步完成',
                'message': f'成功同步 {success_count}/{len(moves)} 張發票',
                'type': 'success',
                'sticky': False,
            }
        }
        
    def write(self, vals):
        result = super().write(vals)
        
        # 當貸記單狀態變為 posted 時同步
        if vals.get('state') == 'posted':
            for move in self:
                if move.move_type == 'out_refund' and move.reversed_entry_id:
                    try:
                        self.env['invoice.information'].sync_credit_note_from_account_move(move)
                    except Exception as e:
                        _logger.error(f"同步貸記單 {move.name} 失敗: {str(e)}")
                        # 不中斷整個流程，只記錄錯誤
        
        return result

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        
        # 監聽貸記單創建
        for move in moves:
            if move.move_type == 'out_refund' and move.reversed_entry_id and move.state == 'posted':
                # 同步貸記單到電子發票資訊
                self.env['invoice.information'].sync_credit_note_from_account_move(move)
        
        return moves