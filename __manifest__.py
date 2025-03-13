{
    'name': "Jasmine",
    'version': '17.0',
    'summary': "Jasmine",
    'description': """
        此模組用於茉莉行餐具開發
    """,
    'category': 'Jasmine',
    'author': 'eliou',
    'website': 'http://www.hdot.com',
    'depends': ['sale','account', 'purchase',],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/sale_order_form.xml',
        'views/purchase_views.xml',
        'views/invoice_track.xml',
        'reports/sale_report.xml',
        'reports/purchase_order_report.xml',
        'reports/purchase_quotation.xml',
        'reports/einvoice_report.xml',
        'reports/test.xml',
    ],
    'external_dependencies': {
        'python': ['qrcode', 'Pillow','barcode','python-barcode'],
    },

    'installable': True,
    'application': False,
    'auto_install': False,
}