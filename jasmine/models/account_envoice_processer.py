# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import random
import logging

_logger = logging.getLogger(__name__)

class AccountEinvoiceProcessor(models.Model):
    """電子發票處理器 - 負責業務流程協調和資料處理"""
    _name = 'account.einvoice.processor'
    _description = '電子發票處理器'

    # ==================== 主要業務流程方法 ====================
    
    def generate_complete_einvoice(self, account_move):
        """完整的電子發票處理流程 - 業務邏輯核心"""
        account_move.ensure_one()
        
        try:
            _logger.info(f"開始完整發票處理流程 - 發票: {account_move.name}")
            
            # 步驟1: 生成發票號碼和基本資料
            self._generate_invoice_number_and_data(account_move)
            
            # 步驟2: 處理QR Code生成（確保QRCodeASKey可用）
            self._ensure_qr_code_generation(account_move)
            
            # 步驟3: 同步到電子發票資訊模組
            self._sync_to_invoice_information(account_move)
            
            # 步驟4: 自動上傳到汎宇
            self._auto_upload_to_fanyuu(account_move)
            
            
            return 
            
        except Exception as e:
            _logger.error(f"完整發票處理流程失敗: {str(e)}")
            import traceback
            _logger.error(f"錯誤詳情: {traceback.format_exc()}")
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '失敗',
                    'message': f'發票處理失敗：{str(e)}',
                    'type': 'danger',
                }
            }

    # ==================== 步驟處理方法 ====================
    
    def _generate_invoice_number_and_data(self, account_move):
        """步驟1: 生成發票號碼和更新基本資料"""
        try:
            # 從發票字軌取號（這會自動處理A01和QRCodeASKey）
            invoice_number = account_move.invoice_track_id.get_next_number()
            
            # 生成隨機碼
            random_number = f"{random.randint(0, 9999):04d}"
            
            # 更新發票資訊
            account_move.write({
                'einvoice_number': invoice_number,
                'einvoice_date': fields.Datetime.now(),
                'einvoice_random_number': random_number,
                'einvoice_seller_id': account_move.invoice_track_id.invoice_title_id.seller_tax_id
            })
            
            _logger.info(f"步驟1完成: 發票號碼生成 {invoice_number}")
            
        except Exception as e:
            _logger.error(f"步驟1失敗: 發票號碼生成失敗: {str(e)}")
            raise

    def _ensure_qr_code_generation(self, account_move):
        """步驟2: 確保QR Code生成成功 - 最終簡化版"""
        try:
            # 檢查QRCodeASKey是否存在
            qr_code_as_key = account_move.invoice_track_id.fanyuu_qr_code_as_key
            
            if not qr_code_as_key:
                _logger.warning(f"步驟2: QRCodeASKey為空，嘗試重新取得")
                # 強制重新取得QRCodeASKey
                success = self._force_refresh_qr_code_key(account_move)
                if success:
                    # 重新讀取QRCodeASKey
                    account_move.invoice_track_id._compute_display_name()  # 觸發重新讀取
                    qr_code_as_key = account_move.invoice_track_id.fanyuu_qr_code_as_key
            
            # 直接嘗試生成QR Code
            success = account_move._generate_qr_code_77()
            
            if success:
                _logger.info(f"步驟2完成: QR Code生成成功")
            else:
                _logger.warning(f"步驟2警告: QR Code生成失敗，可能是QRCodeASKey問題")
                
        except Exception as e:
            _logger.error(f"步驟2異常: QR Code處理異常: {str(e)}")
            # QR Code生成失敗不中斷流程

    def _sync_to_invoice_information(self, account_move):
        """步驟3: 同步到電子發票資訊模組"""
        try:
            # 如果已經同步過，跳過
            if account_move.invoice_information_id:
                _logger.info(f"步驟3跳過: 發票 {account_move.name} 已同步過")
                return
            
            # 調用同步邏輯
            result = self._sync_invoice_information(account_move)
            
            if result:
                _logger.info(f"步驟3完成: 電子發票資訊同步成功")
            else:
                _logger.warning(f"步驟3失敗: 電子發票資訊同步失敗")
                
        except Exception as e:
            _logger.error(f"步驟3異常: 電子發票資訊同步異常: {str(e)}")
            # 同步失敗不中斷流程，但要記錄

    def _auto_upload_to_fanyuu(self, account_move):
        """步驟4: 自動上傳到汎宇系統"""
        try:
            # 檢查是否啟用自動上傳
            auto_upload_enabled = self.env['ir.config_parameter'].sudo().get_param('fanyuu.auto_upload_invoice', 'true')
            
            if auto_upload_enabled.lower() != 'true':
                _logger.info(f"步驟4跳過: 自動上傳功能已停用")
                return
            
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            fanyuu_api = FanyuuPosAPI(self.env)
            result = fanyuu_api.upload_invoice_to_fanyuu(account_move.id, account_move.invoice_title_id.id)
            
            if result['success']:
                account_move.write({
                    'fanyuu_upload_status': 'uploaded',
                    'fanyuu_upload_time': fields.Datetime.now()
                })
                _logger.info(f"步驟4完成: 汎宇上傳成功")
            else:
                account_move.write({'fanyuu_upload_status': 'failed'})
                _logger.warning(f"步驟4失敗: 汎宇上傳失敗: {result['message']}")
                
        except Exception as e:
            _logger.error(f"步驟4異常: 汎宇上傳異常: {str(e)}")
            account_move.write({'fanyuu_upload_status': 'failed'})

    # ==================== 輔助方法 ====================
    
    def _force_refresh_qr_code_key(self, account_move):
        """強制重新取得QRCodeASKey - 最簡版"""
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            fanyuu_api = FanyuuPosAPI(self.env)
            result = fanyuu_api.get_invoice_track_info(account_move.invoice_title_id.id)
            
            if result['success'] and result.get('track_info', {}).get('qr_code_key'):
                qr_code_as_key = result['track_info']['qr_code_key']
                
                # 直接更新字軌記錄
                account_move.invoice_track_id.write({
                    'fanyuu_qr_code_as_key': qr_code_as_key
                })
                
                _logger.info(f"強制重新取得QRCodeASKey成功: {qr_code_as_key}")
                return True
            else:
                _logger.error(f"強制重新取得QRCodeASKey失敗: {result.get('message', '未知錯誤')}")
                return False
                
        except Exception as e:
            _logger.error(f"強制重新取得QRCodeASKey異常: {str(e)}")
            return False

    def _sync_invoice_information(self, account_move):
        """同步發票資訊到電子發票系統"""
        account_move.ensure_one()
        
        # 已經同步過，不再重複同步
        if account_move.invoice_information_id:
            _logger.info(f"發票 {account_move.name} 已同步過，invoice_information_id={account_move.invoice_information_id.id}")
            return True
        
        # 檢查必要欄位
        if not (account_move.einvoice_number and account_move.invoice_track_id and account_move.invoice_title_id):
            _logger.error(f"發票 {account_move.name} 缺少必要資訊")
            return False
        
        _logger.info(f"開始同步發票 {account_move.name}，發票號碼={account_move.einvoice_number}, 字軌ID={account_move.invoice_track_id.id}")
        
        # 準備明細行資料
        invoice_lines = []
        for line in account_move.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')):
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
        
        _logger.info(f"發票 {account_move.name} 明細行數: {len(invoice_lines)}")
        
        # 獲取買方地址
        buyer_address = account_move._get_partner_address()
        
        # 獲取稅率
        tax_rate = 0.0
        for tax in account_move.invoice_line_ids.mapped('tax_ids'):
            if tax.amount > 0:
                tax_rate = tax.amount
                break
        
        # 準備電子發票資訊的資料
        vals = {
            'order_id': account_move.name or '',
            'seller_tax_id': account_move.invoice_title_id.seller_tax_id or '',
            'seller_name': account_move.invoice_title_id.seller_name or '',
            'seller_address': account_move.invoice_title_id.seller_address or '',
            'seller_phone': account_move.invoice_title_id.seller_phone or '',
            'operation_type': '',  # 預設為開立發票
            
            'invoice_number': account_move.einvoice_number.replace('-', ''),
            'invoice_date': account_move.einvoice_date or fields.Datetime.now(),
            'invoice_type': account_move.invoice_track_id.invoice_category or '07',
            'buyer_tax_id': account_move.partner_id.vat_number or '',
            'buyer_name': account_move.partner_id.name or '',
            'buyer_address': buyer_address,
            
            'tax_type': '1',  # 預設為應稅
            'tax_rate': tax_rate,
            'sales_amount': int(account_move.amount_untaxed) if account_move.amount_untaxed else 0,
            'tax_amount': int(account_move.amount_tax) if account_move.amount_tax else 0,
            'total_amount': int(account_move.amount_total) if account_move.amount_total else 0,
            
            'invoice_track_id': account_move.invoice_track_id.id,
            'invoice_line_ids': invoice_lines,
            
            'currency': account_move.currency_id.name if account_move.currency_id.name in ['TWD', 'USD', 'JPY', 'EUR'] else 'TWD',
            'buyer_customer_number': account_move.partner_id.ref or '',
        }
        
        _logger.info(f"準備創建電子發票資訊，發票號碼={vals['invoice_number']}, 字軌ID={vals['invoice_track_id']}")
        
        # 創建電子發票資訊記錄
        try:
            special_context = {
                'from_account_move_sync': True, 
                'no_regenerate_invoice_number': True
            }
            
            _logger.info(f"使用上下文 {special_context} 創建電子發票資訊")
            
            invoice_info = self.env['invoice.information'].with_context(**special_context).create(vals)
            
            _logger.info(f"成功創建電子發票資訊，ID={invoice_info.id}, 發票號碼={invoice_info.invoice_number}")
            
            account_move.invoice_information_id = invoice_info.id
            
            return True
            
        except Exception as e:
            _logger.error(f"同步發票 {account_move.name} 到電子發票資訊模組失敗: {str(e)}")
            import traceback
            _logger.error(traceback.format_exc())
            return False

    # ==================== 兼容性方法 ====================
    
    def generate_einvoice_number(self, account_move):
        """舊方法保持兼容性，但建議使用generate_complete_einvoice"""
        _logger.warning("使用了舊的generate_einvoice_number方法，建議使用generate_complete_einvoice")
        return self.generate_complete_einvoice(account_move)

    # ==================== 管理功能方法 ====================
    
    def refresh_fanyuu_invoice_data(self, account_move):
        """從汎宇系統刷新發票資料"""
        account_move.ensure_one()
        
        if not account_move.einvoice_number:
            return False
        
        if account_move.fanyuu_upload_status != 'uploaded':
            return False
        
        try:
            # 重新生成QR Code
            success = self._ensure_qr_code_generation(account_move)
            return success
            
        except Exception as e:
            _logger.error(f"刷新汎宇資料失敗: {str(e)}")
            return False

    def sync_to_invoice_information(self, account_move):
        """手動同步到電子發票資訊模組"""
        account_move.ensure_one()
        
        # 尋找關聯的發票字軌
        if not account_move.invoice_track_id:
            section_code = account_move.einvoice_number.split('-')[0] if '-' in account_move.einvoice_number else ''
            track = self.env['invoice.track'].search([('section_code', '=', section_code)], limit=1)
            if track:
                account_move.invoice_track_id = track.id
        
        if not account_move.invoice_track_id:
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
            
        if not account_move.invoice_title_id and account_move.invoice_track_id:
            account_move.invoice_title_id = account_move.invoice_track_id.invoice_title_id.id
        
        # 同步到電子發票資訊模組
        result = self._sync_invoice_information(account_move)
        
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

    # ==================== 批量處理方法 ====================
    
    @api.model
    def sync_all_einvoices(self):
        """批量同步所有未同步的電子發票"""
        # 找出所有已有發票號碼但尚未同步的發票
        moves = self.env['account.move'].search([
            ('einvoice_number', '!=', False),
            ('invoice_information_id', '=', False),
            ('state', '=', 'posted'),
            ('move_type', 'in', ['out_invoice', 'out_refund'])
        ])
        
        success_count = 0
        failed_moves = []
        
        for move in moves:
            try:
                # 更新發票字軌關聯
                if not move.invoice_track_id:
                    section_code = move.einvoice_number.split('-')[0] if '-' in move.einvoice_number else ''
                    track = self.env['invoice.track'].search([('section_code', '=', section_code)], limit=1)
                    if track:
                        move.invoice_track_id = track.id
                        # 確保發票抬頭與字軌一致
                        if not move.invoice_title_id:
                            move.invoice_title_id = track.invoice_title_id.id
                
                # 同步到電子發票資訊模組
                if move.invoice_track_id and self._sync_invoice_information(move):
                    success_count += 1
                else:
                    failed_moves.append(move.name)
                    
            except Exception as e:
                _logger.error(f"批量同步發票 {move.name} 失敗: {str(e)}")
                failed_moves.append(move.name)
                continue
        
        # 準備回應訊息
        message = f'成功同步 {success_count}/{len(moves)} 張發票'
        if failed_moves:
            message += f'\n失敗的發票: {", ".join(failed_moves[:5])}'
            if len(failed_moves) > 5:
                message += f' 等 {len(failed_moves)} 張'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '批量同步完成',
                'message': message,
                'type': 'success' if success_count > 0 else 'warning',
                'sticky': True,
            }
        }

    @api.model
    def retry_failed_uploads(self):
        """重試失敗的汎宇上傳"""
        # 找到上傳失敗的發票
        failed_moves = self.env['account.move'].search([
            ('fanyuu_upload_status', '=', 'failed'),
            ('einvoice_number', '!=', False),
            ('state', '=', 'posted')
        ])
        
        success_count = 0
        still_failed = []
        
        for move in failed_moves:
            try:
                # 重新嘗試上傳
                self._auto_upload_to_fanyuu(move)
                if move.fanyuu_upload_status == 'uploaded':
                    success_count += 1
                else:
                    still_failed.append(move.einvoice_number)
                    
            except Exception as e:
                _logger.error(f"重試上傳發票 {move.einvoice_number} 失敗: {str(e)}")
                still_failed.append(move.einvoice_number)
        
        # 準備回應訊息
        message = f'重試上傳完成: 成功 {success_count}/{len(failed_moves)} 張'
        if still_failed:
            message += f'\n仍然失敗: {", ".join(still_failed[:5])}'
            if len(still_failed) > 5:
                message += f' 等 {len(still_failed)} 張'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '重試上傳完成',
                'message': message,
                'type': 'success' if success_count > 0 else 'warning',
                'sticky': True,
            }
        }

    # ==================== 系統管理方法 ====================
    
    @api.model
    def test_fanyuu_connection(self):
        """測試汎宇連線"""
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            api = FanyuuPosAPI(self.env)
            
            # 使用 Y01 功能測試連線 (取系統時間)
            result = api.get_system_time()
            
            if result and result.get('success'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '連線測試成功',
                        'message': f'汎宇系統連線正常\n系統時間: {result.get("system_time", "")}',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                message = result.get('message', '連線失敗') if result else '無回應'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '連線測試失敗',
                        'message': f'汎宇系統連線異常: {message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"測試汎宇連線失敗: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '連線測試異常',
                    'message': f'測試連線時發生錯誤: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    @api.model
    def get_fanyuu_status_summary(self):
        """取得汎宇狀態統計"""
        # 統計account.move的上傳狀態
        total_invoices = self.env['account.move'].search_count([
            ('einvoice_number', '!=', False),
            ('state', '=', 'posted'),
            ('move_type', 'in', ['out_invoice', 'out_refund'])
        ])
        
        success_count = self.env['account.move'].search_count([
            ('fanyuu_upload_status', '=', 'uploaded'),
            ('state', '=', 'posted')
        ])
        
        failed_count = self.env['account.move'].search_count([
            ('fanyuu_upload_status', '=', 'failed'),
            ('state', '=', 'posted')
        ])
        
        not_uploaded_count = self.env['account.move'].search_count([
            ('fanyuu_upload_status', '=', 'not_uploaded'),
            ('einvoice_number', '!=', False),
            ('state', '=', 'posted')
        ])
        
        # 統計今日的發票
        today_invoices = self.env['account.move'].search_count([
            ('einvoice_date', '>=', fields.Date.today()),
            ('einvoice_number', '!=', False)
        ])
        
        today_success = self.env['account.move'].search_count([
            ('einvoice_date', '>=', fields.Date.today()),
            ('fanyuu_upload_status', '=', 'uploaded')
        ])
        
        summary = {
            'total': total_invoices,
            'success': success_count,
            'failed': failed_count,
            'not_uploaded': not_uploaded_count,
            'today_total': today_invoices,
            'today_success': today_success,
            'success_rate': round((success_count / total_invoices * 100) if total_invoices > 0 else 0, 2),
            'today_success_rate': round((today_success / today_invoices * 100) if today_invoices > 0 else 0, 2)
        }
        
        return summary