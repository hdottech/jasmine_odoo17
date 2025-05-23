from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    einvoice_user_id = fields.Char(string="汎宇 UserID")
    einvoice_auth = fields.Char(string="汎宇 Auth")
    einvoice_apikey = fields.Char(string="汎宇 API Key")
    einvoice_endpoint = fields.Char(string="發票 API URL", default="https://webtest.einvoice.com.tw/einv/openInvoice")
