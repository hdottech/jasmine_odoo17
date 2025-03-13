from odoo import fields, models, api
from odoo.models import ValidationError


class InvoiceTitle(models.Model):
    _name = 'invoice.title'
    _description = '發票抬頭管理'
    
    name = fields.Char(string='發票抬頭', required=True)
    active = fields.Boolean(string='啟用', default=True)
    is_active = fields.Boolean(string='是否啟用中', default=False)
    is_used = fields.Boolean(string='已使用', default=False)
    
    _sql_constraints = [
        ('name_unique', 'unique(name)', '發票抬頭不可重複!')
    ]


class InvoiceTrack(models.Model):
    _name = 'invoice.track'
    _description = 'Invoice Track Number Record'
    _rec_name = 'display_name'

    date_from = fields.Date(string='發票起始日期', required=True)
    date_to = fields.Date(string='發票結束日期', required=True)
    section_code = fields.Char(string='字軌號碼', required=True)
    number_from = fields.Char(string='發票起始號碼', required=True)
    number_to = fields.Char(string='發票結束號碼', required=True)
    is_used = fields.Boolean(string='已使用', default=False)
    last_used_number = fields.Char(string='最後使用號碼', readonly=True)
    invoice_period = fields.Char(string='發票週期', compute='_compute_period', store=True)
    is_active = fields.Boolean(string='是否啟用中', default=False)
    next_available_number = fields.Char(string='下一個可用號碼', compute='_compute_next_number')
    invoice_title_id = fields.Many2one('invoice.title', string='發票抬頭', required=True)
    display_name = fields.Char(string='顯示名稱', compute='_compute_display_name', store=True)


    @api.depends('invoice_title_id', 'section_code')
    def _compute_display_name(self):
        for record in self:
            if record.invoice_title_id and record.section_code:
                record.display_name = f"{record.invoice_title_id.name} ({record.section_code})"
            else:
                record.display_name = record.section_code or ""

    def name_get(self):
        result = []
        for record in self:
            name = record.invoice_title
            result.append((record.id, name))
        return result
    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None, order=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', ('display_name', operator, name), 
                          ('invoice_title_id.name', operator, name)]
        return self._search(domain + args, limit=limit, access_rights_uid=name_get_uid, order=order)


    @api.model
    def create(self, vals):
        """創建時檢查同一發票抬頭下是否已有啟用的字軌"""
        if vals.get('is_active'):
            active_track = self.search([
                ('is_active', '=', True),
                ('invoice_title_id', '=', vals.get('invoice_title_id'))
            ])
            if active_track:
                raise ValidationError('此發票抬頭下已有啟用中的發票字軌，請先停用現有字軌')
        return super().create(vals)

    def write(self, vals):
        """修改時檢查啟用狀態"""
        if vals.get('is_active'):
            invoice_title_id = vals.get('invoice_title_id', self.invoice_title_id.id)
            active_track = self.search([
                ('is_active', '=', True), 
                ('id', '!=', self.id),
                ('invoice_title_id', '=', invoice_title_id)
            ])
            if active_track:
                raise ValidationError('此發票抬頭下已有啟用中的發票字軌，請先停用現有字軌')
        return super().write(vals)
    
    @api.depends('number_from', 'last_used_number', 'section_code')
    def _compute_next_number(self):
        """計算下一個可用號碼"""
        for record in self:
            if not record.section_code or not record.number_from:
                record.next_available_number = False
                continue

            if record.is_used:
                record.next_available_number = "此組字軌號碼已用畢"
                continue

            if not record.last_used_number:
                record.next_available_number = f"{record.section_code}-{record.number_from}"
            else:
                current_number = record.last_used_number.replace(record.section_code + '-', '')
                next_num = str(int(current_number) + 1).zfill(8)
                if int(next_num) > int(record.number_to):
                    record.next_available_number = "此組字軌號碼已用畢"
                else:
                    record.next_available_number = f"{record.section_code}-{next_num}"


    def get_next_number(self):
        """獲取下一個可用的發票號碼"""
        self.ensure_one()
        
        if not self.is_active:
            raise ValidationError('此發票字軌未啟用')

        if self.is_used:
            # 找到下一組可用的發票字軌（同一發票抬頭下）
            next_track = self.search([
                ('id', '!=', self.id),
                ('is_used', '=', False),
                ('date_from', '>=', self.date_from),  # 確保時間順序
                ('invoice_title_id', '=', self.invoice_title_id.id),  # 確保同一發票抬頭
            ], order='date_from asc', limit=1)

            if next_track:
                # 停用當前字軌，啟用新字軌
                self.write({'is_active': False, 'is_used': True})
                next_track.write({'is_active': True})
                return next_track.get_next_number()
            else:
                raise ValidationError('所有發票字軌已用完')
            
        next_number = self.next_available_number
        current_number = next_number.replace(self.section_code + '-', '')

        if int(current_number) > int(self.number_to):
            # 當前字軌用完，找下一組（同一發票抬頭下）
            next_track = self.search([
                ('id', '!=', self.id),
                ('is_used', '=', False),
                ('date_from', '>=', self.date_from),
                ('invoice_title_id', '=', self.invoice_title_id.id),  # 確保同一發票抬頭
            ], order='date_from asc', limit=1)

            if next_track:
                # 停用當前字軌，啟用新字軌
                self.write({'is_active': False, 'is_used': True})
                next_track.write({'is_active': True})
                return next_track.get_next_number()
            else:
                self.write({'is_used': True})
                raise ValidationError('所有發票字軌已用完')

        self.write({'last_used_number': next_number})
        return next_number
            
    
    @api.depends('date_from', 'date_to')
    def _compute_period(self):
        for record in self:
            if record.date_from and record.date_to:
                from_date = record.date_from
                # 轉換為民國年
                roc_year = from_date.year - 1911
                # 格式化為 "民國YYY年MM-MM月"
                start_month = from_date.month
                end_month = start_month + 1 if start_month % 2 == 1 else start_month
                record.invoice_period = f"{roc_year}年{str(start_month).zfill(2)}-{str(end_month).zfill(2)}月"
            else:
                record.invoice_period = False
    @api.constrains('number_from', 'number_to')
    def _check_numbers(self):
        for record in self:
            if record.number_from and record.number_to:
                if int(record.number_from) > int(record.number_to):
                    raise ValidationError('結束號碼必須大於起始號碼')
                
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_from and record.date_to:
                if record.date_from > record.date_to:
                    raise ValidationError('結束日期必須大於起始日期')
                # 檢查是否為兩個月期間
                from_date = record.date_from
                to_date = record.date_to
                if (to_date.year - from_date.year) * 12 + to_date.month - from_date.month != 1:
                    raise ValidationError('發票週期必須為兩個月')
                # 檢查是否從奇數月份開始
                if from_date.month % 2 == 0:
                    raise ValidationError('發票週期必須從奇數月份開始')
                

class PosStyleReceiptReport(models.AbstractModel):
    _name = 'report.jasmine.pos_style_receipt'
    _description = 'POS Style Receipt Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['account.move'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'account.move',
            'docs': docs,
            'data': data,
        }
    

class AccountInvoiceReport(models.Model):
    _inherit = 'account.invoice.report'

    einvoice_number = fields.Char(string='發票號碼', readonly=True)
    einvoice_count = fields.Integer(string='發票數量', compute='_compute_einvoice_count')

    def _select(self):
        return super(AccountInvoiceReport, self)._select() + ", move.einvoice_number as einvoice_number"

    def _group_by(self):
        return super(AccountInvoiceReport, self)._group_by() + ", move.einvoice_number"

    @api.depends('einvoice_number')
    def _compute_einvoice_count(self):
        for record in self:
            record.einvoice_count = 1 if record.einvoice_number else 0