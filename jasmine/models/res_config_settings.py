# -*- coding: utf-8 -*-

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # REST API 設定
    fanyuu_user_id = fields.Char(
        string='汎宇 User ID',
        config_parameter='fanyuu.user_id'
    )
    fanyuu_auth = fields.Char(
        string='汎宇 Auth 密碼',
        config_parameter='fanyuu.auth'
    )
    fanyuu_apikey = fields.Char(
        string='汎宇 API Key',
        config_parameter='fanyuu.apikey'
    )
    fanyuu_company_id = fields.Char(
        string='公司統編',
        config_parameter='fanyuu.company_id'
    )
    fanyuu_endpoint = fields.Char(
        string='API 端點',
        config_parameter='fanyuu.endpoint',
        default='https://webtest.einvoice.com.tw/einv/openInvoice'
    )

    # POS API 設定
    fanyuu_pos_company_id = fields.Char(
        string='POS 公司統編',
        config_parameter='fanyuu.pos_company_id',
        default='83293137'
    )
    fanyuu_pos_id = fields.Char(
        string='POS ID',
        config_parameter='fanyuu.pos_id',
        default='1001'
    )
    fanyuu_pos_channel_key = fields.Char(
        string='通道金鑰',
        config_parameter='fanyuu.pos_channel_key',
        default='dequx8NU7Wf9GzGmpsv9'
    )
    fanyuu_pos_endpoint = fields.Selection([
        ('test', '測試環境'),
        ('prod', '正式環境')
    ], string='環境選擇', 
       config_parameter='fanyuu.pos_endpoint',
       default='test')

    # 系統行為設定
    fanyuu_api_type = fields.Selection([
        ('rest_api', 'REST API'),
        ('pos_json', 'POS JSON API')
    ], string='API 類型',
       config_parameter='fanyuu.api_type',
       default='pos_json')

    fanyuu_allow_local_fallback = fields.Boolean(
        string='允許本地回退',
        config_parameter='fanyuu.allow_local_fallback',
        default=False,
        help='當汎宇取號失敗時，是否允許回退到本地取號'
    )
    
    fanyuu_auto_upload_invoice = fields.Boolean(
        string='發票開立時自動上傳到汎宇',
        config_parameter='fanyuu.auto_upload_invoice',
        default=True,
        help='啟用後，發票開立時會自動上傳到汎宇系統'
    )

    # 進階設定
    fanyuu_error_strategy = fields.Selection([
        ('stop', '中斷'),
        ('continue', '繼續')
    ], string='錯誤處理策略', 
       config_parameter='fanyuu.error_strategy', 
       default='continue')

    fanyuu_retry_count = fields.Integer(
        string='重試次數',
        config_parameter='fanyuu.retry_count',
        default=3
    )

    fanyuu_timeout = fields.Integer(
        string='超時時間（秒）',
        config_parameter='fanyuu.timeout',
        default=30
    )