from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import base64
import csv
import io
from datetime import datetime
from odoo.addons.jasmine.services.fanyuu_api import FanyuuAPI
import logging
_logger = logging.getLogger(__name__)

class InvoiceInformation(models.Model):
    _name = 'invoice.information'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = '電子發票資訊'
    _rec_name = 'invoice_number'

    account_move_ids = fields.One2many('account.move', 'invoice_information_id', 
                                      string='關聯發票', readonly=True)
    order_id = fields.Char(string='銷貨單號', required=True)
    donate_mark = fields.Selection([('0', '不捐贈'), ('1', '捐贈')], string='捐贈註記', required=True, default='0')
    print_mark = fields.Selection([('Y', '列印'), ('N', '不列印')], string='是否列印', required=True, default='Y')
    npoban = fields.Char(string='捐贈碼', size=10)
    freetax_sales_amount = fields.Integer(string='免稅銷售額合計', default=0)
    zerotax_sales_amount = fields.Integer(string='零稅率銷售額合計', default=0)
    notify_email = fields.Char(string='通知信箱')
    unit_code = fields.Char(string='開立單位')

    # 關聯貸記單
    credit_note_ids = fields.One2many(
        'account.move', 
        compute='_compute_credit_notes',
        string='關聯貸記單',
        help='與此發票相關的貸記單'
    )
    has_credit_note = fields.Boolean(
        string='有貸記單',
        compute='_compute_credit_notes',
        store=True,
        help='是否有關聯的貸記單'
    )

    # 折讓
    # is_allowance = fields.Boolean(string='是否為折讓單', default=False)
    # allowance_type = fields.Selection([('1', '買方開立'), ('2', '賣方開立')], string='折讓類型')
    # allowance_number = fields.Char(string='折讓單號碼')
    # original_invoice_number = fields.Char(string='原發票號碼')
    # original_invoice_date = fields.Date(string='原發票日期')

    # 與設定檔關聯（選填，方便切換環境）
    einvoice_env = fields.Selection([('test', '測試環境'), ('prod', '正式環境')], default='test', string='API 環境')
    # 關聯字段
    invoice_line_ids = fields.One2many('invoice.line', 'invoice_id', string='發票明細行', readonly=True)
    invoice_track_id = fields.Many2one('invoice.track', string='發票字軌', required=True, readonly=True)

    # H 區段欄位 - 發票頭
    seller_tax_id = fields.Char(string='賣方統一編號', size=10, required=True, readonly=True)
    seller_name = fields.Char(string='賣方公司名稱', size=60, required=True, readonly=True)
    seller_address = fields.Char(string='賣方公司地址', size=100, readonly=True)
    seller_phone = fields.Char(string='賣方公司電話', size=26, readonly=True)
    operation_type = fields.Selection([
        ('', '開立發票'),
        ('REJ', '退回發票'),
        ('CAN', '作廢發票'),
        ('CRE', '已更正'), 
        ('CRE_ALW', '開立折讓')
    ], string='發票作業類別', default='', size=10, readonly=True)

    # M 區段欄位 - 發票主資訊
    invoice_number = fields.Char(string='發票號碼', size=20, required=True, readonly=True, 
                                help='含發票字軌共10碼')
    invoice_date = fields.Datetime(string='發票日期', required=True, readonly=True,
                                 help='請輸入西元年時間，如未填入時間，則系統會自動帶入 00:00:00')
    invoice_type = fields.Selection([
        ('07', '一般稅額計算之電子發票'),
        ('08', '特種稅額計算之電子發票')
    ], string='發票類別', required=True, default='07', size=2, readonly=True)
    buyer_tax_id = fields.Char(string='買方統一編號', size=10, readonly=True)
    buyer_name = fields.Char(string='買方公司名稱', size=60, readonly=True)
    buyer_address = fields.Char(string='買方公司地址', size=100, readonly=True)
    tax_type = fields.Selection([
        ('1', '應稅'),
        ('2', '零稅率'),
        ('3', '免稅'),
        ('4', '應稅(特種)')
    ], string='課稅別', required=True, default='1', size=1, readonly=True)
    tax_rate = fields.Float(string='稅率', digits=(3,2), help='免填%字樣（僅輸入數字）', readonly=True)
    sales_amount = fields.Integer(string='銷售額合計', size=12, readonly=True)
    tax_amount = fields.Integer(string='營業稅額', size=12, readonly=True)
    total_amount = fields.Integer(string='總計', size=12, readonly=True)
    
    # 通關與零稅率欄位 - 新增
    customs_clearance = fields.Selection([
        ('1', '非經海關出口'),
        ('2', '經海關出口')
    ], string='通關方式註記', size=1, readonly=True, 
    help='若為零稅率發票，此為必填欄位')
    
    zero_tax_mark = fields.Selection([
        ('1', '符合加值型及非加值型營業稅法第7條第4款規定(買受人為保稅區營業人)'),
        ('2', '符合加值型及非加值型營業稅法第7條第7款規定(買受人為遠洋漁業營業人)'),
        ('3', '符合自由貿易港區設置管理條例第28條第1項第1款及第4款規定(買受人為自由貿易港區營業人)'),
        ('4', '其他')
    ], string='買受人簽署適用零稅率註記', size=1, readonly=True, 
    help='若為零稅率發票，此欄位可選擇填入, 若非零稅率發票則不需填')
    
    remark = fields.Text(string='總備註', size=200, readonly=True)
    
    zero_tax_reason = fields.Selection([
        ('71', '第一款 外銷貨物'),
        ('72', '第二款 與外銷有關之勞務，或在國內提供而在國外使用之勞務'),
        ('74', '第四款 銷售與保稅區營業人供營運之貨物或勞務'),
        ('75', '第五款 國際間之運輸；但外國運輸事業在中華民國境內經營國際運輸業務者，應以各該國對中華民國國際運輸事業予以相等待遇或免徵類似稅捐者為限'),
        ('76', '第六款 國際運輸用之船舶、航空器及遠洋漁船'),
        ('77', '第七款 銷售與國際運輸用之船舶、航空器及遠洋漁船所使用之貨物或修繕勞務'),
        ('78', '第八款 保稅區營業人銷售與課稅區營業人未輸往課稅區而直接出口之貨物'),
        ('79', '第九款 保稅區營業人銷售與課稅區營業人存入自由港區事業或海關管理之保稅倉庫、物流中心以供外銷之貨物')
    ], string='零稅率原因', size=2, readonly=True, help='若為零稅率發票，此為必填欄位')
    
    related_number = fields.Char(string='相關號碼', size=20, readonly=True)
    buyer_customer_number = fields.Char(string='買方客戶編號', size=20, readonly=True)
    business_role = fields.Char(string='營業人角色註記', size=40, readonly=True)
    combined_mark = fields.Char(string='彙開註記', size=1, readonly=True, help='若有彙開註記，則打*')
    exchange_rate = fields.Float(string='匯率', digits=(8,4), readonly=True, help='整數8＋小數4')
    currency = fields.Selection([
        ('TWD', '新台幣'),
        ('USD', '美金'),
        ('GBP', '英鎊'),
        ('DEM', '德國馬克'),
        ('AUD', '澳大利亞幣'),
        ('HKD', '港幣'),
        ('SGD', '新加坡幣'),
        ('CAD', '加拿大幣'),
        ('CHF', '瑞士法郎'),
        ('MYR', '馬來西亞幣'),
        ('FRF', '法國法郎'),
        ('BEF', '比利時法郎'),
        ('NLG', '荷蘭幣'),
        ('SEK', '瑞典幣'),
        ('JPY', '日圓'),
        ('ITL', '義大利里拉'),
        ('THB', '泰銖'),
        ('EUR', '歐洲共同貨幣'),
        ('NZD', '紐西蘭幣')
    ], string='幣別', default='TWD', size=3, readonly=True)

    
    # 計算字段
    @api.depends('account_move_ids')
    def _compute_credit_notes(self):
        """計算關聯的貸記單"""
        for record in self:
            # 找到原始發票
            original_moves = record.account_move_ids.filtered(
                lambda m: m.move_type == 'out_invoice'
            )
            
            credit_notes = self.env['account.move']
            for move in original_moves:
                # 找到該發票的所有貸記單
                credit_notes |= self.env['account.move'].search([
                    ('reversed_entry_id', '=', move.id),
                    ('move_type', '=', 'out_refund'),
                    ('state', '=', 'posted')
                ])
            
            record.credit_note_ids = credit_notes
            record.has_credit_note = bool(credit_notes)
    @api.depends('invoice_line_ids.line_amount')
    def _compute_amounts(self):
        for invoice in self:
            total_sales = sum(line.line_amount for line in invoice.invoice_line_ids)
            # 根據課稅別和稅率計算稅額
            if invoice.tax_type == '1':  # 應稅
                tax_amount = int(total_sales * (invoice.tax_rate / 100))
            else:
                tax_amount = 0
                
            invoice.sales_amount = total_sales
            invoice.tax_amount = tax_amount
            invoice.total_amount = total_sales + tax_amount

    def write(self, vals):
        """阻止直接修改電子發票資訊"""
        user = self.env.user
        # 允許管理員通過特殊環境變量強制修改
        if self.env.context.get('force_einvoice_edit') and user.has_group('base.group_system'):
            return super(InvoiceInformation, self).write(vals)
        
        # 允許系統內部修改（來自折讓單操作）
        if self.env.context.get('from_account_move_sync'):
            return super(InvoiceInformation, self).write(vals)
            
        raise UserError('電子發票資訊不可直接修改，請通過應收憑單進行操作。')
    
    @api.model
    def create(self, vals):
        """阻止直接創建電子發票資訊"""
        user = self.env.user
        _logger.info(f"嘗試創建電子發票資訊，上下文={self.env.context}，發票號碼={vals.get('invoice_number')}，字軌ID={vals.get('invoice_track_id')}")
        
        # 允許系統內部創建（來自同步功能）
        if self.env.context.get('from_account_move_sync') or (self.env.context.get('force_einvoice_edit') and user.has_group('base.group_system')):
            # 處理折讓單的特殊情況 - 優先處理折讓情況
            if vals.get('is_allowance') and vals.get('original_invoice_number'):
                # 對於折讓單，使用原始發票號碼
                vals['invoice_number'] = vals.get('original_invoice_number')
                _logger.info(f"為折讓單使用原始發票號碼: {vals['invoice_number']}")
                
            # 從發票字軌獲取下一個可用號碼 - 非折讓單情況
            elif ('invoice_track_id' in vals and not vals.get('invoice_number') and 
                not self.env.context.get('no_regenerate_invoice_number')):
                track = self.env['invoice.track'].browse(vals['invoice_track_id'])
                new_number = track.get_next_number()
                _logger.info(f"從字軌 {track.display_name} 獲取新發票號碼: {new_number}")
                vals['invoice_number'] = new_number
            else:
                # 檢查發票號碼格式
                if vals.get('invoice_number'):
                    original_number = vals['invoice_number']
                    if len(original_number) > 10:
                        _logger.warning(f"發票號碼 {original_number} 長度超過10字符，可能被截斷")
                    
                _logger.info(f"使用提供的發票號碼: {vals.get('invoice_number')}")
            
            # 如果存在 no_regenerate_invoice_number 上下文，確保不會覆蓋發票號碼
            if self.env.context.get('no_regenerate_invoice_number') and vals.get('invoice_number'):
                _logger.info(f"由於上下文標記，使用提供的發票號碼 {vals['invoice_number']} 而不重新生成")
                
            vals['currency'] = 'TWD'  # 確保幣別強制使用台幣
            
            # 檢查資料一致性
            for field, value in vals.items():
                _logger.info(f"字段: {field}, 值: {value}, 類型: {type(value)}")
            
            # 保存原始發票號碼以便比較
            original_invoice_number = vals.get('invoice_number')
            
            result = super(InvoiceInformation, self).create(vals)
            
            # 檢查是否發票號碼在創建過程中被修改
            if result.invoice_number != original_invoice_number:
                _logger.error(f"發票號碼在創建過程中被修改: 原始={original_invoice_number}, 現在={result.invoice_number}")
                # 嘗試強制更新回原始號碼
                try:
                    result.with_context(force_einvoice_edit=True).write({
                        'invoice_number': original_invoice_number
                    })
                    _logger.info(f"已強制恢復發票號碼為 {original_invoice_number}")
                except Exception as e:
                    _logger.error(f"恢復發票號碼失敗: {str(e)}")
            
            _logger.info(f"成功創建電子發票資訊，ID={result.id}, 最終發票號碼={result.invoice_number}")
            return result
        else:
            _logger.error(f"嘗試直接創建電子發票資訊被拒絕，上下文={self.env.context}")
            raise UserError('電子發票資訊不可直接創建，請通過應收憑單產生發票號碼。')
    
    def action_export_csv(self):
        """匯出電子發票資訊為 CSV 格式"""
        if not self:
            raise UserError('請至少選擇一筆記錄進行匯出')

        # 創建 CSV 文件
        csv_file = io.StringIO()
        writer = csv.writer(csv_file)

        # 寫入資料欄位，保留 Column1
        for invoice in self:
            # 寫入發票頭（H區段資料）
            writer.writerow([
                'H', invoice.seller_tax_id or '',
                invoice.seller_name or '',
                invoice.seller_address or '',
                invoice.seller_phone or ''
            ])
            
            # 寫入發票主資訊（M區段資料）
            writer.writerow([
                'M', invoice.invoice_number or '', 
                invoice.invoice_date.strftime('%Y/%m/%d %H:%M:%S') if invoice.invoice_date else '',
                invoice.invoice_type or '', 
                invoice.buyer_tax_id or '', 
                invoice.buyer_name or '', 
                invoice.buyer_address or '', 
                invoice.tax_type or '', 
                str(invoice.tax_rate or ''),
                str(invoice.sales_amount or ''), 
                str(invoice.tax_amount or ''),
                str(invoice.total_amount or ''),
                invoice.customs_clearance or '',
                invoice.zero_tax_mark or '',
                invoice.remark or '',
                invoice.zero_tax_reason or '',
                invoice.related_number or '',
                invoice.buyer_customer_number or '',
                invoice.business_role or '',
                invoice.combined_mark or '',
                str(invoice.exchange_rate or ''),
                invoice.currency or ''
            ])

            # 寫入發票明細（D區段資料）
            for line in invoice.invoice_line_ids:
                writer.writerow([
                    'D', line.product_name or '',
                    str(line.quantity or ''),
                    str(line.unit_price or ''),
                    str(line.line_amount or ''),
                    line.line_remark or '',
                    line.unit or '',
                    # line.line_related_number or ''
                ])

        # 生成附件檔案
        csv_content = csv_file.getvalue().encode('utf-8-sig')  # 使用 BOM 確保中文正常顯示
        filename = f'電子發票_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'

        # 創建附件記錄
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(csv_content),
            'res_model': self._name,
            'res_id': self[0].id if len(self) == 1 else 0,
            'type': 'binary',
        })

        # 返回下載動作
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    
    def action_send_to_fanyuu(self):
        for record in self:
            result = FanyuuAPI(self.env).send_invoice(record)
            if result.get('statusCode') != '0000':
                raise UserError(f"汎宇回傳錯誤: {result.get('statusDesc')}")

            record.write({
                'invoice_number': result.get('invoiceNumber'),
                'invoice_date': result.get('invoiceDate'),
                'remark': result.get('statusDesc'),
            })
    
        return True
    def action_create_sales_return(self):
        """創建銷貨退回單"""
        self.ensure_one()
        if self.operation_type == 'CRE_ALW':
            raise UserError("折讓單不能建立退回單")
        
        if self.operation_type == 'REJ':
            raise UserError("退回單不能再次退回")
        
        return {
            'name': '建立銷貨退回單',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.return',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_original_invoice_id': self.id,
                'default_return_type': 'sales_return',
            }
        }

    def action_create_purchase_return(self):
        """創建進貨退出單"""
        self.ensure_one()
        if self.is_allowance:
            raise UserError("折讓單不能建立退回單")
        
        if self.operation_type == 'REJ':
            raise UserError("退回單不能再次退回")
        
        return {
            'name': '建立進貨退出單',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.return',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_original_invoice_id': self.id,
                'default_return_type': 'purchase_return',
            }
        }
    def action_create_correction(self):
        """創建更正單"""
        self.ensure_one()
        
        if self.operation_type in ['REJ', 'CAN', 'CAN_ALW']:
            raise UserError("已作廢或退回的發票不能更正！")
        
        return {
            'name': '建立更正單',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.correction',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_original_invoice_id': self.id,
            }
        }

    def action_create_cancellation(self):
        """創建作廢單"""
        self.ensure_one()
        
        if self.operation_type in ['REJ', 'CAN', 'CAN_ALW']:
            raise UserError("此發票已作廢或退回，不能再次作廢！")
        
        return {
            'name': '建立作廢單',
            'type': 'ir.actions.act_window',
            'res_model': 'invoice.cancellation',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_invoice_id': self.id,
            }
        }
    @api.model
    def sync_credit_note_from_account_move(self, credit_note_move):
        """當創建貸記單時，同步創建折讓電子發票資訊"""
        if not credit_note_move.reversed_entry_id:
            return
        
        # 找到原始發票的電子發票資訊
        original_invoice_info = self.search([
            ('account_move_ids', 'in', credit_note_move.reversed_entry_id.ids)
        ], limit=1)
        
        if not original_invoice_info:
            return
        
        # 檢查是否已經有對應的折讓記錄
        existing_allowance = self.search([
            ('order_id', '=', credit_note_move.name),
            ('operation_type', '=', 'CRE_ALW')
        ])
        
        if existing_allowance:
            _logger.info(f"貸記單 {credit_note_move.name} 已有對應的折讓記錄")
            return existing_allowance
        
        # 創建折讓證明聯號碼，直接使用原始發票號碼
        original_invoice_number = original_invoice_info.invoice_number
        
        # 創建折讓的電子發票資訊
        allowance_vals = {
            'order_id': credit_note_move.name,
            'seller_tax_id': original_invoice_info.seller_tax_id,
            'seller_name': original_invoice_info.seller_name,
            'seller_address': original_invoice_info.seller_address,
            'seller_phone': original_invoice_info.seller_phone,
            'operation_type': 'CRE_ALW',  # 開立折讓
            
            # 使用生成的折讓證明聯號碼
            'invoice_number': original_invoice_number,
            'invoice_date': credit_note_move.write_date or fields.Datetime.now(), 
            'invoice_type': original_invoice_info.invoice_type,
            'buyer_tax_id': credit_note_move.partner_id.vat or '',
            'buyer_name': credit_note_move.partner_id.name or '',
            'buyer_address': self._get_partner_address(credit_note_move.partner_id),
            
            'tax_type': original_invoice_info.tax_type,
            'tax_rate': original_invoice_info.tax_rate,
            'sales_amount': abs(int(credit_note_move.amount_untaxed)),
            'tax_amount': abs(int(credit_note_move.amount_tax)),
            'total_amount': abs(int(credit_note_move.amount_total)),
            
            'currency': 'TWD',
            'remark': f'貸記單折讓: {credit_note_move.name}，原發票: {original_invoice_number}',
            'invoice_track_id': original_invoice_info.invoice_track_id.id if original_invoice_info.invoice_track_id else False,
            
            # 關聯資訊
            'related_number': original_invoice_number,  # 記錄原始發票號碼
            'buyer_customer_number': credit_note_move.name,  # 記錄貸記單編號
        }
        
        # 準備明細行
        invoice_lines = []
        for line in credit_note_move.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')):
            if not line.product_id and not line.name:
                continue
                
            line_vals = {
                'product_name': line.product_id.name or line.name or '',
                'quantity': abs(line.quantity) or 0.0,
                'unit_price': abs(line.price_unit) or 0.0,
                'unit': line.product_uom_id.name if line.product_uom_id else '',
                'line_remark': f'貸記單明細',
            }
            invoice_lines.append((0, 0, line_vals))
        
        allowance_vals['invoice_line_ids'] = invoice_lines
        
        # 創建折讓記錄
        allowance_info = self.with_context(from_account_move_sync=True).create(allowance_vals)

            
        _logger.info(f"已為貸記單 {credit_note_move.name} 創建折讓電子發票資訊 {allowance_info.id}")
        
        return allowance_info

    def _get_partner_address(self, partner):
        """取得合作夥伴完整地址"""
        if not partner:
            return ''
            
        parts = []
        if partner.zip:
            parts.append(partner.zip)
        if partner.state_id:
            parts.append(partner.state_id.name)
        if partner.city:
            parts.append(partner.city)
        if partner.street:
            parts.append(partner.street)
        if partner.street2:
            parts.append(partner.street2)
            
        return ' '.join(filter(None, parts))


class InvoiceLine(models.Model):
    _name = 'invoice.line'
    _description = '電子發票明細'
    
    # D 區段欄位 - 發票明細
    product_name = fields.Char(string='品名', size=255, required=True, readonly=True)
    quantity = fields.Float(string='數量', digits=(12, 6), required=True, readonly=True)
    unit_price = fields.Float(string='單價', digits=(12, 6), required=True, readonly=True)
    line_amount = fields.Float(string='金額', digits=(12, 6), compute='_compute_amount', store=True)
    unit = fields.Char(string='單位', size=6)
    sequence_number = fields.Char(string='明細序號', size=3)
    line_remark = fields.Char(string='單一欄位備註', size=40)
    tax_type = fields.Selection([('1', '應稅'), ('2', '零稅率'), ('3', '免稅')], string='課稅別')
    
    # 關聯字段
    invoice_id = fields.Many2one('invoice.information', string='發票', required=True, ondelete='cascade')

    
    @api.depends('quantity', 'unit_price')
    def _compute_amount(self):
        for line in self:
            line.line_amount = round(line.quantity * line.unit_price, 2)
            
    def write(self, vals):
        """阻止直接修改電子發票明細行"""
        user = self.env.user
        if self.env.context.get('force_einvoice_edit') and user.has_group('base.group_system'):
            return super(InvoiceLine, self).write(vals)
        
        # 允許系統內部修改（來自折讓單操作）
        if self.env.context.get('from_account_move_sync'):
            return super(InvoiceLine, self).write(vals)
            
        raise UserError('電子發票明細不可直接修改，請通過應收憑單進行操作。')
    
    
    def unlink(self):
        """阻止直接刪除電子發票明細行"""
        user = self.env.user
        if self.env.context.get('force_einvoice_edit') and user.has_group('base.group_system'):
            return super(InvoiceLine, self).unlink()
        raise UserError('電子發票明細不可直接刪除，請聯繫系統管理員。')