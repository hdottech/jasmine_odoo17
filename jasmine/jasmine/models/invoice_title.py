from odoo import models, fields, api
from odoo.exceptions import ValidationError

class InvoiceTitle(models.Model):
    _name = 'invoice.title'
    _description = '發票抬頭管理'
    
    name = fields.Char(string='發票抬頭', required=True)
    active = fields.Boolean(string='啟用', default=True)
    is_active = fields.Boolean(string='是否啟用中', default=False)
    is_used = fields.Boolean(string='已使用', default=False)
    
    # 新增發票相關賣方資訊欄位
    seller_tax_id = fields.Char(string='賣方統一編號', size=8, required=True, 
                              help='請輸入8位數統一編號，不含特殊符號')
    seller_name = fields.Char(string='賣方公司名稱', size=60, required=True)
    seller_address = fields.Char(string='賣方公司地址', size=100)
    seller_phone = fields.Char(string='賣方公司電話', size=26, help='例：02-26551188')
    
    _sql_constraints = [
        ('name_unique', 'unique(name)', '發票抬頭不可重複!'),
        ('seller_tax_id_unique', 'unique(seller_tax_id)', '賣方統一編號不可重複!')
    ]
    
    @api.constrains('seller_tax_id')
    def _check_tax_id_format(self):
        """檢查統一編號格式"""
        for record in self:
            if record.seller_tax_id and (not record.seller_tax_id.isdigit() or len(record.seller_tax_id) != 8):
                raise ValidationError('賣方統一編號必須為8位數字！')
    
    def toggle_active_status(self):
        """切換啟用狀態"""
        # 如果要啟用此抬頭，先檢查是否已有其他啟用中的抬頭
        if not self.is_active:
            active_titles = self.search([('is_active', '=', True), ('id', '!=', self.id)])
            if active_titles:
                raise ValidationError('已有其他啟用中的發票抬頭，請先停用它們。')
        
        self.is_active = not self.is_active
        return True
    
    @api.model
    def create(self, vals):
        """創建時若設為啟用，檢查是否有其他啟用中的抬頭"""
        if vals.get('is_active'):
            active_titles = self.search([('is_active', '=', True)])
            if active_titles:
                raise ValidationError('已有其他啟用中的發票抬頭，請先停用它們。')
        
        return super(InvoiceTitle, self).create(vals)
    
    def write(self, vals):
        """寫入時若設為啟用，檢查是否有其他啟用中的抬頭"""
        if vals.get('is_active'):
            active_titles = self.search([('is_active', '=', True), ('id', '!=', self.id)])
            if active_titles:
                raise ValidationError('已有其他啟用中的發票抬頭，請先停用它們。')
        
        return super(InvoiceTitle, self).write(vals)