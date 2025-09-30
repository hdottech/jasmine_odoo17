# -*- coding: utf-8 -*-
# from odoo import http


# class InvoicePaymentExtension(http.Controller):
#     @http.route('/invoice_payment_extension/invoice_payment_extension', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/invoice_payment_extension/invoice_payment_extension/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('invoice_payment_extension.listing', {
#             'root': '/invoice_payment_extension/invoice_payment_extension',
#             'objects': http.request.env['invoice_payment_extension.invoice_payment_extension'].search([]),
#         })

#     @http.route('/invoice_payment_extension/invoice_payment_extension/objects/<model("invoice_payment_extension.invoice_payment_extension"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('invoice_payment_extension.object', {
#             'object': obj
#         })

