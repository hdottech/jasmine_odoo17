from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    bill_id = fields.Many2one('account.bill', string='關聯票據') 
    bank_id = fields.Many2one('res.bank', string='開票銀行')
    drawer = fields.Char(string='開票人', default=lambda self: self.env.user.name)
    issue_date = fields.Date(string='開票日')
    due_date = fields.Date(string='到期日')
    bill_type = fields.Selection([
        ('regular', '應收票據'),
        ('postdated', '應付票據')
    ], string='票據種類', default='regular')
    bill_ids = fields.One2many('account.bill', 'payment_id', string='票據清單')
    bill_count = fields.Integer(compute='_compute_bill_count', string='票據數量')
    is_bill_payment = fields.Boolean(string='是票據付款', default=False)
    is_bill_cash_payment = fields.Boolean(string='是票據兌現付款', default=False)

    @api.depends('bill_ids')
    def _compute_bill_count(self):
        for payment in self:
            payment.bill_count = len(payment.bill_ids)

    def action_view_bills(self):
        self.ensure_one()
        _logger.info('Action view bills triggered for payment %s', self.id)
        return {
            'name': '票據清單',
            'type': 'ir.actions.act_window',
            'res_model': 'account.bill',
            'view_mode': 'tree,form',
            'domain': [('payment_id', '=', self.id)],
            'context': {'default_payment_id': self.id},
        }
    
    # 重寫創建方法，確保票據付款不建立日記帳分錄
    @api.model_create_multi
    def create(self, vals_list):
        """重寫創建方法，處理票據付款和票據兌現付款"""
        # 檢查是否有票據付款或票據兌現付款
        for i, vals in enumerate(vals_list):
            is_bill_payment = vals.get('is_bill_payment', False)
            is_bill_cash_payment = vals.get('is_bill_cash_payment', False)
            
            if is_bill_payment and not is_bill_cash_payment:
                _logger.info('創建票據付款記錄時跳過會計分錄同步')
                self = self.with_context(skip_account_move_synchronization=True)
                # 創建但不生成會計分錄
                payment = super(AccountPayment, self.with_context(
                    skip_account_move_synchronization=True,
                    no_create_move=True
                )).create(vals_list)
                
                # 設置付款狀態為已過帳，但不創建會計分錄
                if payment:
                    payment.write({'state': 'posted'})
                    _logger.info('已創建票據付款: %s, 狀態設置為已過帳但無會計分錄', payment.ids)
                
                return payment
        
        # 其他情況使用標準流程
        return super(AccountPayment, self).create(vals_list)
                

    # 防止票據付款自動過帳
    def action_post(self):
        # 過濾掉票據付款
        regular_payments = self.filtered(lambda p: not p.is_bill_payment or p.is_bill_cash_payment)
        bill_payments = self.filtered(lambda p: p.is_bill_payment and not p.is_bill_cash_payment)
        
        # 對於票據付款，直接設置狀態而不創建日記帳
        if bill_payments:
            bill_payments.write({'state': 'posted'})
            _logger.info('已將%s個票據付款設置為已過帳狀態', len(bill_payments))
        
        # 對於普通付款，使用標準方法
        result = super(AccountPayment, regular_payments).action_post() if regular_payments else True
        
        return result