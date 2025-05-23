from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import logging
_logger = logging.getLogger(__name__)

class AccountBillCashWizard(models.TransientModel):
    _name = 'account.bill.cash.wizard'
    _description = '票據兌現確認'

    bill_id = fields.Many2one('account.bill', string='票據', required=True)
    journal_id = fields.Many2one(
        'account.journal', 
        string='日記帳',
        required=True,
        domain="[('type', 'in', ['bank', 'cash'])]"
    )
    amount = fields.Monetary(
        string='金額',
        required=True,
        currency_field='currency_id',
        readonly=True
    )
    currency_id = fields.Many2one(
        'res.currency', 
        string='幣別',
        default=lambda self: self.env.company.currency_id
    )
    payment_date = fields.Date(
        string='付款日期',
        required=True,
        default=fields.Date.context_today
    )

    @api.depends('bill_id')
    def _compute_amount(self):
        for record in self:
            record.amount = record.bill_id.amount if record.bill_id else 0.0

    def action_confirm(self):
        self.ensure_one()
        
        try:
            # 檢查票據資料是否完整
            if not self.bill_id:
                raise UserError(_('未指定票據。'))
            
            if not self.bill_id.invoice_move:
                raise UserError(_('票據沒有關聯憑單。'))
                
            if not self.bill_id.invoice_move.partner_id:
                raise UserError(_('關聯憑單沒有合作夥伴資訊。'))
                
            bill_reference = self.bill_id.bill_number
            if not bill_reference:
                raise UserError(_('票據沒有票據號碼。'))
            
            # 找到未結收款科目
            receivable_account = None
            if self.bill_id.invoice_move:
                if self.bill_id.bill_type == 'receivable':
                    receivable_lines = self.bill_id.invoice_move.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'asset_receivable'
                    )
                    if receivable_lines:
                        receivable_account = receivable_lines[0].account_id
                else:
                    payable_lines = self.bill_id.invoice_move.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'liability_payable'
                    )
                    if payable_lines:
                        receivable_account = payable_lines[0].account_id
                        
            if not receivable_account:
                raise UserError(_('無法找到未結收款/付款科目。'))
            
            # 檢查日記帳是否有預設會計科目
            if not self.journal_id.default_account_id:
                raise UserError(_('所選的日記帳沒有預設的會計科目。'))
            
            # 建立一筆兌現分錄 (借現金/銀行，貸未結收款)
            move_vals = {
                'journal_id': self.journal_id.id,
                'date': self.payment_date,
                'ref': f'票據兌現 - {bill_reference}',
                'move_type': 'entry',
                'partner_id': self.bill_id.invoice_move.partner_id.id,
                'line_ids': [
                    (0, 0, {
                        'account_id': self.journal_id.default_account_id.id,  # 銀行/現金科目
                        'name': f'票據兌現 - {bill_reference}',
                        # 借方為現金/銀行
                        'debit': self.amount,
                        'credit': 0.0,
                        'partner_id': self.bill_id.invoice_move.partner_id.id,
                    }),
                    (0, 0, {
                        'account_id': receivable_account.id,  # 未結收款科目
                        'name': f'票據兌現 - {bill_reference}',
                        # 貸方為未結收款
                        'debit': 0.0,
                        'credit': self.amount,
                        'partner_id': self.bill_id.invoice_move.partner_id.id,
                    })
                ]
            }
            
            # 創建並過帳分錄
            _logger.info('確認票據，上下文: %s', self._context)
            _logger.info('創建票據兌現分錄: %s', move_vals)
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            
            # 更新票據狀態
            self.bill_id.write({
                'state': 'cashed',
                'cash_date': self.payment_date,
                'move_id1': move.id,
            })
            
            # 手動更新發票狀態
            self.bill_id.invoice_move.with_context(check_move_validity=False).write({
                'payment_state': 'paid',
                'bill_payment_state': 'paid'
            })
            
            _logger.info('票據兌現完成，票據ID: %s, 分錄ID: %s', self.bill_id.id, move.id)
            return {'type': 'ir.actions.act_window_close'}
                
        except Exception as e:
            _logger.error('兌現處理失敗: %s', str(e), exc_info=True)
            raise UserError(_('兌現處理失敗: %s') % str(e))


  
class AccountBillVoidWizard(models.TransientModel):
    _name = 'account.bill.void.wizard'
    _description = '票據註銷'

    bill_id = fields.Many2one('account.bill', string='票據', required=True)
    void_date = fields.Date(string='註銷日期', required=True, default=fields.Date.context_today)
    void_reason = fields.Text(string='註銷原因', required=True)
    bill_type = fields.Selection([
        ('receivable', '應收票據'),
        ('payable', '應付票據')
    ], string='票據種類', default='receivable')


    def action_confirm(self):
        self.ensure_one()
        self.bill_id.write({
            'state': 'void',
            'cancel_date': self.void_date,
            'cancel_reason': self.void_reason
        })
        return {'type': 'ir.actions.act_window_close'}