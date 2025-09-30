# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)

class InvoiceCancellation(models.Model):
    _name = 'invoice.cancellation'
    _description = '電子發票作廢'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string='作廢單號', required=True, copy=False, readonly=True, default='New')
    invoice_id = fields.Many2one('invoice.information', string='電子發票', required=True, 
                           domain="[('operation_type', 'not in', ['REJ', 'CAN', 'CAN_ALW'])]", 
                           ondelete='restrict')
    invoice_number = fields.Char(string='發票號碼', related='invoice_id.invoice_number', store=True, readonly=True)
    invoice_date = fields.Datetime(string='發票日期', related='invoice_id.invoice_date', store=True, readonly=True)
    
    cancellation_date = fields.Datetime(string='作廢日期', default=fields.Datetime.now)
    cancellation_reason = fields.Selection([
        ('wrong_info', '資訊錯誤'),
        ('return_all', '全部退回'),
        ('void_transaction', '交易取消'),
        ('wrong_invoice', '誤開發票'),
        ('other', '其他原因')
    ], string='作廢原因', required=True)
    reason_detail = fields.Text(string='作廢說明', required=True)
    
    state = fields.Selection([
        ('draft', '草稿'),
        ('done', '已作廢'),
    ], string='狀態', default='draft', tracking=True)
    
    # 汎宇上傳狀態追蹤
    fanyuu_upload_status = fields.Selection([
        ('pending', '待上傳'),
        ('success', '上傳成功'),
        ('failed', '上傳失敗')
    ], string='汎宇上傳狀態', default='pending', readonly=True)
    fanyuu_upload_message = fields.Text(string='汎宇上傳訊息', readonly=True)
    fanyuu_upload_time = fields.Datetime(string='汎宇上傳時間', readonly=True)
    
    def action_confirm(self):
        self.ensure_one()
        
        if self.state != 'draft':
            raise UserError('只有草稿狀態的作廢單可以確認！')
        
        if not self.invoice_id:
            raise UserError('必須選擇要作廢的發票！')
        
        if self.invoice_id.operation_type in ['REJ', 'CAN', 'CAN_ALW']:
            raise UserError('此發票已被作廢或退回，不能再次作廢！')
        
        # 作廢發票
        try:
            # 判斷是否為折讓單的邏輯修正
            # 根據 operation_type 判斷作廢類型
            if self.invoice_id.operation_type == 'CRE_ALW':
                # 這是折讓證明單，使用折讓作廢
                operation_type = 'CAN_ALW'
            else:
                # 這是一般發票，使用一般作廢
                operation_type = 'CAN'
            
            # 更新發票狀態
            self.invoice_id.with_context(force_einvoice_edit=True).write({
                'operation_type': operation_type,
                'remark': f"{self.invoice_id.remark or ''}\n[作廢] {self.cancellation_date.strftime('%Y-%m-%d %H:%M')}: {self.get_cancellation_reason_display()} - {self.reason_detail}"
            })
            
            # 上傳到汎宇系統
            self._send_cancellation_to_fanyuu()
            
            # 更新狀態
            self.write({
                'state': 'done'
            })
            
            # 返回表單視圖
            return {
                'type': 'ir.actions.act_window',
                'name': '作廢單',
                'res_model': 'invoice.cancellation',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
                'flags': {'mode': 'readonly'},
            }
        
        except Exception as e:
            _logger.error(f"作廢單確認失敗: {str(e)}", exc_info=True)
            raise UserError(f'作廢單確認失敗: {str(e)}')
    
    def _send_cancellation_to_fanyuu(self):
        """發送作廢資訊到汎宇系統"""
        try:
            from odoo.addons.jasmine.services.fanyuu_pos_api import FanyuuPosAPI
            
            api = FanyuuPosAPI(self.env)
            
            # 準備作廢資料
            invoice_date = self.invoice_id.invoice_date.strftime('%Y-%m-%d') if self.invoice_id.invoice_date else ''
            buyer_id = self.invoice_id.buyer_tax_id or "0000000000"
            
            # 取得發票抬頭ID
            invoice_title_id = None
            if hasattr(self.invoice_id, 'invoice_track_id') and self.invoice_id.invoice_track_id:
                if hasattr(self.invoice_id.invoice_track_id, 'invoice_title_id'):
                    invoice_title_id = self.invoice_id.invoice_track_id.invoice_title_id.id
            
            _logger.info(f"準備上傳作廢資訊到汎宇: 發票號碼={self.invoice_id.invoice_number}, 作廢類型={self.invoice_id.operation_type}")
            
            if self.invoice_id.operation_type == 'CAN_ALW':
                # 作廢折讓證明單 (D0501)
                _logger.info(f"使用 D0501 作廢折讓證明單")
                result = api.cancel_allowance(
                    allowance_number=self.invoice_id.invoice_number,
                    allowance_date=invoice_date,
                    buyer_id=buyer_id,
                    reason=self.reason_detail,
                    invoice_title_id=invoice_title_id
                )
            else:
                # 作廢一般發票 (C0501)
                _logger.info(f"使用 C0501 作廢一般發票")
                result = api.cancel_invoice(
                    invoice_number=self.invoice_id.invoice_number,
                    invoice_date=invoice_date,
                    buyer_id=buyer_id,
                    reason=self.reason_detail,
                    invoice_title_id=invoice_title_id
                )
            
            _logger.info(f"汎宇回應結果: {result}")
            
            if result.get('success'):
                # 更新作廢單的汎宇狀態
                self.write({
                    'fanyuu_upload_status': 'success',
                    'fanyuu_upload_message': result.get('message', '作廢成功'),
                    'fanyuu_upload_time': fields.Datetime.now()
                })
                
                # 更新發票的汎宇狀態
                self.invoice_id.with_context(force_einvoice_edit=True).write({
                    'fanyuu_status': 'success',
                    'fanyuu_message': result.get('message', '作廢成功'),
                    'fanyuu_response_time': fields.Datetime.now()
                })
                
                # 記錄成功日誌
                self.message_post(
                    body=f"已成功上傳作廢資訊到汎宇系統<br/>"
                         f"發票號碼: {self.invoice_id.invoice_number}<br/>"
                         f"作廢類型: {'折讓證明單作廢' if self.invoice_id.operation_type == 'CAN_ALW' else '一般發票作廢'}<br/>"
                         f"回應訊息: {result.get('message', '')}",
                    message_type='notification'
                )
                
                _logger.info(f"作廢資訊已成功上傳到汎宇系統: {self.invoice_id.invoice_number}")
                
            else:
                # 上傳失敗
                error_message = result.get('message', '未知錯誤')
                self.write({
                    'fanyuu_upload_status': 'failed',
                    'fanyuu_upload_message': f"上傳失敗: {error_message}",
                    'fanyuu_upload_time': fields.Datetime.now()
                })
                
                # 更新發票的汎宇狀態
                self.invoice_id.with_context(force_einvoice_edit=True).write({
                    'fanyuu_status': 'failed',
                    'fanyuu_message': f"作廢上傳失敗: {error_message}",
                    'fanyuu_response_time': fields.Datetime.now()
                })
                
                _logger.error(f"汎宇系統回應錯誤: {error_message}")
                raise UserError(f"汎宇系統回應錯誤: {error_message}")
                
        except Exception as e:
            error_msg = f"上傳作廢資訊到汎宇失敗: {str(e)}"
            _logger.error(error_msg, exc_info=True)
            
            # 更新作廢單狀態為失敗
            self.write({
                'fanyuu_upload_status': 'failed',
                'fanyuu_upload_message': error_msg,
                'fanyuu_upload_time': fields.Datetime.now()
            })
            
            # 更新發票的汎宇狀態為失敗
            if self.invoice_id:
                self.invoice_id.with_context(force_einvoice_edit=True).write({
                    'fanyuu_status': 'failed',
                    'fanyuu_message': error_msg,
                    'fanyuu_response_time': fields.Datetime.now()
                })
            
            # 記錄失敗但不中斷流程
            self.message_post(
                body=f"上傳作廢資訊到汎宇系統失敗<br/>錯誤訊息: {str(e)}",
                message_type='notification'
            )
            
            # 這裡可以選擇是否要拋出異常中斷流程
            # 如果不想因為汎宇上傳失敗而中斷作廢流程，可以註解掉下面這行
            raise UserError(error_msg)
    
    def action_retry_fanyuu_upload(self):
        """重新上傳到汎宇系統"""
        self.ensure_one()
        
        if self.state != 'done':
            raise UserError('只有已確認的作廢單才能重新上傳！')
        
        try:
            self._send_cancellation_to_fanyuu()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '重新上傳成功',
                    'message': '作廢資訊已成功重新上傳到汎宇系統',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(f"重新上傳失敗: {str(e)}")
    
    def get_cancellation_reason_display(self):
        """獲取作廢原因的顯示文字"""
        selection = dict(self._fields['cancellation_reason'].selection)
        return selection.get(self.cancellation_reason, '')
    
    def action_cancel(self):
        """取消作廢單"""
        self.ensure_one()
        
        if self.state == 'done':
            raise UserError('已確認的作廢單不能取消！')
            
        self.write({'state': 'cancel'})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('invoice.cancellation')
        return super(InvoiceCancellation, self).create(vals_list)