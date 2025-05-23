# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.addons.product.report.product_label_report import _prepare_data

class ReportProductTemplateLabel2x5(models.AbstractModel):
    _name = 'report.jasmine.report_producttemplatelabel2x5'
    _description = 'Product Label Report 2x5'

    def _get_report_values(self, docids, data):
        return _prepare_data(self.env, docids, data)

class ProductLabelLayout(models.TransientModel):
    _inherit = 'product.label.layout'
    
    print_format = fields.Selection(selection_add=[
        ('2x5', '2 x 5 公分')
    ], ondelete={'2x5': 'set default'})
    
    def _prepare_report_data(self):
        if self.print_format == '2x5':
            xml_id = 'jasmine.report_product_template_label_2x5'
            
            active_model = ''
            if self.product_tmpl_ids:
                products = self.product_tmpl_ids.ids
                active_model = 'product.template'
            elif self.product_ids:
                products = self.product_ids.ids
                active_model = 'product.product'
            else:
                return super()._prepare_report_data()
            
            data = {
                'active_model': active_model,
                'quantity_by_product': {str(p): self.custom_quantity for p in products},
                'layout_wizard': self.id,
                'price_included': True,
            }
            return xml_id, data
        return super()._prepare_report_data()