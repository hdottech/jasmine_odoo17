# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)

class InvoiceReturn(models.Model):
    _name = 'invoice.return'
    _description = '銷貨/進貨退回'
    _inherit = ['mail.thread']
    
    name = fields.Char(string='退回單號', required=True, copy=False, readonly=True, default='New')
    original_invoice_id = fields.Many2one('invoice.information', string='原始電子發票', required=True, 
                                         domain="[('operation_type', '=', '')]",  # 改為只選擇開立發票
                                         ondelete='restrict')
    original_invoice_number = fields.Char(string='原始發票號碼', related='original_invoice_id.invoice_number', store=True, readonly=True)
    original_invoice_date = fields.Datetime(string='原始發票日期', related='original_invoice_id.invoice_date', store=True, readonly=True)
    
    return_type = fields.Selection([
        ('sales_return', '銷貨退回'),
        ('purchase_return', '進貨退出')
    ], string='退回類型', required=True, default='sales_return')
    
    return_date = fields.Datetime(string='退回日期', default=fields.Datetime.now)
    return_reason = fields.Selection([
        ('quality', '品質問題'),
        ('damage', '運送損壞'),
        ('wrong_item', '錯誤商品'),
        ('other', '其他原因')
    ], string='退回原因', required=True)
    reason_detail = fields.Text(string='原因說明')
    
    tax_type = fields.Selection(related='original_invoice_id.tax_type', string='課稅別', store=True, readonly=True)
    tax_rate = fields.Float(related='original_invoice_id.tax_rate', string='稅率', store=True, readonly=True)
    buyer_tax_id = fields.Char(string='買方統編', related='original_invoice_id.buyer_tax_id', store=True, readonly=True)
    seller_tax_id = fields.Char(string='賣方統編', related='original_invoice_id.seller_tax_id', store=True, readonly=True)
    
    sales_amount = fields.Float(string='銷售額', compute='_compute_amounts', store=True)
    tax_amount = fields.Float(string='稅額', compute='_compute_amounts', store=True)
    total_amount = fields.Float(string='總計金額', compute='_compute_amounts', store=True)
    
    state = fields.Selection([
        ('draft', '草稿'),
        ('done', '已確認退回'),
        ('cancel', '已取消')
    ], string='狀態', default='draft', tracking=True)
    
    return_line_ids = fields.One2many('invoice.return.line', 'return_id', string='退回明細')
    
    @api.depends('return_line_ids.return_amount', 'tax_type', 'tax_rate')
    def _compute_amounts(self):
        for record in self:
            # 根據明細行計算銷售額
            record.sales_amount = sum(line.return_amount for line in record.return_line_ids)
            
            # 根據稅別計算稅額和總額
            if record.tax_type == '1':  # 應稅
                record.tax_amount = round(record.sales_amount * (record.tax_rate / 100), 0)
            else:
                record.tax_amount = 0
                
            record.total_amount = record.sales_amount + record.tax_amount
    
    @api.onchange('original_invoice_id', 'return_type')
    def _onchange_original_invoice(self):
        if self.original_invoice_id:
            # 檢查發票狀態
            if self.original_invoice_id.operation_type != '':
                raise UserError('只能對未處理的原始發票建立退回單！')
            
            # 清空現有明細行
            self.return_line_ids = [(5, 0, 0)]
            
            # 載入發票明細行
            lines = []
            for line in self.original_invoice_id.invoice_line_ids:
                # 檢查此明細是否已有退回記錄
                existing_returns = self.env['invoice.return.line'].search([
                    ('original_invoice_line_product', '=', line.product_name),
                    ('return_id.original_invoice_id', '=', self.original_invoice_id.id),
                    ('return_id.state', '=', 'done')
                ])
                
                already_returned = sum(r.return_quantity for r in existing_returns)
                remaining_qty = line.quantity - already_returned
                
                if remaining_qty > 0:
                    lines.append((0, 0, {
                        'original_invoice_line_product': line.product_name,
                        'original_quantity': line.quantity,
                        'already_returned': already_returned,
                        'remaining_quantity': remaining_qty,
                        'unit_price': line.unit_price,
                        'unit': line.unit,
                        'return_quantity': 0,
                        'return_amount': 0,
                    }))
            
            if lines:
                self.return_line_ids = lines
    
    def action_confirm(self):
        self.ensure_one()
        
        if self.state != 'draft':
            raise UserError('只有草稿狀態的退回單可以確認！')
        
        # 檢查原始發票狀態
        if self.original_invoice_id.operation_type != '':
            raise UserError('原始發票已被處理，無法建立退回單！')
        
        # 檢查是否有明細
        if not self.return_line_ids:
            raise UserError('請至少添加一行退回明細！')
            
        # 檢查是否有數量要退回
        if not any(line.return_quantity > 0 for line in self.return_line_ids):
            raise UserError('至少需要一行明細有退回數量！')
        
        try:
            # 整理退回明細信息
            return_details = []
            for line in self.return_line_ids:
                if line.return_quantity > 0:
                    return_details.append(
                        f"{line.original_invoice_line_product}: {line.return_quantity} {line.unit}, 金額: {line.return_amount}"
                    )
            
            return_detail_text = "\n    - ".join([""] + return_details) if return_details else ""
            
            # 在原始發票上更新操作類型和備註
            self.original_invoice_id.with_context(force_einvoice_edit=True).write({
                'operation_type': 'REJ',  # 退回發票
                'remark': f"{self.original_invoice_id.remark or ''}\n[{self.return_type}] {self.return_date.strftime('%Y-%m-%d %H:%M')}: "
                        f"{self.get_return_reason_display()} - {self.reason_detail or ''}"
                        f"\n退回金額: {int(self.total_amount)}{return_detail_text}"
            })
            
            # 更新退回單狀態
            self.write({
                'state': 'done'
            })
            
            # 記錄日誌
            _logger.info(f"退回單 {self.name} 已確認，原始發票 {self.original_invoice_number} 狀態已更新為退回")
            
            # 返回表單視圖
            return {
                'type': 'ir.actions.act_window',
                'name': '退回單',
                'res_model': 'invoice.return',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
                'flags': {'mode': 'readonly'},
            }
            
        except Exception as e:
            _logger.error(f"退回單確認失敗: {str(e)}", exc_info=True)
            raise UserError(f'退回單確認失敗: {str(e)}')
    
    def get_return_reason_display(self):
        """獲取退回原因的顯示文字"""
        selection = dict(self._fields['return_reason'].selection)
        return selection.get(self.return_reason, '')
    
    def action_cancel(self):
        """取消退回單"""
        self.ensure_one()
        
        if self.state == 'done':
            raise UserError('已確認的退回單不能取消！')
            
        self.write({'state': 'cancel'})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                # 根據退回類型生成不同前綴
                prefix = 'SR-' if vals.get('return_type') == 'sales_return' else 'PR-'
                vals['name'] = prefix + self.env['ir.sequence'].next_by_code('invoice.return')
        return super(InvoiceReturn, self).create(vals_list)


class InvoiceReturnLine(models.Model):
    _name = 'invoice.return.line'
    _description = '退回明細行'
    
    return_id = fields.Many2one('invoice.return', string='退回單', required=True, ondelete='cascade')
    original_invoice_line_product = fields.Char(string='商品名稱', required=True)
    original_quantity = fields.Float(string='原始數量', digits=(12, 2), readonly=True)
    already_returned = fields.Float(string='已退回數量', digits=(12, 2), readonly=True)
    remaining_quantity = fields.Float(string='可退回數量', digits=(12, 2), readonly=True)
    return_quantity = fields.Float(string='退回數量', digits=(12, 2))
    unit_price = fields.Float(string='單價', digits=(12, 2), readonly=True)
    unit = fields.Char(string='單位', readonly=True)
    return_amount = fields.Float(string='退回金額', compute='_compute_return_amount', store=True)
    
    @api.depends('return_quantity', 'unit_price')
    def _compute_return_amount(self):
        for line in self:
            line.return_amount = round(line.return_quantity * line.unit_price, 2)
    
    @api.constrains('return_quantity', 'remaining_quantity')
    def _check_return_quantity(self):
        for line in self:
            if line.return_quantity < 0:
                raise ValidationError('退回數量不能為負數！')
            if line.return_quantity > line.remaining_quantity:
                raise ValidationError(f'退回數量 {line.return_quantity} 不能超過可退回數量 {line.remaining_quantity}！')
    
    @api.onchange('return_quantity')
    def _onchange_return_quantity(self):
        if self.return_quantity < 0:
            return {'warning': {'title': '警告', 'message': '退回數量不能為負數！'}}
        if self.return_quantity > self.remaining_quantity:
            return {'warning': {'title': '警告', 'message': f'退回數量不能超過可退回數量 {self.remaining_quantity}！'}}