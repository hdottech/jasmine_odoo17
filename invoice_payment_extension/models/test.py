from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import UserError
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
    bill_number = fields.Char(string='Bill Number', required=True, copy=False, readonly=True, default='New', tracking=True)
    date = fields.Date(string='Date', default=fields.Date.today)
    issue_date = fields.Date(string='開票日', required=True)
    cash_date = fields.Date(string='兌現日', required=True)
    due_date = fields.Date(string='到期日', required=True)
    
    bill_type = fields.Selection([
        ('receivable', '應收票據'),
        ('payable', '應付票據')
    ], string='票據種類', required=True, store=True)

    color = fields.Integer(string='顏色', compute='_compute_bill_type_color')
    active = fields.Boolean(default=True)
    issuer = fields.Many2one('res.users', string='開票人', default=lambda self: self.env.user, required=True)
    bank_id = fields.Many2one('res.bank', string='開票銀行', required=True)
    amount = fields.Monetary(string='開票金額', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='幣別', required=True, default=lambda self: self.env.user.company_id.currency_id)
    journal_id = fields.Many2one('account.journal', string='日記帳', required=True)
    account_id = fields.Many2one('account.account', string='日記帳分錄')
    company_id = fields.Many2one('res.company', string='公司', default=lambda self: self.env.company)
    move_id1= fields.One2many('account.move.line', 'bill_id', string='對應單號One2many') #票據對應單號
    move_id2 = fields.Many2one('account.move', string='相關分錄')
    partner_id = fields.Many2one('res.partner', string='客户', related='move_id2.partner_id', store=True)
    @api.depends('move_id2')
    def _compute_move_lines(self):
        for record in self:
            if record.move_id2:
                record.move_line_ids = record.move_id2.line_ids
            else:
                record.move_line_ids = False
    move_line_ids = fields.One2many('account.move.line', compute='_compute_move_lines', string='分錄行項目')
    move_id = fields.Many2one('account.move.line', string='對應單號', required=False) #票據對應單號
    move_name = fields.Char(related='move_id.move_id.name', string='原票據名稱', store=True, ondelete='set null') #related='move_id.move_id.name',
    payment_id = fields.Many2one('account.payment', string='付款')
    company_id = fields.Many2one('res.company', string='公司', related='move_id.company_id', store=True, readonly=True)
    state = fields.Selection([
        ('draft', '草稿'),
        ('confirmed', '已過帳票據'),
        ('cashed', '已兌現'),
        ('cancelled', '已取消')
    ], string='狀態', default='confirmed')
    line_ids = fields.One2many('account.move.line', 'bill_id', string='日記帳項目')
    message_ids = fields.One2many('mail.message', 'res_id', domain=lambda self: [('model', '=', self._name)], string='聊天記錄')
    activity_ids = fields.One2many('mail.activity', 'res_id', domain=lambda self: [('res_model', '=', self._name)], string='活動')
    note = fields.Text(string='備註')
    total_debit = fields.Monetary(string="借方總計", compute="_compute_totals", store=True)
    total_credit = fields.Monetary(string="貸方總計", compute="_compute_totals", store=True)
    # 生成票據
    @api.model
    def create(self, vals):
        # 生成唯一的票據編號
        if vals.get('bill_number', _('New')) == _('New'):
            today = datetime.today().strftime('%Y%m%d')
            last_bill = self.search([('bill_number', 'like', today + '%')], order='bill_number desc', limit=1)
            if last_bill:
                last_number = int(last_bill.bill_number[-4:]) + 1
            else:
                last_number = 1
            vals['bill_number'] = f"{today}{str(last_number).zfill(4)}"
        
        # 如果沒有提供 move_id，創建一個新的 account.move 和 account.move.line
        if not vals.get('move_id'):
            # 創建 account.move
            move = self.env['account.move'].create({
                'name': vals.get('bill_number', 'New Bill'),
                'journal_id': vals.get('journal_id') or self.env['account.journal'].search([], limit=1).id,
                'date': fields.Date.today(),
            })
            
            # 創建關聯的 account.move.line
            move_line = self.env['account.move.line'].create({
                'move_id': move.id,
                'name': vals.get('bill_number', 'New Bill'),
                'account_id': self.env['account.account'].search([], limit=1).id,
                'debit': 0,
                'credit': 0,
            })
            vals['move_id'] = move_line.id

        # 創建紀錄
        record = super(AccountBill, self).create(vals)
        
        # 確保更新後的紀錄也同步了 move_id1 字段
        if record.move_id:
            record.move_id1 = [(6, 0, [record.move_id.id])]
        
        return record
        
    def _compute_name(self):
        for record in self:
            record.name = record.bill_number

    def _inverse_name(self):
        for record in self:
            record.bill_number = record.name

    def cash_payment(self):
        self.ensure_one()
        return {
            'name': _('確認兌現'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bill.cash.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_bill_id': self.id},
        }

    def action_confirm_cash(self):
        self.write({'state': 'cashed'}) 

    def action_cancel_cash(self):
        self.write({'state': 'confirmed'})
    
    
    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        self.account_id = False  # Reset account_id when journal_id changes
        return {'domain': {'account_id': [('journal_id', '=', self.journal_id.id)]}}
    
    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def archive_record(self):
    # 將記錄存檔
        self.write({'active': False})

    def action_confirm(self):
        self.ensure_one()
        if not self.move_id2 and self.move_id2:
            receivable_line = self.original_move_id.line_ids.filtered(lambda l: l.account_id.internal_type == 'receivable')
            if not receivable_line:
                raise UserError(_("找不到原始应收账款行"))

            move_vals = {
                'journal_id': self.journal_id.id,
                'date': self.issue_date,
                'ref': f'票据确认 - {self.bill_number}',
                'line_ids': [
                    (0, 0, {
                        'account_id': self.env['account.account'].search([('code', '=', '101401')], limit=1).id,  # 应收票据
                        'name': f'票据 {self.bill_number}',
                        'partner_id': self.partner_id.id,
                        'debit': self.amount,
                        'credit': 0,
                    }),
                    (0, 0, {
                        'account_id': receivable_line.account_id.id,  # 使用原始应收账款的科目
                        'name': f'票据 {self.bill_number}',
                        'partner_id': self.partner_id.id,
                        'debit': 0,
                        'credit': self.amount,
                    })
                ]
            }
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            self.write({
                'state': 'confirmed',
                'move_id2': move.id
            })
        return True
    @api.onchange('move_id')
    def _onchange_original_move(self):
        if self.original_move_id:
            self.amount = self.original_move_id.amount_residual