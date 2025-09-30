{
    'name': '票據功能',
    'version': '1.0',
    'category': 'Accounting',
    'summary': '發票支付擴展功能',
    'description': """
       增加了票據支付的選項。
    """,
    'depends': ['base','account','mail',],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_views.xml',
        'views/account_payment_register_views.xml',
        'views/account_bill_views.xml',
        'views/confirm_cash_payment.xml',
        'views/res_config_settings_views.xml',
        'security/account_security.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

