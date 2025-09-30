import requests
import hashlib
import base64
from datetime import datetime

class FanyuuAPI:
    def __init__(self, env):
        self.env = env
        config = env['ir.config_parameter'].sudo()
        self.user_id = config.get_param('fanyuu.user_id')
        self.auth = config.get_param('fanyuu.auth')
        self.apikey = config.get_param('fanyuu.apikey')
        self.company_id = config.get_param('fanyuu.company_id')
        self.endpoint = config.get_param('fanyuu.endpoint') or 'https://webtest.einvoice.com.tw/einv/openInvoice'

    def _generate_signature(self, timestamp):
        raw = (timestamp + self.apikey).encode('utf-8')
        sha256 = hashlib.sha256(raw).digest()
        return base64.b64encode(sha256).decode()

    def _build_header(self, timestamp):
        return {
            'companyID': self.company_id,
            'userID': self.user_id,
            'auth': base64.b64encode(self.auth.encode()).decode(),
            'createDateTime': timestamp,
            'signatureValue': self._generate_signature(timestamp)
        }

    def _build_payload(self, invoice):
        req_data = {
            'orderID': invoice.order_id,
            'process_type': 'B',
            'sellerID': invoice.seller_tax_id,
            'buyerID': invoice.buyer_tax_id or '',
            'buyerName': invoice.buyer_name or '',
            'invoiceType': invoice.invoice_type,
            'donateMark': invoice.donate_mark,
            'printMark': invoice.print_mark,
            'salesAmount': invoice.sales_amount,
            'freetaxSalesamount': invoice.freetax_sales_amount,
            'zerotaxSalesamount': invoice.zerotax_sales_amount,
            'taxType': invoice.tax_type,
            'taxrate': invoice.tax_rate,
            'taxAmount': invoice.tax_amount,
            'totalAmount': invoice.total_amount,
            'mainRemark': invoice.remark or '',
            'Details': [
                {
                    'description': line.product_name,
                    'quantity': line.quantity,
                    'unit': line.unit,
                    'unitprice': line.unit_price,
                    'amount': line.line_amount,
                    'sequenceNumber': line.sequence_number or str(idx+1).zfill(3),
                    'remark': line.line_remark or '',
                    'taxType': line.tax_type or '1'
                } for idx, line in enumerate(invoice.invoice_line_ids)
            ]
        }
        return req_data

    def send_invoice(self, invoice):
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        header = self._build_header(timestamp)
        data = self._build_payload(invoice)

        payload = header.copy()
        payload['reqData'] = data

        response = requests.post(self.endpoint, json=payload, headers={'Content-Type': 'application/json'})
        response.raise_for_status()
        return response.json()
