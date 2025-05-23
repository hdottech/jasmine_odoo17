from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fanyuu_user_id = fields.Char(string="汎宇 User ID", config_parameter="fanyuu.user_id")
    fanyuu_auth = fields.Char(string="汎宇 Auth 密碼", config_parameter="fanyuu.auth")
    fanyuu_apikey = fields.Char(string="汎宇 API Key", config_parameter="fanyuu.apikey")
    fanyuu_company_id = fields.Char(string="公司統編 (companyID)", config_parameter="fanyuu.company_id")
    fanyuu_endpoint = fields.Char(
        string="API 端點網址",
        config_parameter="fanyuu.endpoint",
        default="https://webtest.einvoice.com.tw/einv/openInvoice"
    )