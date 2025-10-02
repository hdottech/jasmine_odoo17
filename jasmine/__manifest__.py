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
    'depends': ['sale','account', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'data/invoice_allowance_sequence.xml',
        'views/res_partner_views.xml',
        'views/sale_order_form.xml',
        'views/invoice_track.xml',
        'views/invoice_title.xml',
        'views/invoice_information.xml',
        'views/purchase_views.xml',
        'views/res_config_settings_view.xml',
        'views/invoice_allowance.xml',
        'views/invoice_cancellation.xml',
        'views/invoice_menu.xml',
        'reports/purchase_quotation.xml',
        'reports/einvoice_report.xml',
        'reports/test.xml',
        'reports/return.xml',
        'reports/sale_report.xml',
        'reports/product_template_label_2x5.xml',
        
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}