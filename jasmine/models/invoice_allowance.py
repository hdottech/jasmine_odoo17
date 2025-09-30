# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
_logger = logging.getLogger(__name__)


class InvoiceAllowance(models.Model):
    _name = 'invoice.allowance'
    _description = '折讓證明單資訊'
    _inherit = ['mail.thread']

    name = fields.Char(string='折讓證明單號', required=True, copy=False, readonly=True, default='New')
    original_invoice_id = fields.Many2one('invoice.information', string='原始電子發票', required=True, 
                                         domain="[('is_allowance', '=', False)]", 
                                         ondelete='restrict')
    original_invoice_number = fields.Char(string='原始發票號碼', related='original_invoice_id.invoice_number', store=True, readonly=True)
    original_invoice_date = fields.Datetime(string='原始發票日期', related='original_invoice_id.invoice_date', store=True, readonly=True)
    tax_type = fields.Selection(related='original_invoice_id.tax_type', string='課稅別', store=True, readonly=True)
    tax_rate = fields.Float(related='original_invoice_id.tax_rate', string='稅率', store=True, readonly=True)
    buyer_tax_id = fields.Char(string='買方統編', related='original_invoice_id.buyer_tax_id', store=True, readonly=True)
    seller_tax_id = fields.Char(string='賣方統編', related='original_invoice_id.seller_tax_id', store=True, readonly=True)

    allowance_date = fields.Datetime(string='折讓開立日期', default=fields.Datetime.now)
    allowance_type = fields.Selection([
        ('1', '買方開立'),
        ('2', '賣方開立')
    ], string='折讓類型', default='2', required=True)

    sales_amount = fields.Float(string='折讓銷售額', compute='_compute_tax_amount', store=True)
    tax_amount = fields.Float(string='折讓稅額', compute='_compute_tax_amount', store=True)
    total_amount = fields.Float(string='折讓總金額', compute='_compute_tax_amount', store=True)
    
    remark = fields.Text(string='備註')
    allowance_number = fields.Char(string='折讓證明單號碼', readonly=True)

    invoice_information_id = fields.Many2one('invoice.information', string='電子發票記錄', readonly=True)
    state = fields.Selection([
        ('draft', '草稿'),
        ('done', '已成立折讓單'),
    ], string='狀態', default='draft', tracking=True)
    
    allowance_line_ids = fields.One2many('invoice.allowance.line', 'allowance_id', string='折讓證明單明細')
    
    # 計算字段
    @api.depends('allowance_line_ids.allowance_amount', 'tax_type', 'tax_rate')
    def _compute_tax_amount(self):
        for record in self:
            # 根據明細行計算銷售額
            record.sales_amount = sum(line.allowance_amount for line in record.allowance_line_ids)
            
            # 根據稅別計算稅額和總額
            if record.tax_type == '1':  # 應稅
                # 正向計算稅額和總額
                record.tax_amount = round(record.sales_amount * (record.tax_rate / 100), 0)
                record.total_amount = record.sales_amount + record.tax_amount
            else:
                # 免稅
                record.tax_amount = 0
                record.total_amount = record.sales_amount
    
    @api.onchange('original_invoice_id')
    def _onchange_original_invoice(self):
        """當選擇原始發票時，自動載入明細行"""
        if self.original_invoice_id:
            # 清空現有明細行，避免重複添加
            self.allowance_line_ids = [(5, 0, 0)]
            
            # 計算已折讓金額 - 修正處理新記錄的情況
            done_allowances = self.env['invoice.allowance'].search([
                ('original_invoice_id', '=', self.original_invoice_id.id),
                ('state', '=', 'done')
            ])
            
            # 計算每個產品明細的已折讓金額
            product_allowanced = {}
            for allowance in done_allowances:
                for line in allowance.allowance_line_ids:
                    key = (line.product_name, line.quantity, line.unit_price)
                    if key not in product_allowanced:
                        product_allowanced[key] = 0
                    product_allowanced[key] += line.allowance_amount
            
            # 將原始發票的明細項目複製到折讓單明細行
            lines = []
            for line in self.original_invoice_id.invoice_line_ids:
                key = (line.product_name, line.quantity, line.unit_price)
                already_allowanced = product_allowanced.get(key, 0)
                remaining_amount = line.line_amount - already_allowanced
                
                lines.append((0, 0, {
                    'product_name': line.product_name,
                    'quantity': line.quantity,
                    'unit_price': line.unit_price,
                    'unit': line.unit,
                    'already_allowanced': already_allowanced,
                    'original_line_amount': line.line_amount,
                    'remaining_line_amount': remaining_amount,
                    'allowance_amount': 0.0,
                }))
            
            if lines:
                self.allowance_line_ids = lines

    def action_confirm(self):
        self.ensure_one()
        
        if self.state != 'draft':
            raise UserError('只有草稿狀態的折讓單可以確認！')
        
        # 檢查原始發票是否有效
        if not self.original_invoice_id:
            raise UserError('必須選擇原始電子發票！')
            
        if not self.original_invoice_number:
            raise UserError('原始發票號碼不能為空！')
        
        # 記錄確認時的發票資訊
        _logger.info(f"確認折讓單，原始發票資訊: ID={self.original_invoice_id.id}, "
                    f"號碼={self.original_invoice_number}, 日期={self.original_invoice_date}")
        
        # 檢查折讓金額不能超過原始發票金額
        if self.total_amount > self.original_invoice_id.total_amount:
            raise UserError('折讓金額不能超過原始發票金額！')
            
        # 檢查折讓明細行
        if not self.allowance_line_ids:
            raise UserError('請至少新增一筆折讓明細行！')
            
        # 檢查是否有明細行折讓金額大於0
        if not any(line.allowance_amount > 0 for line in self.allowance_line_ids):
            raise UserError('至少需要一筆明細行有折讓金額！')
        
        # 產生折讓單號碼
        if not self.allowance_number:
            # 獲取序列號，如果沒有則使用名稱，但不重複添加 ALW- 前綴
            seq_number = self.env['ir.sequence'].next_by_code('invoice.allowance.number')
            if seq_number:
                self.allowance_number = seq_number
            else:
                # 確保不重複添加前綴
                self.allowance_number = self.name if not self.name.startswith('ALW-') else self.name
            _logger.info(f"生成折讓單號碼: {self.allowance_number}")

        # 準備折讓電子發票明細行
        invoice_lines = []
        for line in self.allowance_line_ids:
            if line.allowance_amount > 0:
                invoice_lines.append((0, 0, {
                    'product_name': f"折讓: {line.product_name}",
                    'quantity': line.quantity,
                    'unit_price': (line.allowance_amount / line.quantity) if line.quantity else 0,
                    'unit': line.unit,
                    'line_amount': line.allowance_amount,
                    'tax_type': self.tax_type,
                }))
        
        # 檢查是否有明細行要添加
        if not invoice_lines:
            raise UserError('沒有任何明細行的折讓金額大於0！')

        # 建立折讓電子發票
        try:
            # 準備創建折讓單記錄的值
            einvoice_vals = {
                'order_id': self.name,
                # 使用折讓單號碼作為發票號碼，不生成新的發票號碼
                'invoice_number':  f"{self.original_invoice_number}",
                # 添加 no_regenerate_invoice_number 確保不會在 create 方法中生成新號碼
                'invoice_date': self.allowance_date,
                'invoice_type': self.original_invoice_id.invoice_type,
                'invoice_track_id': self.original_invoice_id.invoice_track_id.id,
                'seller_tax_id': self.original_invoice_id.seller_tax_id,
                'seller_name': self.original_invoice_id.seller_name,
                'seller_address': self.original_invoice_id.seller_address,
                'seller_phone': self.original_invoice_id.seller_phone,
                'buyer_tax_id': self.original_invoice_id.buyer_tax_id,
                'buyer_name': self.original_invoice_id.buyer_name,
                'buyer_address': self.original_invoice_id.buyer_address,
                'tax_type': self.tax_type,
                'tax_rate': self.tax_rate,
                'sales_amount': int(self.sales_amount),
                'tax_amount': int(self.tax_amount),
                'total_amount': int(self.total_amount),
                'currency': self.original_invoice_id.currency or 'TWD',
                'is_allowance': True,  # 明確標記為折讓單
                'allowance_type': self.allowance_type,
                'allowance_number': self.allowance_number,  # 明確設置折讓單號
                'original_invoice_number': self.original_invoice_number,  # 原始發票號碼
                'original_invoice_date': self.original_invoice_date,
                'operation_type': 'CRE_ALW',
                'invoice_line_ids': invoice_lines,
                'remark': self.remark,
            }
            
            # 記錄準備創建的折讓單信息
            _logger.info(f"準備創建折讓單記錄，折讓單號: {self.allowance_number}, "
                        f"原始發票號碼: {self.original_invoice_number}")
            
            # 創建折讓單記錄，添加上下文確保不會生成新發票號碼
            einvoice = self.env['invoice.information'].with_context(
                from_account_move_sync=True,
                no_regenerate_invoice_number=True
            ).create(einvoice_vals)
            
            # 檢查創建結果
            _logger.info(f"創建折讓單記錄結果: ID={einvoice.id}, "
                        f"發票號碼={einvoice.invoice_number}, "
                        f"原始發票號碼={einvoice.original_invoice_number}")
            
            # 更新關聯和狀態
            self.write({
                'invoice_information_id': einvoice.id,
                'state': 'done'
            })
            
            # 提交事務
            self.env.cr.commit()
            
            # 顯示成功訊息
            return {
                'type': 'ir.actions.act_window',
                'name': '折讓單',
                'res_model': 'invoice.allowance',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
                'context': {'form_view_initial_mode': 'edit'},
                'flags': {'mode': 'readonly'},
            }
        
        except Exception as e:
            # 記錄錯誤詳情
            _logger.error(f"折讓單開立失敗: {str(e)}", exc_info=True)
            raise UserError(f'折讓單開立失敗：{str(e)}')
        
    def action_create_allowance(self):
        self.ensure_one()
        if self.is_allowance:
            raise UserError("此發票為折讓單，無法再折讓")
        
        if self.has_allowance:
            raise UserError("此發票已開立折讓單")

        return {
            'name': '建立折讓單',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.allowance',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_original_invoice_id': self.id,
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('invoice.allowance') or 'New'
        return super(InvoiceAllowance, self).create(vals_list)


class InvoiceAllowanceLine(models.Model):
    _name = 'invoice.allowance.line'
    _description = '折讓單明細行'
    
    allowance_id = fields.Many2one('invoice.allowance', string='折讓單', required=True, ondelete='cascade')
    product_name = fields.Char(string='品名', required=True)
    quantity = fields.Float(string='數量', digits=(12, 2))
    unit_price = fields.Float(string='單價', digits=(12, 2))
    unit = fields.Char(string='單位')
    already_allowanced = fields.Float(string='已折讓金額', digits=(12, 2), readonly=True)
    original_line_amount = fields.Float(string='原始金額', digits=(12, 2), readonly=True)
    remaining_line_amount = fields.Float(string='可折讓餘額', digits=(12, 2), readonly=True)
    allowance_amount = fields.Float(string='折讓金額', digits=(12, 2))
    
    @api.constrains('allowance_amount', 'original_line_amount')
    def _check_allowance_amount(self):
        for line in self:
            # 僅檢查折讓金額不超過原始金額
            if line.allowance_amount > line.original_line_amount:
                raise ValidationError(f'折讓金額 {line.allowance_amount} 不能超過原始金額 {line.original_line_amount}！')
    
    @api.onchange('allowance_amount')
    def _onchange_allowance_amount(self):
        if self.allowance_amount > self.original_line_amount:
            return {'warning': {
                'title': '警告',
                'message': f'折讓金額 {self.allowance_amount} 不能超過原始金額 {self.original_line_amount}！'
            }}
            
    @api.depends('allowance_id.state')
    def _compute_readonly(self):
        for line in self:
            line.readonly = line.allowance_id.state == 'done'