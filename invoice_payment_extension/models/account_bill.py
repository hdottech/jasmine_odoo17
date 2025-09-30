from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import UserError,ValidationError
from odoo.tools.float_utils import float_compare
import logging
_logger = logging.getLogger(__name__)
class AccountBill(models.Model):
    _name = 'account.bill'
    _description = '票據模型'
    _inherit = ['mail.thread', 'mail.activity.mixin']  

    name = fields.Char(
        string='Number',
        compute='_compute_name', inverse='_inverse_name', readonly=False, store=True,
        copy=False,
        tracking=True,
        index='trigram',
    )
    bill_number = fields.Char(string='票據號碼',copy=False, readonly=True, default='New', tracking=True)
    date = fields.Date(string='Date', default=fields.Date.today)
    issue_date = fields.Date(string='開票日', required=True)
    cash_date = fields.Date(string='兌現日')
    due_date = fields.Date(string='到期日', required=True)
    
    bill_type = fields.Selection([
        ('receivable', '應收票據'),
        ('payable', '應付票據')
    ], string='票據種類', required=True)

    color = fields.Integer(string='顏色', compute='_compute_bill_type_color')
    active = fields.Boolean(default=True)
    issuer = fields.Many2one('res.users', string='開票人', default=lambda self: self.env.user, required=True)
    bank_id = fields.Many2one('res.bank', string='開票銀行', required=True)
    def _default_amount(self):
        return 0.0
    amount = fields.Monetary(
        string='開票金額',
        required=True,
        currency_field='currency_id',
        default=_default_amount,
    )
    line_amounts = fields.Monetary(
        string='分錄金額',
        compute='_compute_line_amounts',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one('res.currency', string='幣別', required=True, default=lambda self: self.env.user.company_id.currency_id)  
    account_id = fields.Many2one('account.account', string='日記帳分錄') 
    invoice_move = fields.Many2one('account.move', string='關聯憑單', help="關聯的應收/應付憑單",tracking=True) 
    move_line_ids = fields.One2many(related='invoice_move.line_ids', string='分錄行項目', readonly=True) 
    journal_id = fields.Many2one(
        'account.journal', 
        string='日記帳',      
        required=True,  
        tracking=True,  
    )
    line_ids = fields.One2many('account.bill.line', 'bill_id', string='日記帳明細')
    computed_amount = fields.Float(compute='_compute_amount', store=True)
    notes_receivable_account_id = fields.Many2one(
        'account.account',
        string='應收票據科目',
        domain=[('deprecated', '=', False)],
        help='應收票據預設科目'
    )
    notes_payable_account_id = fields.Many2one(
        'account.account',
        string='應付票據科目',
        domain=[('deprecated', '=', False)],
        help='應付票據預設科目'
    )
    move_id1 = fields.Many2one(
        'account.move',
        string='票據分錄',
        copy=False,
        tracking=True,
    )
    move_lines = fields.One2many(
        related='move_id1.line_ids',
        string='分錄明細',
        readonly=True
    ) 
    move_name = fields.Char(related='invoice_move.name', string='原票據名稱', store=True)
    payment_id = fields.Many2one('account.payment', string='付款',tracking=True,help="關聯的付款單")
    company_id = fields.Many2one('res.company', string='公司', related='move_id1.company_id', store=True, readonly=True)
    cancel_date = fields.Date(string='註銷日期')
    cancel_reason = fields.Text(string='註銷原因')
    state = fields.Selection([
        ('confirmed', '草稿'),
        ('cashed', '已兌現'),
        ('void', '已註銷'),
        ('cancelled', '已取消')
    ], string='狀態', default='confirmed', tracking=True)
    message_ids = fields.One2many('mail.message', 'res_id', domain=lambda self: [('model', '=', self._name)], string='聊天記錄')
    activity_ids = fields.One2many('mail.activity', 'res_id', domain=lambda self: [('res_model', '=', self._name)], string='活動')
    note = fields.Text(string='備註')
    show_cashed_badge = fields.Boolean(
        string='Show Cashed Badge',
        compute='_compute_show_cashed_badge',
    )
    def _compute_show_cashed_badge(self):
        for record in self:
            record.show_cashed_badge = record.state == 'cashed'


    @api.depends('line_ids.debit', 'line_ids.credit')
    def _compute_line_amounts(self):
        for record in self:
            if record.bill_type == 'payable':
                record.line_amounts = sum(record.line_ids.mapped('credit'))
            else:
                record.line_amounts = sum(record.line_ids.mapped('debit'))
    @api.onchange('amount')
    def _onchange_amount(self):
        if self.amount and self.invoice_move:
            self._onchange_invoice_move()

    @api.model_create_multi
    def _create_bill(self):
        lines = self.env['account.move.line'].browse(self.env.context.get('active_ids', []))
        amount = sum(abs(line.amount_residual) for line in lines)
        
        _logger.info('計算出的總金額: %s', amount)

        # 檢查 journal_id 是否存在
        if not self.journal_id:
            raise UserError(_('請選擇一個日記帳。'))

        # 檢查 move_id 或 active_id 是否有效
        invoice_move_id = self.move_id.id or self.env.context.get('active_id')
        if not invoice_move_id:
            raise UserError(_('未能獲取有效的發票分錄 ID。'))

        vals = {
            'bill_number': self.check_number,
            'issue_date': self.issue_date,
            'due_date': self.due_date,
            'bill_type': self.bill_type if hasattr(self, 'bill_type') else False,
            'amount': amount,
            'currency_id': self.currency_id.id,
            'bank_id': self.bank_id.id,
            'issuer': self.env.user.id,
            'journal_id': self.journal_id.id,
            'invoice_move': invoice_move_id,
            'state': 'confirmed',
        }

        # 使用 sudo() 確保有足夠權限
        bill = self.env['account.bill'].sudo().create(vals)
        _logger.info('票據已建立，ID: %s，金額: %s', bill.id, bill.amount)

        # 確認分錄已經創建
        if not bill.line_ids:
            # 獲取應收帳款分錄
            receivable_line = bill.invoice_move.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable'
            )

            # 取得預設票據科目
            notes_account_id = int(self.env['ir.config_parameter'].sudo().get_param(
                'account.default_notes_receivable_account', '0'))
            if not notes_account_id:
                raise UserError(_('請先在會計設定中設定預設票據科目！'))

            # 檢查科目是否有效
            notes_account = self.env['account.account'].browse(notes_account_id)
            if not notes_account.exists():
                raise UserError(_('預設的票據科目 ID (%s) 無效，請確認設置。') % notes_account_id)

            if receivable_line:
                lines_vals = [
                    (0, 0, {
                        'name': f'收到票據 - {bill.invoice_move.name}',
                        'account_id': notes_account.id,
                        'debit': amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': f'沖銷應收帳款 - {bill.invoice_move.name}',
                        'account_id': receivable_line[0].account_id.id,
                        'debit': 0.0,
                        'credit': amount,
                    })
                ]
                bill.write({'line_ids': lines_vals})
                _logger.info('分錄已成功建立，分錄資料: %s', lines_vals)

        # 強制更新顯示金額
        self.env.cr.commit()
        _logger.info('交易已提交至資料庫。')

        return bill
    
    @api.model
    def create(self, vals):
        # 檢查是否是從票據付款創建的
        skip_accounting_entry = self._context.get('skip_account_move_synchronization') or \
                            self._context.get('no_create_move')
                            
        if skip_accounting_entry:
            _logger.info('從付款登記創建票據，跳過會計分錄的創建')
        
        bill = super().create(vals)
        
        if bill.invoice_move and not skip_accounting_entry:
            bill.invoice_move._compute_bill_payment_state()
            bill.invoice_move.flush_recordset(['payment_state', 'bill_payment_state'])
        
        return bill

    def write(self, vals):
        result = super(AccountBill, self).write(vals)
        if 'state' in vals or 'invoice_move' in vals:
            for bill in self:
                if bill.invoice_move:
                    bill.invoice_move._compute_bill_payment_state()  # 手動觸發重新計算
                    bill.invoice_move.flush_recordset(['payment_state', 'bill_payment_state'])  # 強制更新
        return result

    def unlink(self):
        for record in self:
            if record.state not in ['confirmed', 'cancelled']:
                raise UserError(_('只能刪除草稿或已取消的票據。'))
            if record.move_id1:
                record.move_id1.unlink()
        return super().unlink()
        

    def _compute_name(self):
        for record in self:
            record.name = record.bill_number

    def _inverse_name(self):
        for record in self:
            record.bill_number = record.name

    def cash_payment(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('票據必須為確認狀態才能兌現。'))
        self.write({'state': 'cashed', 'cash_date': fields.Date.today()})
        return {
            'name': _('確認兌現'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bill.cash.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bill_id': self.id,
                'default_amount': self.amount,
                'default_communication': self.invoice_move.name if self.invoice_move else '',
            },
        }

    def action_cancel_cash(self):
        """取消兌現時檢查是否有關聯的付款記錄"""
        for record in self:
            # 檢查是否有關聯的付款記錄
            if record.payment_id:
                raise UserError(_('此票據有關聯的付款記錄，無法取消兌現。'))
            record.write({
                'state': 'confirmed',  # 回到草稿狀態
                'cash_date': False     # 清除兌現日期
            })
    def action_void(self):
        """處理註銷動作"""
        return {
            'name': _('票據註銷'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bill.void.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_bill_id': self.id}
        }
    
    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        self.account_id = False  # Reset account_id when journal_id changes
        return {'domain': {'account_id': [('journal_id', '=', self.journal_id.id)]}}
    

    def action_cancel(self):
        """取消票據"""
        for record in self:
            if record.state != 'confirmed':
                raise UserError(_('只有草稿狀態的票據可以取消。'))
            record.write({'state': 'cancelled'})

    @api.model
    def _get_default_notes_account(self):
        """獲取預設票據科目"""
        if self.bill_type == 'receivable':
            return int(self.env['ir.config_parameter'].sudo().get_param(
                'account.default_notes_receivable_account', '0'))
        else:
            return int(self.env['ir.config_parameter'].sudo().get_param(
                'account.default_notes_payable_account', '0'))
    def _prepare_journal_entries(self):
        self.ensure_one()
        journal_entries = []
        if self.bill_type == 'receivable':
            journal_entries = [
                (0, 0, {
                    'name': '應收票據',
                    'account_id': self.env['account.account'].search([('code', '=', '111102')], limit=1).id,  # 假設應收票據科目代碼為1103
                    'debit': self.amount,
                    'credit': 0,
                }),
                (0, 0, {
                    'name': '應收帳款',
                    'account_id': self.env['account.account'].search([('code', '=', '1101')], limit=1).id,  # 假設應收帳款科目代碼為1101
                    'debit': 0,
                    'credit': self.amount,
                })
            ]
        elif self.bill_type == 'payable':
            journal_entries = [
                (0, 0, {
                    'name': '應付票據',
                    'account_id': self.env['account.account'].search([('code', '=', '2103')], limit=1).id,  # 假設應付票據科目代碼為2103
                    'debit': self.amount,
                    'credit': 0,
                }),
                (0, 0, {
                    'name': '應付帳款',
                    'account_id': self.env['account.account'].search([('code', '=', '2101')], limit=1).id,  # 假設應付帳款科目代碼為2101
                    'debit': 0,
                    'credit': self.amount,
                })
            ]
        return journal_entries

    def action_confirm(self):
        self.ensure_one()
        # 檢查是否應該跳過會計分錄的創建
        if self._context.get('skip_account_move_synchronization') or \
            self._context.get('no_create_move'):
                _logger.info('跳過為票據創建會計分錄')
                self.write({'state': 'confirmed'})
                return True
        move_lines = self._prepare_journal_entries()
        if move_lines:
            move = self.env['account.move'].create({
                'journal_id': self.journal_id.id,
                'date': fields.Date.today(),
                'ref': self.bill_number,
                'line_ids': move_lines,
            })
            self.write({
                'state': 'confirmed',
                'invoice_move': move.id,  # 原 move_id2
            })
        return True

    @api.constrains('line_ids')
    def _check_balance(self):
        for record in self:
            if record.line_ids:
                total_debit = sum(record.line_ids.mapped('debit'))
                total_credit = sum(record.line_ids.mapped('credit'))
                if float_compare(total_debit, total_credit, precision_rounding=record.currency_id.rounding) != 0:
                    raise ValidationError(_('借貸必須相等！'))
                
                
    @api.depends('invoice_move')
    def _compute_amount(self):
        for record in self:
            if not record.amount:  # 只在金額為空時才計算
                if record.invoice_move:
                    if record.bill_type == 'payable':
                        account_lines = record.invoice_move.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'liability_payable'
                        )
                    else:
                        account_lines = record.invoice_move.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable'
                        )
                    record.amount = abs(sum(account_lines.mapped('amount_residual')))
                else:
                    record.amount = 0.0  
    def _onchange_invoice_move(self):
        """當選擇憑單時自動產生對應的分錄"""
        _logger.info('=== _onchange_invoice_move 開始執行 ===')
        if self._context.get('skip_account_move_synchronization') or \
            self._context.get('no_create_move'):
                _logger.info('跳過為票據創建分錄明細')
                return

        # 清空現有的分錄
        self.line_ids = [(5, 0, 0)]

        if not self.invoice_move or not self.amount:
            return

        # 搜尋應收帳款分錄
        receivable_line = self.invoice_move.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
        )
        _logger.info('找到的應收帳款分錄: %s', receivable_line)

        if not receivable_line:
            _logger.info('未找到應收帳款分錄')
            return

        # 取得預設票據科目
        notes_account = self._get_default_notes_account()
        if not notes_account:
            _logger.warning('未找到預設票據科目')
            return

        # 準備分錄資料
        _logger.info('準備分錄資料')
        new_lines = [
            (0, 0, {
                'name': f'收到票據 - {self.invoice_move.name}',
                'account_id': notes_account.id,
                'debit': self.amount,
                'credit': 0.0,
            }),
            (0, 0, {
                'name': f'沖銷應收帳款 - {self.invoice_move.name}',
                'account_id': receivable_line.account_id.id,
                'debit': 0.0,
                'credit': self.amount,
            })
        ]
        
        # 寫入分錄
        self.line_ids = new_lines
        _logger.info('分錄已寫入: %s', new_lines)
class AccountBillLine(models.Model):
    _name = 'account.bill.line'
    _description = '票據日記帳明細'

    bill_id = fields.Many2one('account.bill', string='票據')
    account_id = fields.Many2one(
        'account.account', 
        string='會計科目', 
        required=True,
        domain="[('deprecated', '=', False), ('account_type', 'not in', ('asset_receivable', 'liability_payable'))]"
    )
    name = fields.Char(string='摘要', required=True)
    debit = fields.Monetary(string='借方金額', default=0.0)
    credit = fields.Monetary(string='貸方金額', default=0.0)
    currency_id = fields.Many2one(related='bill_id.currency_id')
    
    @api.onchange('debit')  
    def _onchange_debit(self):
        if self.debit != 0:
            self.credit = 0

    @api.onchange('credit')
    def _onchange_credit(self):
        if self.credit != 0:
            self.debit = 0

    @api.constrains('debit', 'credit')
    def _check_debit_credit(self):
        for line in self:
            if line.debit * line.credit != 0:
                raise ValidationError(_('一個分錄行不能同時有借貸金額'))
    @api.constrains('due_date', 'issue_date')
    def _check_due_date(self):
        for record in self:
            if record.due_date < record.issue_date:
                raise ValidationError(_('到期日不能早於開票日。'))
            
    @api.constrains('bill_type', 'invoice_move')
    def _check_bill_type(self):
        for record in self:
            if record.invoice_move:
                # 檢查票據類型是否與來源憑單匹配
                if record.invoice_move.move_type in ['out_invoice', 'out_refund']:
                    if record.bill_type != 'receivable':
                        raise ValidationError(_('應收憑單只能建立應收票據。'))
                elif record.invoice_move.move_type in ['in_invoice', 'in_refund']:
                    if record.bill_type != 'payable':
                        raise ValidationError(_('應付憑單只能建立應付票據。'))
                    
    # 檢查關聯分錄
    def action_view_move_entries(self):
        """查看相關分錄"""
        self.ensure_one()
        
        # 收集所有相關的分錄
        moves = self.env['account.move']
        if self.move_id1:
            moves |= self.move_id1
        if self.payment_id and self.payment_id.move_id:
            moves |= self.payment_id.move_id
        
        action = {
            'name': _('關聯分錄'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
        }
        
        if len(moves) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': moves.id,
            })
        else:
            action.update({
                'domain': [('id', 'in', moves.ids)],
            })
            
        return action