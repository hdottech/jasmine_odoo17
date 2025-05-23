# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)

class InvoiceCorrection(models.Model):
    _name = 'invoice.correction'
    _description = '電子發票更正'
    _inherit = ['mail.thread']
    
    name = fields.Char(string='更正單號', required=True, copy=False, readonly=True, default='New')
    original_invoice_id = fields.Many2one('invoice.information', string='原始電子發票', required=True, 
                                         domain="[('operation_type', 'not in', ['REJ', 'CAN', 'CRE_ALW', 'CAN_ALW', 'CRE'])]",  # 修正domain條件
                                         ondelete='restrict')
    original_buyer_name = fields.Char(string='原買方名稱', related='original_invoice_id.buyer_name', readonly=True)
    original_buyer_tax_id = fields.Char(string='原買方統編', related='original_invoice_id.buyer_tax_id', readonly=True)
    original_buyer_address = fields.Char(string='原買方地址', related='original_invoice_id.buyer_address', readonly=True)
    original_tax_type = fields.Selection(string='原課稅別', related='original_invoice_id.tax_type', readonly=True)
    original_tax_rate = fields.Float(string='原稅率', related='original_invoice_id.tax_rate', readonly=True)
    original_remark = fields.Text(string='原備註', related='original_invoice_id.remark', readonly=True)
    original_invoice_number = fields.Char(string='原始發票號碼', related='original_invoice_id.invoice_number', store=True, readonly=True)
    original_invoice_date = fields.Datetime(string='原始發票日期', related='original_invoice_id.invoice_date', store=True, readonly=True)
    
    correction_date = fields.Datetime(string='更正日期', default=fields.Datetime.now)
    correction_reason = fields.Selection([
        ('buyer_info', '買方資訊錯誤'),
        ('product_info', '商品資訊錯誤'),
        ('tax_info', '稅務資訊錯誤'),
        ('other', '其他原因')
    ], string='更正原因', required=True)
    reason_detail = fields.Text(string='更正說明', required=True)
    
    # 更正欄位
    buyer_name = fields.Char(string='買方名稱')
    buyer_tax_id = fields.Char(string='買方統編')
    buyer_address = fields.Char(string='買方地址')
    
    tax_type = fields.Selection([
        ('1', '應稅'),
        ('2', '零稅率'),
        ('3', '免稅'),
        ('4', '應稅(特種)')
    ], string='課稅別')
    tax_rate = fields.Float(string='稅率', digits=(3,2))
    
    remark = fields.Text(string='備註')
    
    state = fields.Selection([
        ('draft', '草稿'),
        ('done', '已更正'),
        ('cancel', '已取消')
    ], string='狀態', default='draft', tracking=True)
    
    correction_line_ids = fields.One2many('invoice.correction.line', 'correction_id', string='更正明細')
    
    @api.onchange('original_invoice_id')
    def _onchange_original_invoice(self):
        if self.original_invoice_id:
            # 檢查發票狀態
            if self.original_invoice_id.operation_type in ['REJ', 'CAN', 'CRE_ALW', 'CAN_ALW', 'CRE']:
                raise UserError('此發票已被處理或更正，無法再次更正！')
            
            # 載入原始發票資訊
            self.buyer_name = self.original_invoice_id.buyer_name
            self.buyer_tax_id = self.original_invoice_id.buyer_tax_id
            self.buyer_address = self.original_invoice_id.buyer_address
            self.tax_type = self.original_invoice_id.tax_type
            self.tax_rate = self.original_invoice_id.tax_rate
            self.remark = self.original_invoice_id.remark
            
            # 清空並載入發票明細行
            self.correction_line_ids = [(5, 0, 0)]
            lines = []
            for line in self.original_invoice_id.invoice_line_ids:
                lines.append((0, 0, {
                    'original_line_id': line.id,
                    'product_name': line.product_name,
                    'quantity': line.quantity,
                    'unit_price': line.unit_price,
                    'unit': line.unit,
                    'line_amount': line.line_amount,
                    'corrected_product_name': line.product_name,
                    'corrected_quantity': line.quantity,
                    'corrected_unit_price': line.unit_price,
                    'corrected_unit': line.unit,
                }))
            
            if lines:
                self.correction_line_ids = lines
    
    def action_confirm(self):
        self.ensure_one()
        
        if self.state != 'draft':
            raise UserError('只有草稿狀態的更正單可以確認！')
        
        # 再次檢查原始發票狀態
        if self.original_invoice_id.operation_type in ['REJ', 'CAN', 'CRE_ALW', 'CAN_ALW', 'CRE']:
            raise UserError('原始發票狀態已變更，無法更正！')
        
        # 檢查是否有明細行
        if not self.correction_line_ids:
            raise UserError('請至少添加一行更正明細！')
        
        # 檢查是否有實際更正內容
        has_changes = False
        
        # 檢查發票頭部資訊是否有變更
        if (self.buyer_name != self.original_invoice_id.buyer_name or
            self.buyer_tax_id != self.original_invoice_id.buyer_tax_id or
            self.buyer_address != self.original_invoice_id.buyer_address or
            self.tax_type != self.original_invoice_id.tax_type or
            self.tax_rate != self.original_invoice_id.tax_rate or
            self.remark != self.original_invoice_id.remark):
            has_changes = True
        
        # 檢查明細行是否有變更
        if not has_changes:
            for line in self.correction_line_ids:
                if line.original_line_id:
                    if (line.corrected_product_name != line.product_name or
                        line.corrected_quantity != line.quantity or
                        line.corrected_unit_price != line.unit_price or
                        line.corrected_unit != line.unit):
                        has_changes = True
                        break
        
        if not has_changes:
            raise UserError('沒有檢測到任何更正內容，請修改需要更正的資訊！')
        
        # 計算更新後的銷售額和稅額
        sales_amount = sum(line.corrected_quantity * line.corrected_unit_price for line in self.correction_line_ids)
        if self.tax_type == '1':  # 應稅
            tax_amount = round(sales_amount * (self.tax_rate / 100))
        else:
            tax_amount = 0
        total_amount = sales_amount + tax_amount
        
        # 更新原始發票
        try:
            # 獲取更正原因文字
            reason_display = dict(self._fields['correction_reason'].selection).get(self.correction_reason, '')
            
            # 準備更正記錄
            correction_summary = []
            if self.buyer_name != self.original_invoice_id.buyer_name:
                correction_summary.append(f"買方名稱: {self.original_invoice_id.buyer_name} → {self.buyer_name}")
            if self.buyer_tax_id != self.original_invoice_id.buyer_tax_id:
                correction_summary.append(f"買方統編: {self.original_invoice_id.buyer_tax_id} → {self.buyer_tax_id}")
            if self.tax_type != self.original_invoice_id.tax_type:
                correction_summary.append(f"課稅別: {self.original_invoice_id.tax_type} → {self.tax_type}")
            
            correction_detail = "\n    - ".join([""] + correction_summary) if correction_summary else ""
            
            # 更新發票主記錄
            self.original_invoice_id.with_context(force_einvoice_edit=True).write({
                'buyer_name': self.buyer_name,
                'buyer_tax_id': self.buyer_tax_id,
                'buyer_address': self.buyer_address,
                'tax_type': self.tax_type,
                'tax_rate': self.tax_rate,
                'sales_amount': int(sales_amount),
                'tax_amount': int(tax_amount),
                'total_amount': int(total_amount),
                'operation_type': 'CRE',  # 設置為更正狀態
                'remark': f"{self.original_invoice_id.remark or ''}\n[更正] {self.correction_date.strftime('%Y-%m-%d %H:%M')}: "
                         f"{reason_display} - {self.reason_detail}{correction_detail}"
            })
            
            # 更新發票明細行
            for line in self.correction_line_ids:
                if line.original_line_id:
                    line.original_line_id.with_context(force_einvoice_edit=True).write({
                        'product_name': line.corrected_product_name,
                        'quantity': line.corrected_quantity,
                        'unit_price': line.corrected_unit_price,
                        'unit': line.corrected_unit,
                        'line_amount': line.corrected_quantity * line.corrected_unit_price
                    })
            
            # 更新狀態
            self.write({
                'state': 'done'
            })
            
            # 記錄日誌
            _logger.info(f"更正單 {self.name} 已確認，原始發票 {self.original_invoice_number} 已更正")
            
            # 返回表單視圖
            return {
                'type': 'ir.actions.act_window',
                'name': '更正單',
                'res_model': 'invoice.correction',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
                'flags': {'mode': 'readonly'},
            }
        
        except Exception as e:
            _logger.error(f"更正單確認失敗: {str(e)}", exc_info=True)
            raise UserError(f'更正單確認失敗: {str(e)}')
    
    def get_correction_reason_display(self):
        """獲取更正原因的顯示文字"""
        selection = dict(self._fields['correction_reason'].selection)
        return selection.get(self.correction_reason, '')
    
    def action_cancel(self):
        """取消更正單"""
        self.ensure_one()
        
        if self.state == 'done':
            raise UserError('已確認的更正單不能取消！')
            
        self.write({'state': 'cancel'})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('invoice.correction')
        return super(InvoiceCorrection, self).create(vals_list)


class InvoiceCorrectionLine(models.Model):
    _name = 'invoice.correction.line'
    _description = '電子發票更正明細'
    
    correction_id = fields.Many2one('invoice.correction', string='更正單', required=True, ondelete='cascade')
    original_line_id = fields.Many2one('invoice.line', string='原始明細行')
    
    # 原始資訊
    product_name = fields.Char(string='原品名', readonly=True)
    quantity = fields.Float(string='原數量', digits=(12, 2), readonly=True)
    unit_price = fields.Float(string='原單價', digits=(12, 2), readonly=True)
    unit = fields.Char(string='原單位', readonly=True)
    line_amount = fields.Float(string='原金額', digits=(12, 2), readonly=True)
    
    # 更正資訊
    corrected_product_name = fields.Char(string='更正品名', required=True)
    corrected_quantity = fields.Float(string='更正數量', digits=(12, 2), required=True)
    corrected_unit_price = fields.Float(string='更正單價', digits=(12, 2), required=True)
    corrected_unit = fields.Char(string='更正單位')
    corrected_line_amount = fields.Float(string='更正金額', compute='_compute_corrected_amount', store=True)
    
    @api.depends('corrected_quantity', 'corrected_unit_price')
    def _compute_corrected_amount(self):
        for line in self:
            line.corrected_line_amount = round(line.corrected_quantity * line.corrected_unit_price, 2)
    
    @api.constrains('corrected_quantity', 'corrected_unit_price')
    def _check_corrected_values(self):
        for line in self:
            if line.corrected_quantity < 0:
                raise ValidationError('更正數量不能為負數！')
            if line.corrected_unit_price < 0:
                raise ValidationError('更正單價不能為負數！')