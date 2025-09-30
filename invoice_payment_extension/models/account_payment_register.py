from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import logging
_logger = logging.getLogger(__name__)

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    journal_type = fields.Selection([
        ('cash', '現金'),
        ('bank', '銀行'),
        ('transfer', '轉帳'),
        ('check', '支票')
    ], string='付款方式', default='cash')
    bill_id = fields.Many2one('account.bill', string='票據')
    journal_id = fields.Many2one('account.journal', string='日記帳')
    journal_id_show = fields.Char(related='journal_id.name', string='日記帳名稱', store=True)
    move_id = fields.Many2one(related='bill_id.invoice_move', string='應收/付憑單')
    check_number = fields.Char(string='票據單號', help="請輸入票據單號")
    currency_id = fields.Many2one('res.currency', string='幣別', required=True, default=lambda self: self.env.user.company_id.currency_id)
    bank_id = fields.Many2one('res.bank', string='開票銀行')
    drawer = fields.Char(string='開票人', default=lambda self: self.env.user.name)
    issue_date = fields.Date(string='開票日')
    due_date = fields.Date(string='到期日')
    bill_type = fields.Selection([
        ('receivable', '應收票據'),
        ('payable', '應付票據')
    ], string='票據種類', compute='_compute_bill_type', store=True, readonly=True)


    def _create_payments(self):
        if self._context.get('skip_payment_creation'):
            _logger.info('跳過創建付款，因為上下文中有 skip_payment_creation 標記')
            return self.env['account.payment']
        
        return super(AccountPaymentRegister, self)._create_payments()

    @api.depends('move_id', 'payment_type', 'partner_type')
    def _compute_bill_type(self):
        for record in self:
            if record.move_id:
                if record.move_id.move_type in ['out_invoice', 'out_refund', 'out_receipt']:
                    record.bill_type = 'receivable'
                elif record.move_id.move_type in ['in_invoice', 'in_refund', 'in_receipt']:
                    record.bill_type = 'payable'
                else:
                    record.bill_type = False
            elif record.payment_type and record.partner_type:
                if record.payment_type == 'inbound' and record.partner_type == 'customer':
                    record.bill_type = 'receivable'
                elif record.payment_type == 'outbound' and record.partner_type == 'supplier':
                    record.bill_type = 'payable'
                else:
                    record.bill_type = False
            else:
                record.bill_type = False

    def action_create_payments(self):
        """重寫建立付款邏輯"""
        _logger.info('進入 action_create_payments 方法，journal_type: %s, context: %s', 
                 self.journal_type, self._context)
        
        # 如果是票據付款，走完全獨立的流程
        if self.journal_type == 'check':
            clean_ctx = {
                'active_model': self.env.context.get('active_model'),
                'active_id': self.env.context.get('active_id'),
                'active_ids': self.env.context.get('active_ids'),
                'skip_payment_creation': True,
                'no_create_move': False,
                'no_create_bill_accounting': False
            }
            
            self = self.with_context(clean_ctx)
            
            _logger.info('準備處理票據付款，允許創建會計分錄，上下文: %s', self._context)
            self._check_bank_selection()
            bill = self._create_bill_if_needed()
            if bill:
                invoice_move = bill.invoice_move
                if invoice_move:
                    _logger.info('更新發票狀態為票據待兌現')
                    invoice_move.write({
                        'payment_state': 'bill_pending',
                        'bill_payment_state': 'bill_pending'
                    })
                    _logger.info('使用票據付款，已產生會計分錄')
                
                # 不創建付款記錄，直接返回
                _logger.info('票據支付完成，直接返回，不執行標準付款流程')
                return {'type': 'ir.actions.act_window_close'}
        
        # 只有非票據付款才走原生流程
        _logger.info('非票據付款，執行標準付款流程')
        result = super(AccountPaymentRegister, self).action_create_payments()
        return result

    def _create_payment_vals_from_wizard(self, batch_result):
        """重寫付款值生成方法，處理票據付款場景"""
        if self.journal_type == 'check':
            _logger.info('嘗試為票據付款創建付款值，返回空字典')
            return {}
        else:
            return super()._create_payment_vals_from_wizard(batch_result)

    def _check_bank_selection(self):
        if self.journal_type == 'check' and not self.bank_id:
            raise UserError(_("請選擇開票銀行。"))

    def _create_bill_if_needed(self):
        if self.journal_type == 'check':
            # 檢查是否已經存在相同參考號的票據
            existing_bill = self.env['account.bill'].search([
                ('invoice_move', '=', self.move_id.id),
                ('bill_number', '=', self.check_number),
                ('state', '=', 'confirmed')
            ], limit=1)
            
            if existing_bill:
                _logger.info('找到現有票據，ID: %s', existing_bill.id)
                return existing_bill
                
            bill = self._create_bill()
            if bill:
                _logger.info('新建票據，ID: %s', bill.id)
                self.check_number = bill.id
                return bill
        return False

   
    def _create_bill(self):
        try:
            # 添加上下文防止自動創建會計分錄
            self = self.with_context(
                skip_account_move_synchronization=True,
                no_create_payment=True,
                no_create_move=False,
                no_create_bill_accounting=False
            )
            _logger.info('創建票據，上下文: %s', self._context)
            # 先計算金額
            amount = self.amount
            _logger.info('計算出的總金額: %s', amount)

            # 獲取預設票據科目
            if self.bill_type == 'receivable':
                notes_account_id = int(self.env['ir.config_parameter'].sudo().get_param(
                    'account.default_notes_receivable_account', '0'
                ))
                if not notes_account_id:
                    raise UserError(_('尚未設定預設應收票據科目，請先在設定中設定。'))
            else:
                notes_account_id = int(self.env['ir.config_parameter'].sudo().get_param(
                    'account.default_notes_payable_account', '0'
                ))
                if not notes_account_id:
                    raise UserError(_('尚未設定預設應付票據科目，請先在設定中設定。'))

            # 創建票據基本資料 - 確保有票據號碼
            check_number = self.check_number or self._generate_check_number()
            vals = {
                'bill_number': check_number,
                'issue_date': self.issue_date,
                'due_date': self.due_date,
                'bill_type': self.bill_type,
                'amount': abs(amount),
                'currency_id': self.currency_id.id,
                'bank_id': self.bank_id.id,
                'issuer': self.env.user.id,
                'journal_id': self.journal_id.id,  # 使用選擇的日記帳
                'invoice_move': self.move_id.id or self.env.context.get('active_id'),
                'state': 'confirmed',
                'notes_receivable_account_id': notes_account_id if self.bill_type == 'receivable' else False,
                'notes_payable_account_id': notes_account_id if self.bill_type == 'payable' else False,
            }

            bill = self.env['account.bill'].sudo().create(vals)
            
            if not bill.line_ids:
                # 處理分錄
                account_lines = []
                if self.bill_type == 'payable':
                    account_lines = bill.invoice_move.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'liability_payable' and l.credit > 0
                    )
                else:
                    account_lines = bill.invoice_move.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'asset_receivable' and l.debit > 0
                    )

                notes_account = self.env['account.account'].browse(notes_account_id)
                _logger.info('找到的帳款分錄: %s', account_lines)
                _logger.info('找到的票據科目: %s', notes_account)

                if account_lines and notes_account.exists():
                    actual_amount = sum(abs(line.amount_residual) for line in account_lines)
                    _logger.info('實際金額: %s', actual_amount)

                    if self.bill_type == 'payable':
                        lines_vals = [
                            (0, 0, {
                                'name': f'開立票據 - {bill.invoice_move.name}',
                                'account_id': account_lines[0].account_id.id,
                                'debit': actual_amount,
                                'credit': 0.0,
                            }),
                            (0, 0, {
                                'name': f'記錄應付票據 - {bill.invoice_move.name}',
                                'account_id': notes_account.id,
                                'debit': 0.0,
                                'credit': actual_amount,
                            })
                        ]
                        _logger.info('創建應付票據分錄: %s', lines_vals)
                    else:
                        lines_vals = [
                            (0, 0, {
                                'name': f'收到票據 - {bill.invoice_move.name}',
                                'account_id': notes_account.id,
                                'debit': actual_amount,
                                'credit': 0.0,
                            }),
                            (0, 0, {
                                'name': f'沖銷應收帳款 - {bill.invoice_move.name}',
                                'account_id': account_lines[0].account_id.id,
                                'debit': 0.0,
                                'credit': actual_amount,
                            })
                        ]

                    # 更新票據金額和分錄明細 (但不建立實際會計分錄)
                    bill.with_context(skip_amount_computation=True).write({
                        'amount': actual_amount,
                        'line_ids': lines_vals
                    })

            _logger.info('票據已建立，ID: %s，金額: %s，類型: %s', bill.id, bill.amount, bill.bill_type)
            _logger.info('票據將在兌現時才建立會計分錄')
            return bill

        except Exception as e:
            _logger.error('建立票據時發生錯誤: %s', str(e))
            raise UserError(_('建立票據失敗: %s') % str(e))

    def _generate_check_number(self):
        today = datetime.today().strftime('%Y%m%d')
        last_check = self.env['account.bill'].search([
            ('bill_number', 'like', f'{today}%')
        ], order='bill_number desc', limit=1)

        if last_check:
            last_number = int(last_check.bill_number[-4:])
            new_number = last_number + 1
        else:
            new_number = 1

        return f"{today}{str(new_number).zfill(4)}"

    @api.onchange('journal_type')
    def _onchange_journal_type(self):
        if self.journal_type == 'check':
            # self.check_number = self._generate_check_number()
            pass
        else:
            self.check_number = False






    

    

    
