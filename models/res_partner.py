# -*- coding: utf-8 -*-
from odoo import models, fields, api
import re
import logging

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    vat_number = fields.Char(string='統一編號', help='公司統一編號')
    vendor_code = fields.Char(string='編號', help='自定義編號', copy=False)
    
    _sql_constraints = [
        ('vendor_code_uniq', 'unique(vendor_code)', '編號必須是唯一的!')
    ]
    # 修改銷售員欄位
    employee_user_id = fields.Many2one(
        'hr.employee',
        string="銷售員 (員工)",
        domain="[('active', '=', True)]",  # 只顯示在職員工
        help="選擇負責此客戶的員工"
    )

    employee_buyer_id = fields.Many2one(
        'hr.employee',
        string="買方 (員工)",
        domain="[('active', '=', True)]",
        help="選擇負責此採購的員工"
    )

    # 有顯示地址
    @api.depends('name', 'vendor_code', 'parent_id', 'type', 'company_name', 'is_company', 'commercial_company_name')
    def _compute_display_name(self):
        for partner in self:
            name = partner.name or ''
            
            if partner.vendor_code:
                name = f'[{partner.vendor_code}] {name}'
            
            if self._context.get('show_address'):
                address = partner._display_address(without_company=True)
                if address:
                    name = f"{name}\n{address}"
            if self._context.get('show_vat') and partner.vat:
                name = f"{name} ‒ {partner.vat}"
            
            partner.display_name = name.strip()

    def name_get(self):
        result = []
        for partner in self:
            name = partner.name or ''
            
            if partner.vendor_code:
                name = f'[{partner.vendor_code}] {name}'

            if self._context.get('show_address'):
                address = partner._display_address(without_company=True)
                if address:
                    name = f"{name}\n{address}"

            if self._context.get('show_vat') and partner.vat:
                name = f"{name} ‒ {partner.vat}"
            
            result.append((partner.id, name.strip()))
        return result

    

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    partner_vendor_code = fields.Char(related='partner_id.vendor_code', string='編號', readonly=True, store=True)
    partner_vat_number = fields.Char(related='partner_id.vat_number', string='統一編號', readonly=True, store=True)
    partner_id = fields.Many2one(
        'res.partner',
    )
    employee_buyer_id = fields.Many2one(
        'hr.employee',
        string="買方 (員工)",
        related='partner_id.employee_buyer_id',
        store=True,
        readonly=False
    )
    @api.onchange('partner_id', 'company_id')   #檢查並帶入統一編號、廠商編號
    def onchange_partner_id(self):
        result = super().onchange_partner_id()
        if self.partner_id:
            self.partner_vendor_code = self.partner_id.vendor_code
            self.partner_vat_number = self.partner_id.vat_number
        else:
            self.partner_vendor_code = False
            self.partner_vat_number = False
        return result
    
class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    sequence_number = fields.Integer(string='項次', compute='_compute_sequence_number', default=0)

    @api.depends('order_id.order_line')
    def _compute_sequence_number(self):
        for order in self.mapped('order_id'):
            lines = order.order_line.sorted('sequence')
            for index, line in enumerate(lines, start=1):
                line.sequence_number = index
    
    
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    partner_vendor_code = fields.Char(related='partner_id.vendor_code', string='編號', readonly=True, store=True)
    partner_vat_number = fields.Char(related='partner_id.vat_number', string='統一編號', readonly=True, store=True)
    signature = fields.Binary(string='客戶簽名', attachment=True)
    employee_user_id = fields.Many2one(
        'hr.employee',
        string="銷售員 (員工)",
        related='partner_id.employee_user_id',
        store=True,
        readonly=False
    )
    
    def print_sale_order(self):
        self.ensure_one()
        return self.env.ref('jasmine.jasmine_sale_order_report').report_action(self, config=False)
    def action_open_sales_report(self):
        partner_id = self.order_id.partner_id.id
        
        return {
            'name': '銷售分析報表',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.report',
            'view_mode': 'tree',
            'target': 'new',
            'domain': [('partner_id', '=', partner_id)],  # 只顯示此客戶的資料
            'context': {
                'create': False,
            }
        }
            
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    sequence_number = fields.Integer(string='項次', compute='_compute_sequence_number', default=0)

    #計算項次
    @api.depends('order_id.order_line')
    def _compute_sequence_number(self):
        for order in self.mapped('order_id'):
            lines = order.order_line.sorted('sequence')
            for index, line in enumerate(lines, start=1):
                line.sequence_number = index

    #產品銷售分析按鈕
    def action_open_sales_report(self):
        if not self.order_id:
            _logger.warning("Order ID is missing for sale.order.line ID: %s", self.id)
            return

        if not self.order_id.partner_id:
            _logger.warning("Partner ID is missing for order ID: %s", self.order_id.id)
            return

        partner_id = self.order_id.partner_id.id
        _logger.info("Found Partner ID: %s", partner_id)

        # 確保 partner_id 有值
        if not partner_id:
            _logger.warning("Partner ID is still missing after assignment")
            return

        # 測試查詢是否有資料
        reports = self.env['sale.report'].search([('partner_id', '=', partner_id)])
        _logger.info("Found %s reports for Partner ID %s", len(reports), partner_id)

        return {
        'name': '銷售分析報表',
        'type': 'ir.actions.act_window',
        'res_model': 'sale.report',
        'view_mode': 'tree',
        'target': 'new',  # 使用彈出視窗
        'domain': [],  # 不設定 domain，顯示所有記錄
        'context': {
            'create': False,
            'search_default_partner_id': partner_id,  # 使用 search_default 來預設搜尋條件
        },
    }
    
class StockMove(models.Model):
    _inherit = 'stock.move'

    sequence_number = fields.Integer(string='項次', compute='_compute_sequence_number', store=True, default=0)

    @api.depends('picking_id.move_ids_without_package')
    def _compute_sequence_number(self):
        for picking in self.mapped('picking_id'):
            if not picking:
                continue
                
            lines = picking.move_ids_without_package.sorted('sequence')
            for index, line in enumerate(lines, start=1):
                line.sequence_number = index
                
        # 處理未分配到項次的記錄（可能沒有 picking_id）
        for move in self.filtered(lambda m: not m.picking_id):
            move.sequence_number = 0




            


