from odoo import fields, models, api
from odoo.models import ValidationError
import logging
from datetime import datetime
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # 基本欄位
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

    # 電子發票相關欄位
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
    invoice_format_code = fields.Char(string='發票格式', default='25', help='電子發票格式代碼')
    
    # 發票配置欄位
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
    
    # 汎宇系統相關欄位
    fanyuu_qr_code_image = fields.Text(
        string="財政部QR Code圖片",
        help="財政部77碼QR Code圖片(base64格式)"
    )
    fanyuu_barcode_image = fields.Text(
        string="汎宇條碼圖片",
        help="發票條碼圖片(base64格式)"
    )
    fanyuu_upload_time = fields.Datetime(string='汎宇上傳時間')
    fanyuu_upload_status = fields.Selection([
        ('not_uploaded', '未上傳'),
        ('uploaded', '已上傳'),
        ('failed', '上傳失敗')
    ], string='汎宇上傳狀態', default='not_uploaded')
    fanyuu_response_data = fields.Text(
        string='汎宇回應資料',
        help='儲存汎宇系統的完整回應資料，用於除錯'
    )
    
    # 汎宇QR Code相關欄位
    fanyuu_qr_code_as_key = fields.Char(string='汎宇QR Code AS Key', help='從A01取號時取得的QRCodeASKey')
    fanyuu_qr_code_77 = fields.Char(string='77碼QR Code', help='用財政部元件生成的77碼QR Code字串')
    
    # 🎯 第二個QR Code相關欄位
    detail_qr_code_content = fields.Text(
        string='明細QR Code內容',
        help='包含發票明細資訊的QR Code內容'
    )
    detail_qr_code_image = fields.Text(
        string='明細QR Code圖片',
        help='發票明細QR Code的base64圖片'
    )

    # 關聯到電子發票資訊
    invoice_information_id = fields.Many2one('invoice.information', 
                                           string='電子發票資訊', readonly=True, 
                                           copy=False)

    def action_print_receipt(self):
        """列印電子發票收據"""
        return self.env.ref('jasmine.action_report_einvoice').report_action(self)

    def action_refresh_fanyuu_data(self):
        """從汎宇系統刷新QR Code和條碼資料"""
        self.ensure_one()
        
        if not self.einvoice_number:
            raise ValidationError('此發票尚未產生發票號碼')
        
        if self.fanyuu_upload_status != 'uploaded':
            raise ValidationError('此發票尚未成功上傳至汎宇系統')
        
        # 委派給電子發票處理器處理
        try:
            processor = self.env['account.einvoice.processor']
            success = processor.refresh_fanyuu_invoice_data(self)
            
            if success:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '成功',
                        'message': '已成功從汎宇系統更新QR Code和條碼資料',
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '失敗',
                        'message': '無法從汎宇系統取得最新資料，請稍後再試',
                        'type': 'warning',
                    }
                }
        except Exception as e:
            _logger.error(f"刷新汎宇資料失敗: {str(e)}")
            raise ValidationError(f'刷新汎宇資料時發生錯誤：{str(e)}')

    @api.depends('invoice_title_id')
    def _compute_invoice_track(self):
        """根據選擇的發票抬頭，自動找到對應的發票字軌"""
        for record in self:
            if record.invoice_title_id:
                invoice_track = self.env['invoice.track'].search([
                    ('invoice_title_id', '=', record.invoice_title_id.id),
                    ('status', '=', 'in_use'),
                    ('is_valid_for_current_period', '=', True)
                ], limit=1)
                
                record.invoice_track_id = invoice_track.id if invoice_track else False
            else:
                record.invoice_track_id = False

    @api.onchange('partner_id')
    def _onchange_partner_id_for_einvoice(self):
        """當合作夥伴變更時，更新買方統編"""
        if self.partner_id and self.partner_id.vat:
            self.einvoice_buyer_id = self.partner_id.vat.replace('TW', '') if self.partner_id.vat.startswith('TW') else self.partner_id.vat
        else:
            self.einvoice_buyer_id = False
    
    @api.onchange('is_cash_payment', 'is_credit_payment', 'amount_total')
    def _onchange_payment_method(self):
        """根據付款方式自動分配金額"""
        if self.is_cash_payment and not self.is_credit_payment:
            self.payment_cash = self.amount_total
            self.payment_credit = 0
        elif self.is_credit_payment and not self.is_cash_payment:
            self.payment_credit = self.amount_total
            self.payment_cash = 0
        elif self.is_cash_payment and self.is_credit_payment:
            half_amount = self.amount_total / 2
            self.payment_cash = half_amount
            self.payment_credit = half_amount
        else:
            self.payment_cash = 0
            self.payment_credit = 0

    @api.depends('invoice_date')
    def _compute_einvoice_period(self):
        """計算發票期別（每兩個月為一期）"""
        for record in self:
            date = record.invoice_date or record.einvoice_date
            if not date:
                record.einvoice_period = False
                continue

            roc_year = date.year - 1911
            month = date.month
            start_month = ((month - 1) // 2) * 2 + 1
            end_month = start_month + 1
            record.einvoice_period = f"{roc_year}年{str(start_month).zfill(2)}-{str(end_month).zfill(2)}月"

    def update_fanyuu_invoice_data(self, qr_code_image=None, barcode_image=None, 
                                   certification_number=None, response_data=None):
        """
        更新汎宇發票相關資料
        
        Args:
            qr_code_image: QR Code圖片(base64格式)
            barcode_image: 條碼圖片(base64格式)  
            certification_number: 加密驗證碼
            response_data: 汎宇回應的完整資料
        """
        self.ensure_one()
        
        vals = {}
        
        if qr_code_image:
            vals['fanyuu_qr_code_image'] = qr_code_image
            
        if barcode_image:
            vals['fanyuu_barcode_image'] = barcode_image
            
        if certification_number:
            vals['einvoice_certification_number'] = certification_number
            
        if response_data:
            vals['fanyuu_response_data'] = response_data
        
        if vals:
            self.write(vals)
            _logger.info(f"已更新發票 {self.name} 的汎宇資料")

    def _generate_qr_code_77(self):
        """生成財政部77碼QR Code - 修正版"""
        self.ensure_one()
        
        if not all([self.einvoice_number, self.einvoice_date, self.einvoice_random_number]):
            _logger.warning(f"發票 {self.name} 缺少必要欄位，無法生成QR Code")
            return False
        
        # 從發票字軌取得QRCodeASKey
        if not self.invoice_track_id:
            _logger.error(f"發票 {self.name} 找不到發票字軌")
            return False
            
        qr_code_as_key = self.invoice_track_id.fanyuu_qr_code_as_key
        
        # 如果QRCodeASKey為空，嘗試重新取得
        if not qr_code_as_key:
            _logger.warning(f"發票 {self.name} QRCodeASKey為空，嘗試重新取得")
            
            try:
                from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
                
                fanyuu_api = FanyuuPosAPI(self.env)
                result = fanyuu_api.get_invoice_track_info(self.invoice_title_id.id)
                
                if result['success'] and result.get('track_info', {}).get('qr_code_key'):
                    qr_code_as_key = result['track_info']['qr_code_key']
                    
                    # 更新字軌記錄
                    self.invoice_track_id.write({
                        'fanyuu_qr_code_as_key': qr_code_as_key
                    })
                    
                    _logger.info(f"發票 {self.name} 成功重新取得QRCodeASKey: {qr_code_as_key}")
                else:
                    _logger.error(f"發票 {self.name} 重新取得QRCodeASKey失敗")
                    return False
                    
            except Exception as e:
                _logger.error(f"發票 {self.name} 重新取得QRCodeASKey異常: {str(e)}")
                return False

        try:
            # 準備財政部規格的53碼明文參數
            invoice_number = self.einvoice_number.replace('-', '')  # 10碼
            
            # 開立年月日(民國年yyymmdd) - 7碼
            roc_year = self.einvoice_date.year - 1911
            invoice_date = f"{roc_year:03d}{self.einvoice_date.month:02d}{self.einvoice_date.day:02d}"
            
            # 時間(hhmmss) - 6碼
            invoice_time = f"{self.einvoice_date.hour:02d}{self.einvoice_date.minute:02d}{self.einvoice_date.second:02d}"
            
            # 四位隨機碼 - 4碼
            random_number = (self.einvoice_random_number or '0000').zfill(4)
            
            # 金額(8碼，無小數點)
            sales_amount = f"{int(self.amount_untaxed):08d}"
            tax_amount = f"{int(self.amount_tax):08d}"
            total_amount = f"{int(self.amount_total):08d}"
            
            # 統編(8碼)
            buyer_id = ((self.partner_id.vat or '00000000').replace('TW', '')).zfill(8)
            represent_id = '00000000'  # 代表店統編，一般為00000000
            seller_id = (self.invoice_track_id.invoice_title_id.seller_tax_id or '00000000').zfill(8)
            business_id = seller_id  # 營業人統編，通常同賣方統編
            
            # 組合前53碼明文
            params_53 = (
                invoice_number +      # 10碼
                invoice_date +        # 7碼  
                invoice_time +        # 6碼
                random_number +       # 4碼
                sales_amount +        # 8碼
                tax_amount +          # 8碼
                total_amount +        # 8碼
                buyer_id +           # 8碼
                represent_id +       # 8碼
                seller_id +          # 8碼
                business_id          # 8碼
            )  # 總共53碼
            
            _logger.info(f"發票 {self.name} 前53碼參數: {params_53}")
            _logger.info(f"發票 {self.name} 使用QRCodeASKey: {qr_code_as_key}")
            
            # 使用QRCodeASKey進行AES加密生成後24碼
            encrypted_24 = self._aes_encrypt_with_qr_key(params_53, qr_code_as_key)
            
            # 組合77碼QR Code
            qr_code_77 = params_53 + encrypted_24
            
            # 儲存77碼QR Code字串
            self.fanyuu_qr_code_77 = qr_code_77
            
            # 生成財政部QR Code圖片
            self._generate_qr_code_image(qr_code_77)
            
            # 生成條碼圖片
            self._generate_barcode_image()
            
            # 🎯 同時生成發票明細QR Code
            detail_success = self._generate_detail_qr_code()
            
            _logger.info(f"發票 {self.name} 財政部QR Code生成成功: {qr_code_77}")
            if detail_success:
                _logger.info(f"發票 {self.name} 發票明細QR Code生成成功")
            else:
                _logger.warning(f"發票 {self.name} 發票明細QR Code生成失敗")
            
            return True
            
        except Exception as e:
            _logger.error(f"發票 {self.name} 生成QR Code失敗: {str(e)}")
            import traceback
            _logger.error(f"錯誤詳情: {traceback.format_exc()}")
            return False

    def _generate_qr_code_image(self, qr_content):
        """生成財政部QR Code圖片 - 加強錯誤處理版"""
        try:
            import qrcode
            from io import BytesIO
            import base64
            
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_content)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            
            self.fanyuu_qr_code_image = base64.b64encode(buffer.getvalue()).decode()
            
            _logger.info(f"發票 {self.name} 財政部QR Code圖片生成成功")
            
        except ImportError:
            _logger.error("缺少qrcode套件，請執行: pip install qrcode[pil]")
        except Exception as e:
            _logger.error(f"生成財政部QR Code圖片失敗: {str(e)}")

    def _generate_detail_qr_code(self):
        """生成發票明細QR Code - 修正版"""
        self.ensure_one()
        
        if not self.einvoice_number:
            _logger.warning(f"發票 {self.name} 尚未產生發票號碼，無法生成明細QR Code")
            return False
        
        try:
            # 準備簡化的明細資訊（避免內容過長）
            detail_info = []
            
            # 基本發票資訊
            detail_info.append(f"發票號碼: {self.einvoice_number}")
            detail_info.append(f"開立時間: {self.einvoice_date.strftime('%Y-%m-%d %H:%M:%S') if self.einvoice_date else ''}")
            detail_info.append(f"賣方: {self.invoice_title_id.seller_name if self.invoice_title_id else ''}")
            detail_info.append(f"統編: {self.einvoice_seller_id or ''}")
            detail_info.append(f"總金額: {int(self.amount_total)}")
            
            # 加入商品明細（最多3項）
            detail_info.append("--- 商品明細 ---")
            line_count = 0
            for line in self.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')):
                if line_count >= 3:  # 最多3項
                    break
                
                product_name = line.product_id.name or line.name or '商品'
                # 限制商品名稱長度
                if len(product_name) > 20:
                    product_name = product_name[:20] + "..."
                
                detail_info.append(f"{product_name}: {int(line.quantity)}x{int(line.price_unit)}={int(line.price_subtotal)}")
                line_count += 1
            
            # 如果有更多商品
            total_lines = len(self.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')))
            if total_lines > 3:
                detail_info.append(f"...等共{total_lines}項商品")
            
            # 將資訊組合成字串
            detail_content = '\n'.join(detail_info)
            
            # 確保內容不超過QR Code限制（約2000字元）
            if len(detail_content) > 1500:
                # 進一步簡化
                simple_info = [
                    f"發票: {self.einvoice_number}",
                    f"時間: {self.einvoice_date.strftime('%Y-%m-%d %H:%M') if self.einvoice_date else ''}",
                    f"賣方: {(self.invoice_title_id.seller_name if self.invoice_title_id else '')[:10]}",
                    f"金額: {int(self.amount_total)}",
                    f"項目數: {total_lines}"
                ]
                detail_content = '\n'.join(simple_info)
            
            # 儲存明細內容
            self.detail_qr_code_content = detail_content
            
            # 生成QR Code圖片
            success = self._generate_detail_qr_code_image(detail_content)
            
            if success:
                _logger.info(f"發票 {self.name} 明細QR Code生成成功")
                return True
            else:
                _logger.error(f"發票 {self.name} 明細QR Code圖片生成失敗")
                return False
                
        except Exception as e:
            _logger.error(f"發票 {self.name} 生成明細QR Code失敗: {str(e)}")
            import traceback
            _logger.error(f"錯誤詳情: {traceback.format_exc()}")
            return False

    def _generate_detail_qr_code_image(self, qr_content):
        """生成明細QR Code圖片 - 加強錯誤處理"""
        try:
            import qrcode
            from io import BytesIO
            import base64
            
            # 檢查內容長度
            if len(qr_content) > 2000:
                _logger.warning(f"QR Code內容過長 ({len(qr_content)} 字元)，將被截斷")
                qr_content = qr_content[:1800] + "..."
            
            # 建立QR Code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            
            qr.add_data(qr_content)
            qr.make(fit=True)
            
            # 生成圖片
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            
            # 儲存為base64
            self.detail_qr_code_image = base64.b64encode(buffer.getvalue()).decode()
            
            _logger.info(f"發票 {self.name} 明細QR Code圖片生成成功")
            return True
            
        except ImportError:
            _logger.error("缺少qrcode套件，請執行: pip install qrcode[pil]")
            return False
        except Exception as e:
            _logger.error(f"生成明細QR Code圖片失敗: {str(e)}")
            return False

    def _generate_barcode_image(self):
        """修改條碼生成 - 移除條碼下方的文字顯示"""
        try:
            import barcode
            from barcode.writer import ImageWriter
            from io import BytesIO
            import base64
            
            # 使用完整的發票號碼（包含字軌）
            if self.invoice_track_id and self.invoice_track_id.section_code:
                # 格式：字軌+發票號碼（例如：XA19242768）
                full_invoice_number = f"{self.invoice_track_id.section_code}{self.einvoice_number.replace('-', '')}"
            else:
                # 如果沒有字軌，使用原本的發票號碼
                full_invoice_number = self.einvoice_number.replace('-', '')
            
            # 設定條碼選項 - 關閉文字顯示
            options = {
                'write_text': False,  # 關鍵參數：不顯示條碼下方的文字
                'module_width': 0.3,  # 條碼寬度
                'module_height': 10,  # 條碼高度
            }
            
            code39 = barcode.get('code39', full_invoice_number, writer=ImageWriter())
            buffer = BytesIO()
            code39.write(buffer, options=options)
            
            self.fanyuu_barcode_image = base64.b64encode(buffer.getvalue()).decode()
            
            _logger.info(f"發票 {self.name} 條碼圖片生成成功: {full_invoice_number}")
            
        except Exception as e:
            _logger.error(f"生成條碼圖片失敗: {str(e)}")

    def action_generate_einvoice_number(self):
        """手動生成電子發票號碼 - 回到簡單的直接更新方式"""
        self.ensure_one()
        
        # 前置驗證
        if self.state != 'posted':
            raise ValidationError('發票必須先過帳才能產生發票號碼')
        
        # 檢查是否有發票明細行
        invoice_lines = self.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note'))
        if not invoice_lines:
            raise ValidationError('應收憑單表身沒有發票資料之前不可以產生發票號碼')
        
        # 檢查付款方式
        if not (self.is_cash_payment or self.is_credit_payment):
            raise ValidationError('請先選擇付款方式')
            
        # 檢查是否已有發票號碼
        if self.einvoice_number:
            raise ValidationError('此發票已有發票號碼')

        # 檢查是否已選擇發票抬頭
        if not self.invoice_title_id:
            raise ValidationError('請先選擇發票抬頭')
                
        # 檢查是否已計算出對應的字軌
        if not self.invoice_track_id:
            raise ValidationError('找不到可用的發票字軌，請選擇其他發票抬頭或聯繫管理員')

        try:
            # 步驟1: 直接生成發票號碼和基本資料
            invoice_number = self.invoice_track_id.get_next_number()
            
            # 生成隨機碼
            import random
            random_number = f"{random.randint(0, 9999):04d}"
            
            # 直接更新當前記錄的欄位
            self.write({
                'einvoice_number': invoice_number,
                'einvoice_date': fields.Datetime.now(),
                'einvoice_random_number': random_number,
                'einvoice_seller_id': self.invoice_track_id.invoice_title_id.seller_tax_id
            })
            
            _logger.info(f"步驟1完成: 發票號碼生成 {invoice_number}")
            
            # 步驟2: 生成QR Code
            try:
                self._generate_qr_code_77()
                _logger.info(f"步驟2完成: QR Code生成成功")
            except Exception as e:
                _logger.warning(f"步驟2警告: QR Code生成失敗: {str(e)}")
                # QR Code生成失敗不影響主流程
            
            # 步驟3: 同步到電子發票資訊模組
            try:
                processor = self.env['account.einvoice.processor']
                processor._sync_to_invoice_information(self)
                _logger.info(f"步驟3完成: 電子發票資訊同步成功")
            except Exception as e:
                _logger.warning(f"步驟3警告: 電子發票資訊同步失敗: {str(e)}")
                # 同步失敗不影響主流程
            
            # 步驟4: 自動上傳到汎宇
            try:
                processor = self.env['account.einvoice.processor']
                processor._auto_upload_to_fanyuu(self)
                _logger.info(f"步驟4完成: 汎宇上傳完成")
            except Exception as e:
                _logger.warning(f"步驟4警告: 汎宇上傳失敗: {str(e)}")
                # 上傳失敗不影響主流程
            
            # 返回什麼都不做的action，讓Odoo自然更新欄位
            return 
            
        except Exception as e:
            _logger.error(f"生成發票號碼失敗: {str(e)}")
            raise ValidationError(f'生成發票號碼失敗：{str(e)}')

    def _aes_encrypt_with_qr_key(self, plaintext, qr_code_as_key):
        """AES加密邏輯 - 保留在account.move中"""
        try:
            import base64
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
            import hashlib
            
            # 處理QRCodeASKey
            if len(qr_code_as_key) >= 32:
                try:
                    aes_key = bytes.fromhex(qr_code_as_key[:32])[:16]
                except ValueError:
                    aes_key = hashlib.md5(qr_code_as_key.encode()).digest()
            else:
                aes_key = hashlib.md5(qr_code_as_key.encode()).digest()
            
            # 財政部固定的IV
            iv = base64.b64decode('Dt8lyToo17X/XkXaQvihuA==')
            
            # AES-128-CBC加密
            cipher = AES.new(aes_key, AES.MODE_CBC, iv)
            padded_plaintext = pad(plaintext.encode('utf-8'), AES.block_size)
            encrypted = cipher.encrypt(padded_plaintext)
            encrypted_base64 = base64.b64encode(encrypted).decode('utf-8')
            
            return encrypted_base64[:24].ljust(24, '=')
            
        except Exception as e:
            _logger.error(f"AES加密失敗: {str(e)}")
            return "0000000000000000000000=="

    # ==================== 其他業務方法 ====================

    def _validate_invoice_generation(self):
        """驗證發票生成的前置條件"""
        if self.state != 'posted':
            raise ValidationError('發票必須先過帳才能產生發票號碼')
        
        # 檢查是否有發票明細行
        invoice_lines = self.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note'))
        if not invoice_lines:
            raise ValidationError('應收憑單表身沒有發票資料之前不可以產生發票號碼')
        
        # 檢查付款方式
        if not (self.is_cash_payment or self.is_credit_payment):
            raise ValidationError('請先選擇付款方式')
            
        # 檢查是否已有發票號碼
        if self.einvoice_number:
            raise ValidationError('此發票已有發票號碼')

        # 檢查是否已選擇發票抬頭
        if not self.invoice_title_id:
            raise ValidationError('請先選擇發票抬頭')
                
        # 檢查是否已計算出對應的字軌
        if not self.invoice_track_id:
            raise ValidationError('找不到可用的發票字軌，請選擇其他發票抬頭或聯繫管理員')

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
        
        # 委派給電子發票處理器
        return self.env['account.einvoice.processor'].sync_to_invoice_information(self)

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
        
        return result

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        
        # 監聽貸記單創建
        for move in moves:
            if move.move_type == 'out_refund' and move.reversed_entry_id and move.state == 'posted':
                self.env['invoice.information'].sync_credit_note_from_account_move(move)
        
        return moves

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
        
        return {
            'name': '電子發票資訊',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.information',
            'view_mode': 'form',
            'res_id': invoice_info.id,
            'target': 'current',
            'context': {'create': False, 'edit': False, 'delete': False}
        }