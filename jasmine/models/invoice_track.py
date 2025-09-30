from odoo import fields, models, api
from odoo.exceptions import UserError, ValidationError
import json
import logging

_logger = logging.getLogger(__name__)

class InvoiceTrack(models.Model):
    _name = 'invoice.track'
    _description = 'Invoice Track Number Record'
    _rec_name = 'display_name'

    date_from = fields.Date(string='發票起始日期', required=True)
    date_to = fields.Date(string='發票結束日期', required=True)
    section_code = fields.Char(string='字軌號碼', required=True)
    number_from = fields.Char(string='發票起始號碼', required=True)
    number_to = fields.Char(string='發票結束號碼', required=True)
    is_used = fields.Boolean(string='已使用', default=False)
    last_used_number = fields.Char(string='最後使用號碼', readonly=True)
    invoice_period = fields.Char(string='發票週期', compute='_compute_period', store=True)
    is_active = fields.Boolean(string='是否啟用中', default=False)
    status = fields.Selection([
        ('unused', '未啟用'),
        ('in_use', '使用中'),
        ('used_up', '已用畢')
    ], string='使用狀態', default='unused', required=True, tracking=True)
    next_available_number = fields.Char(string='下一個可用號碼', compute='_compute_next_number')
    invoice_title_id = fields.Many2one('invoice.title', string='發票抬頭', required=True)
    display_name = fields.Char(string='顯示名稱', compute='_compute_display_name', store=True)
    invoice_category = fields.Selection([
        ('07', '一般稅額計算電子發票'),
        ('08', '特殊稅額計算電子發票'),
    ], string='發票類別', required=True, default='07')
    is_valid_for_current_period = fields.Boolean(
        string='是否為當前有效期間',
        compute='_compute_is_valid_for_current_period',
        store=True,
        help='判斷此發票字軌是否在當前使用期間內'
    )
    
    # ========== 汎宇整合相關欄位 - 增強版 ==========
    use_fanyuu_numbering = fields.Boolean(
        string='使用汎宇取號',
        default=True,
        help='是否使用汎宇系統進行發票號碼管理'
    )
    
    last_fanyuu_number = fields.Char(
        string='汎宇最後號碼',
        help='從汎宇系統取得的最後一個發票號碼',
        readonly=True
    )
    
    fanyuu_sync_status = fields.Selection([
        ('not_sync', '未同步'),
        ('synced', '已同步'),
        ('error', '同步錯誤')
    ], string='汎宇同步狀態', default='not_sync')
    
    fanyuu_error_message = fields.Text(
        string='汎宇錯誤訊息',
        help='汎宇取號失敗時的錯誤訊息'
    )
    
    # 號碼池相關欄位
    fanyuu_pool_size = fields.Integer(
        string='號碼池大小',
        default=0,
        readonly=True,
        help='從汎宇取得的號碼總數量'
    )

    fanyuu_used_count = fields.Integer(
        string='已使用數量',
        default=0,
        readonly=True,
        help='已經使用的號碼數量'
    )

    fanyuu_remaining_count = fields.Integer(
        string='剩餘號碼數量',
        compute='_compute_fanyuu_remaining',
        store=True,
        help='號碼池中剩餘的號碼數量'
    )

    fanyuu_usage_percentage = fields.Float(
        string='使用率(%)',
        compute='_compute_fanyuu_remaining',
        store=True,
        help='號碼池使用率百分比'
    )

    current_fanyuu_index = fields.Integer(
        string='當前使用索引',
        default=0,
        readonly=True,
        help='目前在號碼池中的使用位置'
    )

    fanyuu_pool_header = fields.Char(
        string='號碼池字軌',
        readonly=True,
        help='當前號碼池的發票字軌'
    )

    fanyuu_pool_created_at = fields.Datetime(
        string='號碼池建立時間',
        readonly=True,
        help='號碼池建立的時間'
    )

    fanyuu_pool_last_used_at = fields.Datetime(
        string='最後取號時間',
        readonly=True,
        help='最後一次從號碼池取號的時間'
    )
    
    # 統計欄位
    fanyuu_success_count = fields.Integer(
        string='汎宇取號成功次數',
        default=0,
        readonly=True
    )
    
    fanyuu_fail_count = fields.Integer(
        string='汎宇取號失敗次數',
        default=0,
        readonly=True
    )
    
    last_fanyuu_request_time = fields.Datetime(
        string='最後汎宇請求時間',
        readonly=True
    )
    fanyuu_qr_code_as_key = fields.Char(
        string='汎宇QR Code AS Key',
        help='從A01取號時取得的QRCodeASKey',
        readonly=True
    )

    @api.depends('fanyuu_pool_size', 'fanyuu_used_count')
    def _compute_fanyuu_remaining(self):
        """計算剩餘號碼數量和使用率"""
        for record in self:
            if record.fanyuu_pool_size > 0:
                record.fanyuu_remaining_count = record.fanyuu_pool_size - record.fanyuu_used_count
                record.fanyuu_usage_percentage = (record.fanyuu_used_count / record.fanyuu_pool_size) * 100
            else:
                record.fanyuu_remaining_count = 0
                record.fanyuu_usage_percentage = 0

    @api.depends('invoice_title_id', 'section_code', 'use_fanyuu_numbering', 'fanyuu_remaining_count')
    def _compute_display_name(self):
        for record in self:
            if record.invoice_title_id and record.section_code:
                if record.use_fanyuu_numbering:
                    if record.fanyuu_pool_size > 0:
                        pool_info = f"(池:{record.fanyuu_remaining_count}/{record.fanyuu_pool_size})"
                        name = f"{record.invoice_title_id.name} ({record.section_code}) [汎宇{pool_info}]"
                    else:
                        name = f"{record.invoice_title_id.name} ({record.section_code}) [汎宇-未取號]"
                else:
                    name = f"{record.invoice_title_id.name} ({record.section_code}) [本地]"
                record.display_name = name
            else:
                record.display_name = record.section_code or ""

    @api.depends('number_from', 'last_used_number', 'section_code', 'status', 'use_fanyuu_numbering', 
                 'last_fanyuu_number', 'fanyuu_remaining_count', 'fanyuu_pool_size')
    def _compute_next_number(self):
        """計算下一個可用號碼 - 改進版"""
        for record in self:
            if record.use_fanyuu_numbering:
                # 使用汎宇取號模式
                if record.fanyuu_pool_size > 0:
                    if record.fanyuu_remaining_count > 0:
                        record.next_available_number = f"汎宇池取號 (剩餘: {record.fanyuu_remaining_count})"
                    else:
                        record.next_available_number = "汎宇池已空 (將取新區間)"
                elif record.last_fanyuu_number:
                    record.next_available_number = f"汎宇模式 (最後: {record.last_fanyuu_number})"
                else:
                    record.next_available_number = "汎宇模式 (將取新區間)"
            else:
                # 使用本地取號模式
                if not record.last_used_number:
                    record.next_available_number = f"{record.section_code}-{record.number_from}"
                else:
                    current_number = record.last_used_number.replace(record.section_code + '-', '')
                    next_num = str(int(current_number) + 1).zfill(8)
                    if int(next_num) > int(record.number_to):
                        record.next_available_number = "此組字軌號碼已用畢"
                        if record.status == 'in_use':
                            record.status = 'used_up'
                    else:
                        record.next_available_number = f"{record.section_code}-{next_num}"
    def handle_a01_response(self, response_data):
        """處理A01取號回應，儲存QRCodeASKey"""
        self.ensure_one()
        
        vals = {}
        
        index_data = response_data.get('INDEX', {})
        
        # 儲存QR Code AS Key - 這是生成QR Code的關鍵
        if index_data.get('QRCodeASKey'):
            vals['fanyuu_qr_code_as_key'] = index_data['QRCodeASKey']
            _logger.info(f"字軌 {self.section_code} 取得QRCodeASKey: {index_data['QRCodeASKey']}")
        
        # 更新字軌資訊
        if index_data.get('INVOICEHEADER'):
            vals['fanyuu_pool_header'] = index_data['INVOICEHEADER']
        
        if index_data.get('INVOICESTART') and index_data.get('INVOICEEND'):
            vals.update({
                'number_from': str(index_data['INVOICESTART']).zfill(8),
                'number_to': str(index_data['INVOICEEND']).zfill(8),
            })
        
        if vals:
            self.write(vals)
            _logger.info(f"已更新字軌 {self.section_code} 的A01回應資料")

    def get_next_number(self):
        self.ensure_one()
        from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI

        def _compose_number(index):
            num = int(self.number_from) + index
            return f"{self.fanyuu_pool_header}-{str(num).zfill(8)}"

        # 若號碼池存在且尚有可用號碼
        if self.fanyuu_pool_size > 0 and self.current_fanyuu_index < self.fanyuu_pool_size:
            invoice_number = _compose_number(self.current_fanyuu_index)

            self.write({
                'current_fanyuu_index': self.current_fanyuu_index + 1,
                'fanyuu_used_count': self.fanyuu_used_count + 1,
                'last_fanyuu_number': invoice_number,
                'fanyuu_pool_last_used_at': fields.Datetime.now(),
            })

            _logger.info(f"[號碼池] 取號成功: {invoice_number}")
            return invoice_number

        # 號碼池已用完 → 向汎宇取新段號碼
        _logger.warning(f"[號碼池] 已用完，字軌 {self.section_code} 開始向汎宇取新號碼段")

        result = FanyuuPosAPI(self.env).get_invoice_track_info(self.invoice_title_id.id)

        if not result['success']:
            raise ValidationError(f"字軌 {self.section_code} 取號失敗: {result['message']}")

        track_info = result['track_info']
        header = track_info['invoice_header']
        start = track_info['invoice_start']
        end = track_info['invoice_end']
        qr_code_as_key = track_info.get('qr_code_key', '')  # 取得 QRCodeASKey
        now = fields.Datetime.now()
        size = end - start + 1
        first_number = f"{header}-{str(start).zfill(8)}"

        # 更新時包含 QRCodeASKey
        self.write({
            'fanyuu_pool_header': header,
            'number_from': str(start).zfill(8),
            'number_to': str(end).zfill(8),
            'fanyuu_pool_size': size,
            'current_fanyuu_index': 1,
            'fanyuu_used_count': 1,
            'fanyuu_pool_created_at': now,
            'fanyuu_pool_last_used_at': now,
            'last_fanyuu_number': first_number,
            'fanyuu_sync_status': 'synced',
            'last_fanyuu_request_time': now,
            'fanyuu_qr_code_as_key': qr_code_as_key,  # 儲存 QRCodeASKey
        })

        _logger.info(f"[號碼池] 重新建立成功：{first_number} ～ {header}-{str(end).zfill(8)}，共 {size} 筆")
        _logger.info(f"[號碼池] QRCodeASKey: {qr_code_as_key}")

        return first_number

    def _get_number_locally(self):
        """本地取號邏輯（保持原有邏輯）"""
        next_number = self.next_available_number
        
        # 如果顯示的是汎宇模式訊息，需要重新計算本地號碼
        if "汎宇" in next_number:
            if not self.last_used_number:
                next_number = f"{self.section_code}-{self.number_from}"
            else:
                current_number = self.last_used_number.replace(self.section_code + '-', '')
                next_num = str(int(current_number) + 1).zfill(8)
                next_number = f"{self.section_code}-{next_num}"
        
        current_number = next_number.replace(self.section_code + '-', '')

        if int(current_number) > int(self.number_to):
            # 當前字軌用完，找下一組
            next_track = self.search([
                ('id', '!=', self.id),
                ('status', '=', 'unused'),
                ('date_from', '>=', self.date_from),
                ('invoice_title_id', '=', self.invoice_title_id.id),
            ], order='date_from asc', limit=1)

            if next_track:
                self.write({'status': 'used_up'})
                next_track.write({'status': 'in_use'})
                return next_track.get_next_number()
            else:
                self.write({'status': 'used_up'})
                raise ValidationError('所有發票字軌已用完')

        self.write({'last_used_number': next_number})
        return next_number

    def _handle_fanyuu_error(self, error_message):
        """處理汎宇錯誤"""
        self.write({
            'fanyuu_sync_status': 'error',
            'fanyuu_error_message': error_message,
            'fanyuu_fail_count': self.fanyuu_fail_count + 1,
            'last_fanyuu_request_time': fields.Datetime.now()
        })
        _logger.error(f"字軌 {self.section_code} 汎宇取號失敗: {error_message}")
        raise UserError(error_message)

    # ========== Y01 和 C01 功能方法 ==========
    
    def action_get_system_time(self):
        """取得汎宇系統時間 (Y01)"""
        self.ensure_one()
        
        if not self.use_fanyuu_numbering:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '⚠️ 功能限制',
                    'message': '此功能僅適用於汎宇取號模式',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            fanyuu_api = FanyuuPosAPI(self.env)
            result = fanyuu_api.get_system_time(self.invoice_title_id.id)
            
            if result['success']:
                system_time = result.get('system_time', '')
                local_time = fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                message = f"🕐 汎宇系統時間查詢成功！\n\n" \
                        f"🖥️ 汎宇系統時間: {system_time}\n" \
                        f"🏠 本地系統時間: {local_time}\n\n" \
                        f"📋 統編: {self.invoice_title_id.seller_tax_id}\n" \
                        f"🏢 公司: {self.invoice_title_id.name}"
                
                title = "🕐 系統時間查詢"
                msg_type = 'success'
                
                # 更新同步狀態
                self.write({
                    'fanyuu_sync_status': 'synced',
                    'fanyuu_error_message': False,
                    'last_fanyuu_request_time': fields.Datetime.now()
                })
                
            else:
                message = f"❌ 取得系統時間失敗：\n{result.get('message', '未知錯誤')}"
                title = "❌ 查詢失敗"
                msg_type = 'danger'
                
                # 更新錯誤狀態
                self.write({
                    'fanyuu_sync_status': 'error',
                    'fanyuu_error_message': result.get('message', '未知錯誤'),
                    'fanyuu_fail_count': self.fanyuu_fail_count + 1,
                    'last_fanyuu_request_time': fields.Datetime.now()
                })
                
        except Exception as e:
            message = f"❌ 系統時間查詢異常：\n{str(e)}"
            title = "❌ 查詢異常"
            msg_type = 'danger'
            
            # 更新錯誤狀態
            self.write({
                'fanyuu_sync_status': 'error',
                'fanyuu_error_message': str(e),
                'fanyuu_fail_count': self.fanyuu_fail_count + 1,
                'last_fanyuu_request_time': fields.Datetime.now()
            })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': msg_type,
                'sticky': True,
            }
        }

    def action_get_next_period_track(self):
        """取得下期發票字軌資訊 (C01)"""
        self.ensure_one()
        
        if not self.use_fanyuu_numbering:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '⚠️ 功能限制',
                    'message': '此功能僅適用於汎宇取號模式',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            fanyuu_api = FanyuuPosAPI(self.env)
            result = fanyuu_api.get_next_period_track_info(self.invoice_title_id.id)
            
            if result['success'] and result.get('track_info'):
                track_info = result['track_info']
                
                # 計算下期號碼數量
                total_numbers = track_info['invoice_end'] - track_info['invoice_start'] + 1
                
                message = f"📋 下期字軌資訊查詢成功！\n\n" \
                        f"📅 稅額期間: {track_info.get('tax_month', 'N/A')}\n" \
                        f"🎯 發票字軌: {track_info.get('invoice_header', 'N/A')}\n" \
                        f"🔢 起始號碼: {track_info.get('invoice_start', 'N/A'):08d}\n" \
                        f"🔢 結束號碼: {track_info.get('invoice_end', 'N/A'):08d}\n" \
                        f"📦 總計號碼: {total_numbers} 個\n" \
                        f"🔐 QR金鑰: {track_info.get('qr_code_key', 'N/A')}\n\n" \
                        f"📋 統編: {result.get('seller_tax_id', 'N/A')}\n" \
                        f"🏢 公司: {result.get('company_name', 'N/A')}"
                
                title = "📋 下期字軌資訊"
                msg_type = 'success'
                
                # 更新同步狀態
                self.write({
                    'fanyuu_sync_status': 'synced',
                    'fanyuu_error_message': False,
                    'last_fanyuu_request_time': fields.Datetime.now()
                })
                
            else:
                message = f"❌ 取得下期字軌失敗：\n{result.get('message', '未知錯誤')}"
                title = "❌ 查詢失敗"
                msg_type = 'danger'
                
                # 更新錯誤狀態
                self.write({
                    'fanyuu_sync_status': 'error',
                    'fanyuu_error_message': result.get('message', '未知錯誤'),
                    'fanyuu_fail_count': self.fanyuu_fail_count + 1,
                    'last_fanyuu_request_time': fields.Datetime.now()
                })
                
        except Exception as e:
            message = f"❌ 下期字軌查詢異常：\n{str(e)}"
            title = "❌ 查詢異常"
            msg_type = 'danger'
            
            # 更新錯誤狀態
            self.write({
                'fanyuu_sync_status': 'error',
                'fanyuu_error_message': str(e),
                'fanyuu_fail_count': self.fanyuu_fail_count + 1,
                'last_fanyuu_request_time': fields.Datetime.now()
            })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': msg_type,
                'sticky': True,
            }
        }
    
    def action_debug_number_pool(self):
        """除錯號碼池狀態 - 增強版"""
        self.ensure_one()
        
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            seller_id = self.invoice_title_id.seller_tax_id
            pool_status = FanyuuPosAPI.get_pool_status(seller_id)
            
            if pool_status['exists']:
                health_icon = {
                    'healthy': '🟢',
                    'warning': '🟡', 
                    'empty': '🔴'
                }.get(pool_status.get('pool_health', 'unknown'), '⚪')
                
                message = f"📊 號碼池狀態報告：\n\n" \
                        f" 統編: {seller_id}\n" \
                        f" 總號碼數: {pool_status['total_numbers']}\n" \
                        f" 已使用: {pool_status['used_numbers']}\n" \
                        f" 剩餘: {pool_status['remaining_numbers']}\n" \
                        f" 使用率: {pool_status['usage_percentage']}%\n" \
                        f"{health_icon} 池狀態: {pool_status.get('pool_health', 'unknown')}\n" \
                        f" 當前號碼: {pool_status['current_number']}\n" \
                        f" 建立時間: {pool_status['created_at']}\n" \
                        f" 最後使用: {pool_status['last_used_at']}\n\n" \
                        f" 號碼範圍: {pool_status['first_number']} ~ {pool_status['last_number']}\n" \
                        f" 字軌: {pool_status['invoice_header']}"
                title = " 號碼池狀態"
                msg_type = 'success'
            else:
                message = f" 統編 {seller_id} 尚未建立號碼池\n\n下次取號時將自動向汎宇取得新的號碼區間"
                title = " 號碼池狀態"  
                msg_type = 'warning'
                
        except Exception as e:
            message = f" 檢查號碼池失敗: {str(e)}"
            title = " 檢查失敗"
            msg_type = 'danger'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': msg_type,
                'sticky': True,
            }
        }

    def action_force_refresh_pool(self):
        """強制刷新號碼池 - 取得新的50個號碼"""
        self.ensure_one()
        
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            seller_id = self.invoice_title_id.seller_tax_id
            
            # 先獲取當前狀態
            old_status = FanyuuPosAPI.get_pool_status(seller_id)
            
            # 強制刷新號碼池
            result = FanyuuPosAPI.force_refresh_pool(
                self.env, 
                seller_id, 
                self.invoice_title_id.id
            )
            
            if result['success']:
                # 重置本地狀態
                self.write({
                    'fanyuu_sync_status': 'synced',
                    'fanyuu_error_message': False,
                    'fanyuu_pool_size': result['pool_info']['total_numbers'],
                    'fanyuu_used_count': 0,
                    'current_fanyuu_index': 0,
                    'fanyuu_pool_header': result['pool_info']['invoice_header'],
                    'fanyuu_pool_created_at': fields.Datetime.now(),
                    'fanyuu_pool_last_used_at': False,
                    'last_fanyuu_number': False
                })
                
                message = f" 強制刷新成功！\n\n" \
                        f" 新號碼池: {result['pool_info']['total_numbers']} 個號碼\n" \
                        f" 字軌: {result['pool_info']['invoice_header']}\n" \
                        f" 範圍: {result['pool_info']['first_number']} ~ {result['pool_info']['last_number']}"
                        
                if old_status['exists']:
                    message += f"\n\n 已捨棄舊池剩餘 {old_status['remaining_numbers']} 個號碼"
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': ' 刷新成功',
                        'message': message,
                        'type': 'success',
                        'sticky': True,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': ' 刷新失敗',
                        'message': f'強制刷新號碼池失敗:\n{result["message"]}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': ' 刷新異常',
                    'message': f'強制刷新號碼池異常: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_clear_number_pool(self):
        """清空號碼池 - 增強版"""
        self.ensure_one()
        
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            seller_id = self.invoice_title_id.seller_tax_id
            
            # 獲取清空前的狀態
            old_status = FanyuuPosAPI.get_pool_status(seller_id)
            
            # 清空號碼池
            success = FanyuuPosAPI.clear_pool(seller_id)
            
            if success:
                # 重置本地狀態
                self.write({
                    'fanyuu_sync_status': 'not_sync',
                    'fanyuu_error_message': False,
                    'last_fanyuu_number': False,
                    'fanyuu_pool_size': 0,
                    'fanyuu_used_count': 0,
                    'current_fanyuu_index': 0,
                    'fanyuu_pool_header': False,
                    'fanyuu_pool_created_at': False,
                    'fanyuu_pool_last_used_at': False
                })
                
                if old_status['exists']:
                    message = f' 已清空統編 {seller_id} 的號碼池\n\n' \
                            f' 已捨棄 {old_status["remaining_numbers"]} 個剩餘號碼\n' \
                            f' 使用率: {old_status["usage_percentage"]}%\n\n' \
                            f'下次取號將重新向汎宇取得新的號碼區間'
                else:
                    message = f'統編 {seller_id} 原本就沒有號碼池'
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': ' 清空完成',
                        'message': message,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': ' 清空結果',
                        'message': f'統編 {seller_id} 的號碼池不存在或已清空',
                        'type': 'warning',
                        'sticky': False,
                    }
                }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': ' 清空失敗',
                    'message': f'清空號碼池失敗: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_view_all_pools_status(self):
        """查看所有號碼池狀態"""
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            all_pools = FanyuuPosAPI.get_all_pools_status()
            
            if not all_pools:
                message = "📭 目前沒有任何號碼池"
                title = "號碼池總覽"
                msg_type = 'info'
            else:
                message_parts = [" 所有號碼池狀態總覽：\n"]
                
                for i, pool in enumerate(all_pools, 1):
                    health_icon = {
                        'healthy': '🟢',
                        'warning': '🟡',
                        'empty': '🔴'
                    }.get(pool.get('pool_health', 'unknown'), '⚪')
                    
                    message_parts.append(
                        f"{i}. 統編: {pool['seller_id']}\n"
                        f"   {health_icon} {pool['used_numbers']}/{pool['total_numbers']} "
                        f"({pool['usage_percentage']}%) - {pool['invoice_header']}\n"
                    )
                
                message = '\n'.join(message_parts)
                title = f"號碼池總覽 ({len(all_pools)} 個池)"
                msg_type = 'success'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': title,
                    'message': message,
                    'type': msg_type,
                    'sticky': True,
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '❌ 查看失敗',
                    'message': f'查看號碼池狀態失敗: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_reset_fanyuu_status(self):
        """重置汎宇同步狀態"""
        self.write({
            'fanyuu_sync_status': 'not_sync',
            'fanyuu_error_message': False,
            'last_fanyuu_number': False,
            'fanyuu_success_count': 0,
            'fanyuu_fail_count': 0,
            'last_fanyuu_request_time': False,
            'fanyuu_pool_size': 0,
            'fanyuu_used_count': 0,
            'current_fanyuu_index': 0,
            'fanyuu_pool_header': False,
            'fanyuu_pool_created_at': False,
            'fanyuu_pool_last_used_at': False
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '狀態重置',
                'message': '已重置汎宇同步狀態和號碼池資訊',
                'type': 'info',
                'sticky': False,
            }
        }
  
    @api.depends('date_from', 'date_to')
    def _compute_period(self):
        for record in self:
            if record.date_from and record.date_to:
                from_date = record.date_from
                # 轉換為民國年
                roc_year = from_date.year - 1911
                # 格式化為 "民國YYY年MM-MM月"
                start_month = from_date.month
                end_month = start_month + 1 if start_month % 2 == 1 else start_month
                record.invoice_period = f"{roc_year}年{str(start_month).zfill(2)}-{str(end_month).zfill(2)}月"
            else:
                record.invoice_period = False

    @api.depends('date_from', 'date_to')
    def _compute_is_valid_for_current_period(self):
        """判斷發票字軌是否在當前有效期間內"""
        today = fields.Date.today()
        current_month = today.month
        current_year = today.year
        
        for record in self:
            # 檢查日期範圍是否有效
            if not record.date_from or not record.date_to:
                record.is_valid_for_current_period = False
                continue
                
            # 判斷是否為當前期間
            # 發票週期是兩個月，檢查是否在當前月份或下一個月
            # 根據奇數月開始的規則，確定當前發票期間
            period_start_month = current_month
            if current_month % 2 == 0:  # 如果是偶數月，則期間從上個月開始
                period_start_month = current_month - 1
            
            # 檢查發票字軌的起始月份是否符合當前發票期間
            track_month = record.date_from.month
            track_year = record.date_from.year
            
            # 檢查年份和月份是否符合當前期間
            is_current_period = (
                track_year == current_year and 
                track_month == period_start_month
            )
            
            # 如果不是當前期間，但狀態是"使用中"，也視為有效
            # 這確保已啟用但不是當前期間的字軌仍能顯示
            is_active_track = record.status == 'in_use'
            
            record.is_valid_for_current_period = is_current_period or is_active_track

    def name_get(self):
        result = []
        for record in self:
            name = record.display_name
            result.append((record.id, name))
        return result
    
    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None, order=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', ('display_name', operator, name), 
                          ('invoice_title_id.name', operator, name)]
        return self._search(domain + args, limit=limit, access_rights_uid=name_get_uid, order=order)

    # 添加一個方法來獲取唯一的使用中發票字軌
    @api.model
    def get_unique_active_tracks(self):
        """獲取每個發票抬頭下唯一的使用中字軌"""
        # 查詢所有使用中的字軌
        active_tracks = self.search([
            ('status', '=', 'in_use'),
            ('is_valid_for_current_period', '=', True)
        ])
        
        # 使用字典來確保每個發票抬頭只有一個字軌
        unique_tracks = {}
        for track in active_tracks:
            title_id = track.invoice_title_id.id
            # 如果該抬頭還沒有字軌，或者當前字軌更新，則更新
            if title_id not in unique_tracks or track.date_from > unique_tracks[title_id].date_from:
                unique_tracks[title_id] = track
        
        # 返回唯一的字軌列表
        return list(unique_tracks.values())

    @api.model
    def create(self, vals):
        """創建時檢查同一發票抬頭下是否已有啟用的字軌"""
        if vals.get('status') == 'in_use':
            active_track = self.search([
                ('status', '=', 'in_use'),
                ('invoice_title_id', '=', vals.get('invoice_title_id'))
            ])
            if active_track:
                raise ValidationError('此發票抬頭下已有啟用中的發票字軌，請先停用現有字軌')
        return super().create(vals)

    def write(self, vals):
        """修改時檢查啟用狀態"""
        if vals.get('status') == 'in_use':
            for record in self:
                invoice_title_id = vals.get('invoice_title_id', record.invoice_title_id.id)
                active_track = self.search([
                    ('status', '=', 'in_use'), 
                    ('id', '!=', record.id),
                    ('invoice_title_id', '=', invoice_title_id)
                ])
                if active_track:
                    raise ValidationError('此發票抬頭下已有啟用中的發票字軌，請先停用現有字軌')
        
        """寫入時同步狀態欄位"""
        # 如果修改了 status，同步更新舊欄位
        if 'status' in vals:
            if vals['status'] == 'in_use':
                vals.update({'is_active': True, 'is_used': False})
            elif vals['status'] == 'used_up':
                vals.update({'is_active': False, 'is_used': True})
            elif vals['status'] == 'unused':
                vals.update({'is_active': False, 'is_used': False})
        
        # 如果修改了舊欄位，同步更新 status
        elif 'is_active' in vals or 'is_used' in vals:
            is_active = vals.get('is_active', self.is_active)
            is_used = vals.get('is_used', self.is_used)
            
            if is_used:
                vals['status'] = 'used_up'
            elif is_active:
                vals['status'] = 'in_use'
            else:
                vals['status'] = 'unused'
        
        return super(InvoiceTrack, self).write(vals)

    @api.constrains('number_from', 'number_to')
    def _check_numbers(self):
        for record in self:
            if record.number_from and record.number_to:
                if int(record.number_from) > int(record.number_to):
                    raise ValidationError('結束號碼必須大於起始號碼')
                
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_from and record.date_to:
                if record.date_from > record.date_to:
                    raise ValidationError('結束日期必須大於起始日期')
                # 檢查是否為兩個月期間
                from_date = record.date_from
                to_date = record.date_to
                if (to_date.year - from_date.year) * 12 + to_date.month - from_date.month != 1:
                    raise ValidationError('發票週期必須為兩個月')
                # 檢查是否從奇數月份開始
                if from_date.month % 2 == 0:
                    raise ValidationError('發票週期必須從奇數月份開始')

    def export_csv(self):
        """匯出已用畢但未使用過的發票號碼為財政部指定的 CSV 格式"""
        if not self:
            raise ValidationError('請至少選擇一筆記錄進行匯出')
        
        # 過濾，只保留已用畢的發票字軌
        used_up_tracks = self.filtered(lambda r: r.status == 'used_up')
        
        if not used_up_tracks:
            raise ValidationError('沒有已用畢的發票字軌可匯出')

        # 按照日期排序（先按年份，再按月份）
        sorted_tracks = used_up_tracks.sorted(key=lambda r: (r.date_from.year, r.date_from.month))

        # 創建 CSV 文件（不使用標頭行，因為財政部格式不需要）
        import base64
        import csv
        import io
        
        csv_file = io.StringIO()
        writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        
        # 依序匯出每筆發票字軌紀錄
        row_num = 1
        for track in sorted_tracks:
            # 檢查是否有未使用的號碼
            if track.last_used_number:
                # 獲取最後使用的號碼
                last_num = track.last_used_number.replace(f"{track.section_code}-", "")
                last_num_int = int(last_num)
                
                # 檢查是否有未使用的區間
                if last_num_int < int(track.number_to):
                    # 有未使用的區間
                    start_number = str(last_num_int + 1).zfill(8)
                    end_number = track.number_to.zfill(8)
                else:
                    # 沒有未使用的區間，跳過此記錄
                    continue
            else:
                # 如果沒有最後使用號碼，表示整個區間都未使用
                start_number = track.number_from.zfill(8)
                end_number = track.number_to.zfill(8)
            
            # 處理民國年月 (格式: 10108)
            roc_year = track.date_from.year - 1911 if track.date_from else 0
            month = track.date_from.month if track.date_from else 0
            period = f"{roc_year}{str(month).zfill(2)}"
            
            # 序號 (5 位數，從 00001 開始)
            serial_number = str(row_num).zfill(5)
            
            # 統一編號 (固定 8 位數)
            tax_id = track.invoice_title_id.seller_tax_id or '00000000'
            
            # 發票類別 (預設為 07: 一般稅額計算電子發票)
            invoice_category = track.invoice_category or '07'
            
            # 依照財政部格式建立 CSV 行
            # 格式: 序號,統一編號,所屬年月,字軌,空白發票起號,空白發票迄號,發票類別
            csv_row = [
                serial_number,
                tax_id,
                period,
                track.section_code or '',
                start_number,
                end_number,
                invoice_category
            ]
            
            writer.writerow(csv_row)
            row_num += 1

        # 如果沒有任何記錄被寫入，提示用戶
        if row_num == 1:
            raise ValidationError('沒有已用畢但尚有未使用號碼的發票字軌')

        # 生成附件檔案 (使用 utf-8 編碼，無 BOM)
        csv_content = csv_file.getvalue().encode('utf-8')
        filename = f'空白未使用字軌_{fields.Date.today()}.csv'

        # 創建附件記錄
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(csv_content),
            'res_model': 'invoice.track',
            'res_id': self[0].id if self else False,
            'type': 'binary',
        })

        # 返回下載動作
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    @api.onchange('status')
    def _onchange_status(self):
        """狀態變更時同步更新 is_active 和 is_used"""
        if self.status == 'in_use':
            self.is_active = True
            self.is_used = False
        elif self.status == 'used_up':
            self.is_active = False
            self.is_used = True
        else:  # unused
            self.is_active = False
            self.is_used = False

    @api.onchange('is_active', 'is_used')
    def _onchange_legacy_status(self):
        """舊狀態欄位變更時同步更新 status"""
        if self.is_used:
            self.status = 'used_up'
        elif self.is_active:
            self.status = 'in_use'
        else:
            self.status = 'unused'


class PosStyleReceiptReport(models.AbstractModel):
    _name = 'report.jasmine.pos_style_receipt'
    _description = 'POS Style Receipt Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['account.move'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'account.move',
            'docs': docs,
            'data': data,
        }
    

class AccountInvoiceReport(models.Model):
    _inherit = 'account.invoice.report'

    einvoice_number = fields.Char(string='發票號碼', readonly=True)
    einvoice_count = fields.Integer(string='發票數量', compute='_compute_einvoice_count')

    def _select(self):
        return super(AccountInvoiceReport, self)._select() + ", move.einvoice_number as einvoice_number"

    def _group_by(self):
        return super(AccountInvoiceReport, self)._group_by() + ", move.einvoice_number"

    @api.depends('einvoice_number')
    def _compute_einvoice_count(self):
        for record in self:
            record.einvoice_count = 1 if record.einvoice_number else 0
    