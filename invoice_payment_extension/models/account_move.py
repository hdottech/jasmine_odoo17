from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    bill_ids = fields.One2many('account.bill', 'invoice_move', string='票據')
    has_bill_payment = fields.Boolean(
        string='Has Bill Payment',
        compute='_compute_has_bill_payment',
        store=True,
        help='檢查是否有使用票據付款'
    )
    is_from_bill = fields.Boolean(
        string='Is From Bill Payment',
        compute='_compute_is_from_bill',
        store=True,
        help='是否由票據付款產生'
    )
    bill_payment_state = fields.Selection([
        ('unpaid', '未付款'),
        ('partial', '部分付款'),
        ('paid', '已付款'),
        ('bill_pending', '已使用票據付款')
    ], string='票據付款狀態', compute='_compute_bill_payment_state', store=True)
    payment_state = fields.Selection(selection_add=[('bill_pending', '票據付款')])
    can_register_payment = fields.Boolean(
        compute='_compute_can_register_payment',
        store=True
    )

    @api.depends('line_ids.payment_id.bill_id')
    def _compute_is_from_bill(self):
        for move in self:
            move.is_from_bill = bool(move.line_ids.mapped('payment_id.bill_id'))

    @api.depends('bill_ids')
    def _compute_has_bill_payment(self):
        for record in self:
            record.has_bill_payment = bool(record.bill_ids)

            
    @api.depends('bill_ids', 'bill_ids.state')
    def _compute_bill_payment_state(self):
        for record in self:
            if not record.bill_ids:
                record.bill_payment_state = 'unpaid'  # 使用已定義的值
                continue
                
            cashed_bills = record.bill_ids.filtered(lambda b: b.state == 'cashed')
            if cashed_bills:
                record.bill_payment_state = 'paid'
            else:
                record.bill_payment_state = 'bill_pending' 

    @api.depends('state', 'bill_payment_state', 'payment_state')
    def _compute_can_register_payment(self):
        for move in self:
            move.can_register_payment = (
                move.state == 'posted' and
                move.payment_state != 'paid' and
                move.bill_payment_state != 'paid'
            )

    def _create_payment_memo(self, payment):
        """創建付款備忘錄"""
        self.ensure_one()
        memo = f"發票號碼: {self.name}"
        if self.bill_ids:
            bill_numbers = ", ".join(self.bill_ids.mapped('bill_number'))
            memo += f" / 票據號碼: {bill_numbers}"
        return memo

    def action_register_payment(self):
        """登記付款動作"""
        if not self.can_register_payment:
            raise UserError(_("此單據目前無法登記付款"))
        return {
            'name': _('登記付款'),
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'context': {
                'active_model': 'account.move',
                'active_ids': self.ids,
                'default_memo': self._create_payment_memo(None),
            },
            'target': 'new',
            'type': 'ir.actions.act_window',
        }
        
    def _get_payment_state_items(self):
        res = super()._get_payment_state_items()
        res['bill_pending'] = _('票據付款中')
        return res
    
    def _create_payment_vals_from_batch(self, batch_result):
        """重寫批量付款值生成方法，處理票據付款場景"""
        if self.journal_type == 'check':
            # 對於票據付款，建立一個特殊標記
            vals = super()._create_payment_vals_from_batch(batch_result)
            vals['is_bill_payment'] = True
            return vals
        else:
            return super()._create_payment_vals_from_batch(batch_result)