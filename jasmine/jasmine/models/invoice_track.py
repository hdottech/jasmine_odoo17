from odoo import fields, models, api
from odoo.models import ValidationError
import base64
import csv
import io


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
    status = fields.Selection([
        ('unused', '未啟用'),
        ('in_use', '使用中'),
        ('used_up', '已用畢')
    ], string='使用狀態', default='unused', required=True, tracking=True)
    next_available_number = fields.Char(string='下一個可用號碼', compute='_compute_next_number')
    invoice_title_id = fields.Many2one('invoice.title', string='發票抬頭', required=True)
    display_name = fields.Char(string='顯示名稱', compute='_compute_display_name', store=True)
    invoice_category = fields.Selection([
            ('07', '一般稅額計算電子發票'),
            ('08', '特殊稅額計算電子發票'),
        ], string='發票類別', required=True, default='07')
    is_valid_for_current_period = fields.Boolean(
        string='是否為當前有效期間',
        compute='_compute_is_valid_for_current_period',
        store=True,
        help='判斷此發票字軌是否在當前使用期間內'
    )


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
    @api.depends('date_from', 'date_to')
    def _compute_is_valid_for_current_period(self):
        """判斷發票字軌是否在當前有效期間內"""
        today = fields.Date.today()
        current_month = today.month
        current_year = today.year
        
        for record in self:
            # 檢查日期範圍是否有效
            if not record.date_from or not record.date_to:
                record.is_valid_for_current_period = False
                continue
                
            # 判斷是否為當前期間
            # 發票週期是兩個月，檢查是否在當前月份或下一個月
            # 根據奇數月開始的規則，確定當前發票期間
            period_start_month = current_month
            if current_month % 2 == 0:  # 如果是偶數月，則期間從上個月開始
                period_start_month = current_month - 1
            
            # 檢查發票字軌的起始月份是否符合當前發票期間
            track_month = record.date_from.month
            track_year = record.date_from.year
            
            # 檢查年份和月份是否符合當前期間
            is_current_period = (
                track_year == current_year and 
                track_month == period_start_month
            )
            
            # 如果不是當前期間，但狀態是"使用中"，也視為有效
            # 這確保已啟用但不是當前期間的字軌仍能顯示
            is_active_track = record.status == 'in_use'
            
            record.is_valid_for_current_period = is_current_period or is_active_track

    # 添加一個方法來獲取唯一的使用中發票字軌
    @api.model
    def get_unique_active_tracks(self):
        """獲取每個發票抬頭下唯一的使用中字軌"""
        # 查詢所有使用中的字軌
        active_tracks = self.search([
            ('status', '=', 'in_use'),
            ('is_valid_for_current_period', '=', True)
        ])
        
        # 使用字典來確保每個發票抬頭只有一個字軌
        unique_tracks = {}
        for track in active_tracks:
            title_id = track.invoice_title_id.id
            # 如果該抬頭還沒有字軌，或者當前字軌更新，則更新
            if title_id not in unique_tracks or track.date_from > unique_tracks[title_id].date_from:
                unique_tracks[title_id] = track
        
        # 返回唯一的字軌列表
        return list(unique_tracks.values())


    @api.model
    def create(self, vals):
        """創建時檢查同一發票抬頭下是否已有啟用的字軌"""
        if vals.get('status') == 'in_use':
            active_track = self.search([
                ('status', '=', 'in_use'),
                ('invoice_title_id', '=', vals.get('invoice_title_id'))
            ])
            if active_track:
                raise ValidationError('此發票抬頭下已有啟用中的發票字軌，請先停用現有字軌')
        return super().create(vals)

    def write(self, vals):
        """修改時檢查啟用狀態"""
        if vals.get('status') == 'in_use':
            invoice_title_id = vals.get('invoice_title_id', self.invoice_title_id.id)
            active_track = self.search([
                ('status', '=', 'in_use'), 
                ('id', '!=', self.id),
                ('invoice_title_id', '=', invoice_title_id)
            ])
            if active_track:
                raise ValidationError('此發票抬頭下已有啟用中的發票字軌，請先停用現有字軌')
        """寫入時同步狀態欄位"""
        # 如果修改了 status，同步更新舊欄位
        if 'status' in vals:
            if vals['status'] == 'in_use':
                vals.update({'is_active': True, 'is_used': False})
            elif vals['status'] == 'used_up':
                vals.update({'is_active': False, 'is_used': True})
            elif vals['status'] == 'unused':
                vals.update({'is_active': False, 'is_used': False})
        
        # 如果修改了舊欄位，同步更新 status
        elif 'is_active' in vals or 'is_used' in vals:
            is_active = vals.get('is_active', self.is_active)
            is_used = vals.get('is_used', self.is_used)
            
            if is_used:
                vals['status'] = 'used_up'
            elif is_active:
                vals['status'] = 'in_use'
            else:
                vals['status'] = 'unused'
        
        return super(InvoiceTrack, self).write(vals)
    
    @api.depends('number_from', 'last_used_number', 'section_code', 'status')
    def _compute_next_number(self):
        """計算下一個可用號碼"""
        for record in self:
            if not record.section_code or not record.number_from:
                record.next_available_number = False
                continue

            if record.status == 'used_up':
                record.next_available_number = "此組字軌號碼已用畢"
                continue

            if not record.last_used_number:
                record.next_available_number = f"{record.section_code}-{record.number_from}"
            else:
                current_number = record.last_used_number.replace(record.section_code + '-', '')
                next_num = str(int(current_number) + 1).zfill(8)
                if int(next_num) > int(record.number_to):
                    record.next_available_number = "此組字軌號碼已用畢"
                    # 自動更新狀態為已用畢
                    if record.status == 'in_use':
                        record.status = 'used_up'
                else:
                    record.next_available_number = f"{record.section_code}-{next_num}"


    def get_next_number(self):
        """獲取下一個可用的發票號碼"""
        self.ensure_one()
        
        if self.status != 'in_use':
            raise ValidationError('此發票字軌未啟用')

        if self.status == 'used_up':
            # 找到下一組可用的發票字軌（同一發票抬頭下）
            next_track = self.search([
                ('id', '!=', self.id),
                ('status', '=', 'unused'),
                ('date_from', '>=', self.date_from),  # 確保時間順序
                ('invoice_title_id', '=', self.invoice_title_id.id),  # 確保同一發票抬頭
            ], order='date_from asc', limit=1)

            if next_track:
                # 停用當前字軌，啟用新字軌
                self.write({'status': 'used_up'})
                next_track.write({'status': 'in_use'})
                return next_track.get_next_number()
            else:
                raise ValidationError('所有發票字軌已用完')
            
        next_number = self.next_available_number
        current_number = next_number.replace(self.section_code + '-', '')

        if int(current_number) > int(self.number_to):
            # 當前字軌用完，找下一組（同一發票抬頭下）
            next_track = self.search([
                ('id', '!=', self.id),
                ('status', '=', 'unused'),
                ('date_from', '>=', self.date_from),
                ('invoice_title_id', '=', self.invoice_title_id.id),  # 確保同一發票抬頭
            ], order='date_from asc', limit=1)

            if next_track:
                # 停用當前字軌，啟用新字軌
                self.write({'status': 'used_up'})
                next_track.write({'status': 'in_use'})
                return next_track.get_next_number()
            else:
                self.write({'status': 'used_up'})
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
    def export_csv(self):
        """匯出已用畢但未使用過的發票號碼為財政部指定的 CSV 格式"""
        if not self:
            raise ValidationError('請至少選擇一筆記錄進行匯出')
        
        # 過濾，只保留已用畢的發票字軌
        used_up_tracks = self.filtered(lambda r: r.status == 'used_up')
        
        if not used_up_tracks:
            raise ValidationError('沒有已用畢的發票字軌可匯出')

        # 按照日期排序（先按年份，再按月份）
        sorted_tracks = used_up_tracks.sorted(key=lambda r: (r.date_from.year, r.date_from.month))

        # 創建 CSV 文件（不使用標頭行，因為財政部格式不需要）
        csv_file = io.StringIO()
        writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        
        # 依序匯出每筆發票字軌紀錄
        row_num = 1
        for track in sorted_tracks:
            # 檢查是否有未使用的號碼
            if track.last_used_number:
                # 獲取最後使用的號碼
                last_num = track.last_used_number.replace(f"{track.section_code}-", "")
                last_num_int = int(last_num)
                
                # 檢查是否有未使用的區間
                if last_num_int < int(track.number_to):
                    # 有未使用的區間
                    start_number = str(last_num_int + 1).zfill(8)
                    end_number = track.number_to.zfill(8)
                else:
                    # 沒有未使用的區間，跳過此記錄
                    continue
            else:
                # 如果沒有最後使用號碼，表示整個區間都未使用
                start_number = track.number_from.zfill(8)
                end_number = track.number_to.zfill(8)
            
            # 處理民國年月 (格式: 10108)
            roc_year = track.date_from.year - 1911 if track.date_from else 0
            month = track.date_from.month if track.date_from else 0
            period = f"{roc_year}{str(month).zfill(2)}"
            
            # 序號 (5 位數，從 00001 開始)
            serial_number = str(row_num).zfill(5)
            
            # 統一編號 (固定 8 位數)
            tax_id = track.invoice_title_id.seller_tax_id or '00000000'
            
            # 發票類別 (預設為 07: 一般稅額計算電子發票)
            invoice_category = track.invoice_category or '07'
            
            # 依照財政部格式建立 CSV 行
            # 格式: 序號,統一編號,所屬年月,字軌,空白發票起號,空白發票迄號,發票類別
            csv_row = [
                serial_number,
                tax_id,
                period,
                track.section_code or '',
                start_number,
                end_number,
                invoice_category
            ]
            
            writer.writerow(csv_row)
            row_num += 1

        # 如果沒有任何記錄被寫入，提示用戶
        if row_num == 1:
            raise ValidationError('沒有已用畢但尚有未使用號碼的發票字軌')

        # 生成附件檔案 (使用 utf-8 編碼，無 BOM)
        csv_content = csv_file.getvalue().encode('utf-8')
        filename = f'空白未使用字軌_{fields.Date.today()}.csv'

        # 創建附件記錄
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(csv_content),
            'res_model': 'invoice.track',
            'res_id': self[0].id if self else False,
            'type': 'binary',
        })

        # 返回下載動作
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
    def migrate_invoice_track_status(self):
        """遷移發票字軌狀態資料"""
        # 從未使用且未啟用 -> unused
        records_unused = self.search([('is_active', '=', False), ('is_used', '=', False)])
        if records_unused:
            records_unused.write({'status': 'unused'})
        
        # 未使用但已啟用 -> in_use
        records_in_use = self.search([('is_active', '=', True), ('is_used', '=', False)])
        if records_in_use:
            records_in_use.write({'status': 'in_use'})
        
        # 已使用 -> used_up
        records_used_up = self.search([('is_used', '=', True)])
        if records_used_up:
            records_used_up.write({'status': 'used_up'})
        
        return {'type': 'ir.actions.client', 'tag': 'reload'}
    @api.onchange('status')
    def _onchange_status(self):
        """狀態變更時同步更新 is_active 和 is_used"""
        if self.status == 'in_use':
            self.is_active = True
            self.is_used = False
        elif self.status == 'used_up':
            self.is_active = False
            self.is_used = True
        else:  # unused
            self.is_active = False
            self.is_used = False

    @api.onchange('is_active', 'is_used')
    def _onchange_legacy_status(self):
        """舊狀態欄位變更時同步更新 status"""
        if self.is_used:
            self.status = 'used_up'
        elif self.is_active:
            self.status = 'in_use'
        else:
            self.status = 'unused'
                

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