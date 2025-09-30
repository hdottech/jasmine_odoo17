from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    notes_receivable_account_id = fields.Many2one(
        'account.account',
        string='預設應收票據科目',
        domain=[('deprecated', '=', False)],
        config_parameter='account.default_notes_receivable_account'
    )
    
    notes_payable_account_id = fields.Many2one(
        'account.account',
        string='預設應付票據科目',
        domain=[('deprecated', '=', False)],
        config_parameter='account.default_notes_payable_account'
    )