from odoo import fields, models, api
from odoo.models import ValidationError
import logging
from datetime import datetime
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # 第二個QR Code相關欄位
    detail_qr_code_content = fields.Text(
        string='明細QR Code內容',
        help='包含發票明細資訊的QR Code內容'
    )
    detail_qr_code_image = fields.Text(
        string='明細QR Code圖片',
        help='發票明細QR Code的base64圖片'
    )

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