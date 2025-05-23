from odoo import models, fields, api, _

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    bill_reference = fields.Many2one('account.bill', string='票據')  