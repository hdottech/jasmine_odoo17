# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)

class InvoiceCancellation(models.Model):
    _name = 'invoice.cancellation'
    _description = '電子發票作廢'
    _inherit = ['mail.thread']
    
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
        ('cancel', '已取消')
    ], string='狀態', default='draft', tracking=True)
    
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
            # 更新發票狀態為作廢
            operation_type = 'CAN'
            if self.invoice_id.is_allowance:
                operation_type = 'CAN_ALW'  # 對折讓單的作廢
            
            self.invoice_id.with_context(force_einvoice_edit=True).write({
                'operation_type': operation_type,
                'remark': f"{self.invoice_id.remark or ''}\n[作廢] {self.cancellation_date.strftime('%Y-%m-%d %H:%M')}: {self.get_cancellation_reason_display()} - {self.reason_detail}"
            })
            
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