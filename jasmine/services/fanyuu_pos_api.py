# -*- coding: utf-8 -*-

from odoo import fields, models, api
import json
import requests
import logging
from datetime import datetime
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# 全域號碼池 - 改進版
_global_number_pools = {}

class FanyuuPosAPI:
    """汎宇發票號碼取號API服務 """

    def __init__(self, env):
        self.env = env
        # 從設定檔獲取基本參數
        params = env['ir.config_parameter'].sudo()
        
        # 根據環境設定選擇API網址
        endpoint = params.get_param('fanyuu.pos_endpoint', 'test')
        if endpoint == 'prod':
            self.api_url = 'https://eposw.einvoice.com.tw/GetInvoice.ashx'
        else:
            self.api_url = 'https://postest2.einvoice.com.tw/GetInvoice.ashx'
        
        # 請求標頭
        self.headers = {
            'Content-Type': 'application/json;charset=utf-8'
        }
        
        # 統編與 POSID 的對應關係
        self.company_mapping = {
            '83293137': {
                'pos_id': '1001',
                'channel_key': 'dequX8NU7Wf9GzGmpsv9'
            },
            '83293128': {
                'pos_id': '1002',
                'channel_key': '另一個channel_key'
            },
        }
        
        _logger.info(f"汎宇取號API初始化 - 環境: {endpoint}, URL: {self.api_url}")

    # 核心取號方法 - 號碼池管理
    def get_invoice_number(self, invoice_track_id=None, invoice_title_id=None):
        """每次從 invoice.track 的號碼池中取出一號，並更新記錄"""
        try:
            # 獲取公司設定
            config = self._get_company_config(invoice_title_id)
            seller_id = config['seller_id']
            
            _logger.info(f"開始取號 - 統編: {seller_id}")

            track = self.env['invoice.track'].browse(invoice_track_id)
        
            # 調用號碼池控制主流程
            invoice_number = track.get_next_number()
            
            return {
                'success': True,
                'invoice_number': invoice_number,
                'raw_number': invoice_number.replace('-', ''),
                'message': '已從 invoice.track 成功取號',
                'seller_tax_id': track.invoice_title_id.seller_tax_id,
                'company_name': track.invoice_title_id.name,
                'pool_status': {
                    'exists': True,
                    'total_numbers': track.fanyuu_pool_size,
                    'used_numbers': track.fanyuu_used_count,
                    'remaining_numbers': track.fanyuu_remaining_count,
                    'current_number': invoice_number,
                    'current_index': track.current_fanyuu_index,
                    'invoice_header': track.fanyuu_pool_header,
                    'created_at': track.fanyuu_pool_created_at,
                    'last_used_at': track.fanyuu_pool_last_used_at,
                    'pool_health': (
                        'empty' if track.fanyuu_remaining_count <= 0 else
                        'warning' if track.fanyuu_remaining_count <= 5 else
                        'healthy'
                    ),
                    'first_number': f"{track.fanyuu_pool_header}-{str(int(track.number_from)).zfill(8)}",
                    'last_number': f"{track.fanyuu_pool_header}-{str(int(track.number_to)).zfill(8)}"
                }
            }

        except Exception as e:
            _logger.exception("汎宇取號失敗")
            return {'success': False, 'message': f'取號發生錯誤: {str(e)}'}

    # 檢查號碼池是否有可用號碼
    def _has_available_numbers_in_pool(self, seller_id):
        """檢查號碼池是否有可用號碼"""
        global _global_number_pools
        
        if seller_id not in _global_number_pools:
            _logger.info(f"統編 {seller_id} 尚未建立號碼池")
            return False
        
        pool = _global_number_pools[seller_id]
        available = pool['current_index'] < len(pool['numbers'])
        remaining = len(pool['numbers']) - pool['current_index']
        
        _logger.info(f"號碼池狀態 - 統編: {seller_id}, 剩餘號碼: {remaining}, 可用: {available}")
        
        return available

    # 從號碼池取得下一個號碼
    def _get_number_from_pool(self, seller_id):
        """從號碼池取得下一個號碼"""
        global _global_number_pools
        
        if seller_id not in _global_number_pools:
            raise UserError(f"統編 {seller_id} 的號碼池不存在")
        
        pool = _global_number_pools[seller_id]
        if pool['current_index'] >= len(pool['numbers']):
            raise UserError(f"統編 {seller_id} 的號碼池已用完")
        
        # 取得當前號碼
        current_number = pool['numbers'][pool['current_index']]
        
        # 移動到下一個號碼
        _global_number_pools[seller_id]['current_index'] += 1
        _global_number_pools[seller_id]['last_used_at'] = datetime.now()
        
        # 記錄使用情況
        remaining = len(pool['numbers']) - pool['current_index']
        used_count = pool['current_index']
        
        _logger.info(f"從號碼池取號: {current_number} (已用: {used_count}, 剩餘: {remaining})")
        
        # 當剩餘號碼不多時提醒
        if remaining <= 5:
            _logger.warning(f"號碼池即將用完 - 統編: {seller_id}, 剩餘: {remaining}")
        
        return current_number

    # 建立新的號碼池
    def _create_number_pool(self, seller_id, track_info):
        """建立新的號碼池"""
        global _global_number_pools
        
        invoice_header = track_info['invoice_header']
        invoice_start = int(track_info['invoice_start'])
        invoice_end = int(track_info['invoice_end'])
        
        # 計算號碼數量
        total_numbers = invoice_end - invoice_start + 1
        
        # 產生所有號碼
        numbers = []
        for i in range(invoice_start, invoice_end + 1):
            formatted_number = f"{invoice_header}-{i:08d}"
            numbers.append(formatted_number)
        
        # 建立號碼池結構
        pool_info = {
            'numbers': numbers,
            'current_index': 0,
            'created_at': datetime.now(),
            'last_used_at': None,
            'track_info': track_info,
            'seller_id': seller_id,
            'total_numbers': total_numbers,
            'invoice_header': invoice_header,
            'start_number': invoice_start,
            'end_number': invoice_end
        }
        
        # 儲存到全域號碼池
        _global_number_pools[seller_id] = pool_info
        
        _logger.info(f"建立號碼池成功 - 統編: {seller_id}")
        _logger.info(f"  號碼範圍: {numbers[0]} 到 {numbers[-1]}")
        _logger.info(f"  總計: {total_numbers} 個號碼")
        _logger.info(f"  字軌: {invoice_header}")
        
        return {
            'total_numbers': total_numbers,
            'first_number': numbers[0],
            'last_number': numbers[-1],
            'invoice_header': invoice_header
        }

    # 取得號碼池摘要資訊
    def _get_pool_summary(self, seller_id):
        """取得號碼池摘要資訊"""
        global _global_number_pools
        
        if seller_id not in _global_number_pools:
            return {'exists': False}
        
        pool = _global_number_pools[seller_id]
        total = len(pool['numbers'])
        used = pool['current_index']
        remaining = total - used
        
        return {
            'exists': True,
            'total_numbers': total,
            'used_numbers': used,
            'remaining_numbers': remaining,
            'usage_percentage': round((used / total) * 100, 1) if total > 0 else 0,
            'current_header': pool['invoice_header'],
            'pool_created_at': pool['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
            'last_used_at': pool['last_used_at'].strftime('%Y-%m-%d %H:%M:%S') if pool['last_used_at'] else None
        }

    # 更新發票字軌記錄
    def _update_track_record(self, invoice_track_id, invoice_number, track_info=None, pool_info=None):
        """更新發票字軌記錄"""
        try:
            track = self.env['invoice.track'].browse(invoice_track_id)
            if track.exists():
                update_vals = {
                    'last_fanyuu_number': invoice_number,
                    'last_used_number': invoice_number,
                    'fanyuu_sync_status': 'synced',
                    'fanyuu_success_count': track.fanyuu_success_count + 1,
                    'last_fanyuu_request_time': fields.Datetime.now()
                }
                
                # 如果有新的號碼區間資訊，也一併更新
                if track_info:
                    update_vals.update({
                        'number_from': str(track_info['invoice_start']).zfill(8),
                        'number_to': str(track_info['invoice_end']).zfill(8),
                        'fanyuu_error_message': False,
                    })
                
                # 如果有號碼池資訊，更新相關欄位
                if pool_info:
                    update_vals.update({
                        'fanyuu_pool_size': pool_info['total_numbers'],
                        'fanyuu_used_count': 1,  # 剛取了一個號碼
                        'current_fanyuu_index': 1
                    })
                
                track.write(update_vals)
                _logger.info(f"已更新字軌記錄: {track.section_code}")
        except Exception as e:
            _logger.error(f"更新字軌記錄失敗: {str(e)}")

    @classmethod # 取得號碼池詳細狀態
    def get_pool_status(cls, seller_id):
        """取得號碼池詳細狀態"""
        global _global_number_pools
        
        if seller_id not in _global_number_pools:
            return {'exists': False, 'message': '號碼池不存在'}
        
        pool = _global_number_pools[seller_id]
        total = len(pool['numbers'])
        used = pool['current_index']
        remaining = total - used
        
        return {
            'exists': True,
            'seller_id': seller_id,
            'total_numbers': total,
            'used_numbers': used,
            'remaining_numbers': remaining,
            'usage_percentage': round((used / total) * 100, 1),
            'first_number': pool['numbers'][0] if pool['numbers'] else None,
            'last_number': pool['numbers'][-1] if pool['numbers'] else None,
            'current_number': pool['numbers'][used] if used < len(pool['numbers']) else '已用完',
            'last_used_number': pool['numbers'][used-1] if used > 0 else '尚未使用',
            'invoice_header': pool['invoice_header'],
            'created_at': pool['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
            'last_used_at': pool['last_used_at'].strftime('%Y-%m-%d %H:%M:%S') if pool['last_used_at'] else '尚未使用',
            'pool_health': 'healthy' if remaining > 10 else 'warning' if remaining > 0 else 'empty'
        }

    @classmethod # 取得所有號碼池狀態
    def get_all_pools_status(cls):
        """取得所有號碼池狀態"""
        global _global_number_pools
        
        status_list = []
        for seller_id in _global_number_pools:
            status = cls.get_pool_status(seller_id)
            status_list.append(status)
        
        return status_list

    @classmethod # 清空號碼池
    def clear_pool(cls, seller_id=None):
        """清空號碼池"""
        global _global_number_pools
        
        if seller_id:
            if seller_id in _global_number_pools:
                pool_info = _global_number_pools[seller_id]
                del _global_number_pools[seller_id]
                _logger.info(f"已清空統編 {seller_id} 的號碼池 (原有 {len(pool_info['numbers'])} 個號碼)")
                return True
            else:
                _logger.warning(f"統編 {seller_id} 的號碼池不存在")
                return False
        else:
            pool_count = len(_global_number_pools)
            _global_number_pools.clear()
            _logger.info(f"已清空所有號碼池 (共 {pool_count} 個)")
            return True


    # 根據發票抬頭獲取對應的統編和設定
    def _get_company_config(self, invoice_title_id=None):
        """根據發票抬頭獲取對應的統編和設定"""
        try:
            if invoice_title_id:
                invoice_title = self.env['invoice.title'].browse(invoice_title_id)
                if not invoice_title.exists():
                    raise ValidationError(f'找不到ID為 {invoice_title_id} 的發票抬頭')
            else:
                invoice_title = self.env['invoice.title'].search([
                    ('is_active', '=', True)
                ], limit=1)
                
                if not invoice_title:
                    _logger.warning("沒有找到啟用中的發票抬頭，使用第一筆記錄")
                    invoice_title = self.env['invoice.title'].search([], limit=1)
                    
                if not invoice_title:
                    raise ValidationError('請先建立發票抬頭資料')
            
            seller_tax_id = invoice_title.seller_tax_id
            
            if seller_tax_id not in self.company_mapping:
                if seller_tax_id == '83293137':
                    _logger.warning(f'統編 {seller_tax_id} 使用預設設定')
                    config = {
                        'pos_id': '1001',
                        'channel_key': 'dequX8NU7Wf9GzGmpsv9'
                    }
                else:
                    raise ValidationError(f'統編 {seller_tax_id} 尚未在汎宇系統中設定對應的 POSID 和通道金鑰')
            else:
                config = self.company_mapping[seller_tax_id]
            
            return {
                'seller_id': seller_tax_id,
                'pos_id': config['pos_id'],
                'channel_key': config['channel_key'],
                'invoice_title': invoice_title
            }
            
        except Exception as e:
            _logger.error(f"獲取公司設定失敗: {str(e)}")
            raise ValidationError(f"獲取公司設定失敗: {str(e)}")

    # 取得發票字軌資訊 (A01)
    def get_invoice_track_info(self, invoice_title_id=None):
        """取得發票字軌資訊 (A01)"""
        try:
            config = self._get_company_config(invoice_title_id)
            
            payload = {
                "INDEX": {
                    "FUNCTIONCODE": "A01",
                    "SELLERID": config['seller_id'],
                    "POSID": config['pos_id'],
                    "POSSN": config['channel_key'],
                    "SYSTIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "REPLY": "",
                    "MESSAGE": "",
                    "VERIONUPDATE": "",
                    "ACCOUNT": "0000000000000000",
                    "APPID": "0000000000000000",
                    "ServerType": "invioce_ml",
                    "APPVSERION": "V1.0",
                    "USERID": "",
                    "TAXMONTH": "",
                    "INVOICEHEADER": "",
                    "INVOICESTART": "",
                    "INVOICEEND": "",
                    "INVOICENUMBER": "",
                    "SECURITY": "",
                    "SELLDETAIL": "",
                    "CHECKSUM": "",
                    "EcrId": ""
                }
            }
            
            result = self._send_request(payload)
            response = self._parse_a01_response(result)
            response['seller_tax_id'] = config['seller_id']
            response['company_name'] = config['invoice_title'].seller_name
            
            return response
            
        except Exception as e:
            _logger.error(f"汎宇取字軌資訊失敗: {str(e)}")
            return {
                'success': False,
                'track_info': None,
                'message': f"取字軌資訊失敗: {str(e)}",
                'seller_tax_id': None
            }

    # 解析汎宇 A01 字軌資訊回應
    def _parse_a01_response(self, result):
        """解析汎宇 A01 字軌資訊回應"""
        try:
            if 'INDEX' in result:
                reply = result['INDEX'].get('REPLY', '0')
                message = result['INDEX'].get('MESSAGE', '')
                
                if reply == '1':
                    track_info = {
                        'tax_month': result['INDEX'].get('TAXMONTH', ''),
                        'invoice_header': result['INDEX'].get('INVOICEHEADER', ''),
                        'invoice_start': int(result['INDEX'].get('INVOICESTART', '0')),
                        'invoice_end': int(result['INDEX'].get('INVOICEEND', '0')),
                        'qr_code_key': result['INDEX'].get('QRCodeASKey', ''),  # 確保包含
                        'type': result['INDEX'].get('TYPE', ''),
                    }
                    
                    total_numbers = track_info['invoice_end'] - track_info['invoice_start'] + 1
                    _logger.info(f"汎宇 A01 取字軌資訊成功: {track_info['invoice_header']}, 共 {total_numbers} 個號碼")
                    _logger.info(f"QRCodeASKey: {track_info['qr_code_key']}")  # 記錄 QRCodeASKey
                    
                    return {
                        'success': True,
                        'track_info': track_info,
                        'message': message or '取字軌資訊成功'
                    }
                else:
                    return {
                        'success': False,
                        'track_info': None,
                        'message': f"汎宇取字軌資訊失敗: {message}"
                    }
            else:
                return {
                    'success': False,
                    'track_info': None,
                    'message': '汎宇回應格式錯誤'
                }
        except Exception as e:
            _logger.error(f"解析汎宇 A01 字軌資訊回應失敗: {str(e)}")
            return {
                'success': False,
                'track_info': None,
                'message': f"解析回應失敗: {str(e)}"
            }

    # 發送請求到汎宇API
    def _send_request(self, payload):
        """發送請求到汎宇API"""
        try:
            _logger.info(f"發送請求到汎宇API: {self.api_url}")
            _logger.debug(f"請求內容: {json.dumps(payload, ensure_ascii=False, indent=2)}")
            
            json_data = json.dumps(payload, ensure_ascii=False)
            json_bytes = json_data.encode('utf-8')
            
            headers = {
                'Content-Type': 'application/json;charset=utf-8',
                'Accept': 'application/json'
            }
            
            response = requests.post(
                self.api_url,
                data=json_bytes,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            response.encoding = 'utf-8'
            result = response.json()
            
            _logger.info(f"汎宇API回應: {json.dumps(result, ensure_ascii=False, indent=2)}")
            
            return result
            
        except requests.exceptions.RequestException as e:
            _logger.error(f"汎宇API請求失敗: {str(e)}")
            raise UserError(f"無法連接到汎宇API: {str(e)}")
        except ValueError as e:
            _logger.error(f"汎宇API回應格式錯誤: {str(e)}")
            raise UserError(f"汎宇API回應格式錯誤: {str(e)}")
        except Exception as e:
            _logger.error(f"汎宇API未知錯誤: {str(e)}")
            raise UserError(f"汎宇API未知錯誤: {str(e)}")

        return result
    
    # 上傳發票明細到汎宇 (C0401)
    def upload_invoice_to_fanyuu(self, account_move_id, invoice_title_id=None):
        """上傳發票明細到汎宇 (C0401)"""
        try:
            # 獲取發票記錄
            move = self.env['account.move'].browse(account_move_id)
            if not move.exists():
                raise ValidationError(f'找不到ID為 {account_move_id} 的發票記錄')
            
            # 檢查必要資訊
            if not move.einvoice_number:
                raise ValidationError('發票必須先產生發票號碼才能上傳明細')
                
            if not move.einvoice_date:
                raise ValidationError('缺少發票開立時間')
                
            if not move.einvoice_random_number:
                raise ValidationError('缺少發票隨機碼')
            
            # 獲取公司設定
            config = self._get_company_config(invoice_title_id or move.invoice_title_id.id)
            
            # 準備發票明細資料 (B 區塊)
            invoice_lines = []
            line_seq = 1
            
            for line in move.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')):
                # 根據汎宇 C0401 規格準備明細
                line_data = {
                    "B1": str(line_seq),  # 商品項目資料 (序號)
                    "B2": line.product_id.name or line.name or '商品',  # 品名
                    "B3": str(line.quantity or 1),  # 數量
                    "B4": line.product_uom_id.name or '',  # 單位
                    "B5": str(int(line.price_unit or 0)),  # 單價
                    "B6": str(int(line.price_subtotal or 0)),  # 金額
                    "B7": str(line_seq),  # 明細排列序號
                    "B8": line.name if line.name != (line.product_id.name or '') else '',  # 單一欄位備註
                    "B9": '',  # 相關號碼
                    "B10": str(int(line.price_subtotal or 0)),  # 未稅金額
                    "B11": line.product_id.default_code or '',  # 品號
                    "B12": '',  # 品項條碼
                    "B13": "1"  # 課稅別 (1:應稅)
                }
                invoice_lines.append(line_data)
                line_seq += 1
            
            # 準備 C0401 請求資料
            payload = {
                "Invoice": {
                    # A 區塊 - 發票基本資訊
                    "A1": "C0401",  # 訊息類型
                    "A2": move.einvoice_number.replace('-', ''),  # 發票號碼 (不含連字號)
                    "A3": move.einvoice_date.strftime("%Y-%m-%d"),  # 發票開立日期
                    "A4": move.einvoice_date.strftime("%H:%M:%S"),  # 發票開立時間
                    "A5": move.partner_id.vat or "0000000000",  # 買方統編
                    "A6": move.partner_id.name or "0000",  # 買方名稱 
                    "A7": self._get_partner_address(move),  # 買方地址
                    "A8": "",  # 買方負責人姓名
                    "A9": move.partner_id.phone or "",  # 買方電話
                    "A10": "",  # 買方傳真
                    "A11": move.partner_id.email or "",  # 買方電子郵件
                    "A12": move.partner_id.ref or "",  # 買方客戶編號
                    "A13": "",  # 買方營業人角色註記
                    "A14": "",  # 發票檢查碼 (MIG4.0不使用)
                    "A15": "",  # 買受人註記欄
                    "A16": "",  # 總備註
                    "A17": "",  # 通關方式註記
                    "A18": "",  # 稅捐稽徵處名稱 (不使用)
                    "A19": "",  # 核准日 (不使用)
                    "A20": "",  # 核准文 (不使用)
                    "A21": "",  # 核准號 (不使用)
                    "A22": move.invoice_track_id.invoice_category or "07",  # 發票類別
                    "A23": "",  # 彙開註記
                    "A24": "0",  # 捐贈註記 (0:非捐贈發票)
                    "A25": "",  # 載具類別號碼
                    "A26": "",  # 載具顯碼
                    "A27": "",  # 載具隱碼
                    "A28": "Y",  # 紙本電子發票已列印註記
                    "A29": "",  # 發票捐贈對象
                    "A30": move.einvoice_random_number or "0000",  # 發票防偽隨機碼
                    "A31": "",  # 零稅率原因
                    
                    # B 區塊 - 發票明細
                    "B": invoice_lines,
                    
                    # C 區塊 - 金額資訊
                    "C1": str(int(move.amount_untaxed or 0)),  # 應稅銷售額合計
                    "C2": "0",  # 免稅銷售額合計
                    "C3": "0",  # 零稅率銷售額合計
                    "C4": "1",  # 課稅別 (1:應稅)
                    "C5": "0.15",  # 稅率 (15%)
                    "C6": str(int(move.amount_tax or 0)),  # 營業稅額
                    "C7": str(int(move.amount_total or 0)),  # 總計
                    "C8": "0",  # 扣抵金額
                    "C9": "0",  # 原幣金額
                    "C10": "0.00",  # 匯率
                    "C11": "",  # 幣別
                    "C12": "",  # 備註一
                    "C13": "",  # 備註二
                    
                    # D 區塊 - 系統資訊
                    "D1": config['seller_id'],  # seller 統編
                    "D2": config['channel_key'],  # POS機出廠序號(通道金鑰)
                    "D3": config['pos_id'],  # POSID
                    "D4": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 系統時間
                    "EcrId": "",  # 收銀機序列號
                    "ACCOUNT": "0000000000000000",
                    "APPID": "0000000000000000",
                    "ServerType": "invioce_ml",
                    "SellerName": config['invoice_title'].seller_name or "",
                    "QRCodeASKey": ""
                }
            }
            
            result = self._send_request(payload)
            response = self._parse_c0401_response(result, move)
            
            return response
            
        except Exception as e:
            _logger.error(f"上傳發票明細失敗: {str(e)}")
            return {
                'success': False,
                'message': f"上傳發票明細失敗: {str(e)}"
            }


    # 取得合作夥伴完整地址
    def _get_partner_address(self, move):
        """取得合作夥伴完整地址"""
        partner = move.partner_id
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

    # 解析汎宇 C0401 上傳發票明細回應
    def _parse_c0401_response(self, result, move):
        """解析汎宇 C0401 上傳發票明細回應"""
        try:
            if 'INDEX' in result:
                reply = result['INDEX'].get('REPLY', '0')
                message = result['INDEX'].get('MESSAGE', '')
                error_code = result['INDEX'].get('ERROR_CODE', '')
                
                if reply == '1':
                    _logger.info(f"汎宇 C0401 上傳發票明細成功: {move.einvoice_number}")
                    
                    # 更新發票狀態
                    move.write({
                        'fanyuu_upload_time': fields.Datetime.now(),
                        'fanyuu_upload_status': 'uploaded'
                    })
                    
                    return {
                        'success': True,
                        'message': message or '上傳發票明細成功',
                        'invoice_number': move.einvoice_number,
                        'error_code': error_code
                    }
                else:
                    return {
                        'success': False,
                        'message': f"汎宇上傳發票明細失敗: {message}",
                        'error_code': error_code
                    }
            else:
                return {
                    'success': False,
                    'message': '汎宇回應格式錯誤'
                }
        except Exception as e:
            _logger.error(f"解析汎宇 C0401 上傳發票明細回應失敗: {str(e)}")
            return {
                'success': False,
                'message': f"解析回應失敗: {str(e)}"
            }
    
    # 解析發票號碼回應 (用於 C01)
    def _parse_invoice_number_response(self, result, invoice_track_id=None):
        """解析發票號碼回應 (用於 C01)"""
        try:
            if 'INDEX' in result:
                reply = result['INDEX'].get('REPLY', '0')
                message = result['INDEX'].get('MESSAGE', '')
                
                if reply == '1':
                    # 從 A01 或 C01 格式中取得發票號碼資訊
                    invoice_header = result['INDEX'].get('INVOICEHEADER', '')
                    invoice_start = result['INDEX'].get('INVOICESTART', '')
                    
                    if invoice_header and invoice_start:
                        # 格式化發票號碼
                        if len(invoice_start) == 8:
                            formatted_number = f"{invoice_header}-{invoice_start}"
                        else:
                            formatted_number = f"{invoice_header}{invoice_start}"
                        
                        _logger.info(f"汎宇取號成功: {formatted_number}")
                        
                        # 更新字軌記錄
                        if invoice_track_id:
                            self._update_track_last_number(invoice_track_id, formatted_number)
                        
                        return {
                            'success': True,
                            'invoice_number': formatted_number,
                            'raw_number': f"{invoice_header}{invoice_start}",
                            'message': message or '取號成功'
                        }
                    else:
                        return {
                            'success': False,
                            'invoice_number': None,
                            'message': '汎宇回應中沒有發票號碼資訊'
                        }
                else:
                    return {
                        'success': False,
                        'invoice_number': None,
                        'message': f"汎宇取號失敗: {message}"
                    }
            else:
                return {
                    'success': False,
                    'invoice_number': None,
                    'message': '汎宇回應格式錯誤'
                }
        except Exception as e:
            _logger.error(f"解析汎宇取號回應失敗: {str(e)}")
            return {
                'success': False,
                'invoice_number': None,
                'message': f"解析回應失敗: {str(e)}"
            }

    # 更新發票字軌的最後使用號碼
    def _update_track_last_number(self, invoice_track_id, invoice_number):
        """更新發票字軌的最後使用號碼"""
        try:
            track = self.env['invoice.track'].browse(invoice_track_id)
            if track.exists():
                track.write({
                    'last_fanyuu_number': invoice_number,
                    'last_used_number': invoice_number,
                    'fanyuu_sync_status': 'synced',
                    'fanyuu_success_count': track.fanyuu_success_count + 1
                })
                _logger.info(f"已更新字軌 {track.section_code} 的最後號碼為 {invoice_number}")
        except Exception as e:
            _logger.error(f"更新字軌最後號碼失敗: {str(e)}")

    # 作廢發票 (C0501)
    def cancel_invoice(self, invoice_number, invoice_date, buyer_id="0000000000", reason="客戶要求作廢", invoice_title_id=None):
        """作廢發票 (C0501)"""
        try:
            # 獲取對應的公司設定
            config = self._get_company_config(invoice_title_id)
            
            # 移除發票號碼中的連字號
            clean_invoice_number = invoice_number.replace('-', '')
            
            payload = {
                "Invoice": {
                    "INVOICE_CODE": "C0501",
                    "POSSN": config['channel_key'],
                    "POSID": config['pos_id'],
                    "INVOICE_NUMBER": clean_invoice_number,
                    "INVOICE_DATE": invoice_date,
                    "BUYERID": buyer_id,
                    "SELLERID": config['seller_id'],
                    "CANCEL_DATE": datetime.now().strftime('%Y-%m-%d'),
                    "CANCEL_TIME": datetime.now().strftime('%H:%M:%S'),
                    "CANCEL_REASON": reason,
                    "RETURNTAXDOCUMENT_NUMBER": "",
                    "REMARK": "",
                    "SYSTIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ACCOUNT": "0000000000000000",
                    "APPID": "0000000000000000"
                }
            }
            
            result = self._send_request(payload)
            
            # 解析回應
            if 'INDEX' in result:
                reply = result['INDEX'].get('REPLY', '0')
                message = result['INDEX'].get('MESSAGE', '')
                error_code = result['INDEX'].get('ERROR_CODE', '')
                
                if reply == '1':
                    _logger.info(f"發票作廢成功: {invoice_number}")
                    return {
                        'success': True,
                        'message': message or '發票作廢成功',
                        'invoice_number': invoice_number,
                        'error_code': error_code
                    }
                else:
                    return {
                        'success': False,
                        'message': f"發票作廢失敗: {message}",
                        'error_code': error_code
                    }
            else:
                return {
                    'success': False,
                    'message': '汎宇回應格式錯誤'
                }
                
        except Exception as e:
            _logger.error(f"發票作廢失敗: {str(e)}")
            return {
                'success': False,
                'message': f"發票作廢失敗: {str(e)}"
            }

    # 開立折讓證明單 (D0401)
    def create_allowance(self, allowance_data, invoice_title_id=None):
        """開立折讓證明單 (D0401)"""
        try:
            # 獲取對應的公司設定
            config = self._get_company_config(invoice_title_id)
            
            # 檢查必要欄位
            if not allowance_data.get('allowance_number'):
                raise ValidationError('缺少折讓證明單號碼')
            if not allowance_data.get('items'):
                raise ValidationError('缺少折讓明細資料')
            
            # 準備折讓明細 (D 區塊)
            items_data = []
            for i, item in enumerate(allowance_data.get('items', []), 1):
                # 驗證明細必要欄位
                if not item.get('original_invoice_number'):
                    raise ValidationError(f'第 {i} 項折讓明細缺少原發票號碼')
                if not item.get('original_description'):
                    raise ValidationError(f'第 {i} 項折讓明細缺少原品名')
                
                items_data.append({
                    "D1": str(i),  # 折讓證明單明細排列序號
                    "D2": item.get('original_invoice_date', ''),  # 原發票日期
                    "D3": item.get('original_invoice_number', '').replace('-', ''),  # 原發票號碼(不含連字號)
                    "D4": str(item.get('original_sequence_number', i)),  # 原明細排列序號
                    "D5": item.get('original_description', ''),  # 原品名
                    "D6": str(item.get('quantity', 1)),  # 數量
                    "D7": item.get('unit', ''),  # 單位
                    "D8": str(int(item.get('unit_price', 0))),  # 單價 (不含稅)
                    "D9": str(int(item.get('amount', 0))),  # 金額 (不含稅之進貨額)
                    "D10": str(int(item.get('tax', 0))),  # 營業稅額
                    "D11": str(item.get('tax_type', 1))  # 課稅別
                })
            
            _logger.info(f"準備開立折讓證明單: {allowance_data.get('allowance_number')}")
            _logger.debug(f"折讓明細數量: {len(items_data)}")
            
            payload = {
                "Invoice": {
                    "DISCOUNT_CODE": "D0401",
                    "POSID": config['pos_id'],
                    "SELLERID": config['seller_id'],
                    "POSSN": config['channel_key'],
                    "A1": allowance_data.get('allowance_number', ''),
                    "A2": datetime.now().strftime('%Y-%m-%d'),
                    "B1": allowance_data.get('buyer_id', '0000000000'),
                    "B2": allowance_data.get('buyer_name', ''),
                    "B3": allowance_data.get('buyer_address', ''),
                    "B4": allowance_data.get('buyer_person_in_charge', ''),
                    "B5": allowance_data.get('buyer_phone', ''),
                    "B6": allowance_data.get('buyer_fax', ''),
                    "B7": allowance_data.get('buyer_email', ''),
                    "B8": allowance_data.get('buyer_customer_number', ''),
                    "B9": allowance_data.get('buyer_role_remark', ''),
                    "C1": "2",
                    "C2": str(allowance_data.get('tax_amount', 0)),
                    "C3": str(allowance_data.get('total_amount', 0)),
                    "C4": allowance_data.get('original_invoice_seller_id', ''),
                    "C5": allowance_data.get('original_invoice_buyer_id', ''),
                    "D": items_data
                }
            }
            
            result = self._send_request(payload)
            
            if 'INDEX' in result:
                reply = result['INDEX'].get('REPLY', '0')
                message = result['INDEX'].get('MESSAGE', '')
                error_code = result['INDEX'].get('ERROR_CODE', '')
                
                if reply == '1':
                    allowance_number = allowance_data.get('allowance_number', '')
                    _logger.info(f"折讓證明單開立成功: {allowance_number}")
                    return {
                        'success': True,
                        'message': message or '折讓證明單開立成功',
                        'allowance_number': allowance_number,
                        'error_code': error_code
                    }
                else:
                    return {
                        'success': False,
                        'message': f"折讓證明單開立失敗: {message}",
                        'error_code': error_code
                    }
            else:
                return {
                    'success': False,
                    'message': '汎宇回應格式錯誤'
                }
                
        except Exception as e:
            _logger.error(f"折讓證明單開立失敗: {str(e)}")
            return {
                'success': False,
                'message': f"折讓證明單開立失敗: {str(e)}"
            }

    # 作廢折讓證明單 (D0501)
    def cancel_allowance(self, allowance_number, allowance_date, buyer_id="0000000000", reason="折讓作廢", invoice_title_id=None):
        """作廢折讓證明單 (D0501)"""
        try:
            # 獲取對應的公司設定
            config = self._get_company_config(invoice_title_id)
            
            payload = {
                "Invoice": {
                    "INVOICE_CODE": "D0501",
                    "POSSN": config['channel_key'],
                    "POSID": config['pos_id'],
                    "INVOICE_NUMBER": allowance_number,
                    "INVOICE_DATE": allowance_date,
                    "BUYERID": buyer_id,
                    "SELLERID": config['seller_id'],
                    "CANCEL_DATE": datetime.now().strftime('%Y-%m-%d'),
                    "CANCEL_TIME": datetime.now().strftime('%H:%M:%S'),
                    "CANCEL_REASON": reason,
                    "RETURNTAXDOCUMENT_NUMBER": "",
                    "REMARK": "",
                    "SYSTIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ACCOUNT": "0000000000000000",
                    "APPID": "0000000000000000",
                    "ALLOWANCETYPE": "2"
                }
            }
            
            result = self._send_request(payload)
            
            # 解析回應
            if 'INDEX' in result:
                reply = result['INDEX'].get('REPLY', '0')
                message = result['INDEX'].get('MESSAGE', '')
                error_code = result['INDEX'].get('ERROR_CODE', '')
                
                if reply == '1':
                    _logger.info(f"折讓證明單作廢成功: {allowance_number}")
                    return {
                        'success': True,
                        'message': message or '折讓證明單作廢成功',
                        'allowance_number': allowance_number,
                        'error_code': error_code
                    }
                else:
                    return {
                        'success': False,
                        'message': f"折讓證明單作廢失敗: {message}",
                        'error_code': error_code
                    }
            else:
                return {
                    'success': False,
                    'message': '汎宇回應格式錯誤'
                }
                
        except Exception as e:
            _logger.error(f"折讓證明單作廢失敗: {str(e)}")
            return {
                'success': False,
                'message': f"折讓證明單作廢失敗: {str(e)}"
            }

    # 動態添加公司對應設定
    def add_company_mapping(self, seller_tax_id, pos_id, channel_key):
        """動態添加公司對應設定"""
        self.company_mapping[seller_tax_id] = {
            'pos_id': pos_id,
            'channel_key': channel_key
        }
        _logger.info(f"已添加統編 {seller_tax_id} 的汎宇設定")

    # 取得可用的公司統編列表
    def get_available_companies(self):
        """取得可用的公司統編列表"""
        return list(self.company_mapping.keys())

    # 取得當前發票號碼狀態
    def get_current_invoice_status(self, seller_id=None):

        """取得當前發票號碼狀態"""
        if seller_id:
            pool_status = self.get_pool_status(seller_id)
            if pool_status['exists']:
                return {
                    'success': True,
                    'data': {
                        'track': pool_status['invoice_header'],
                        'total': pool_status['total_numbers'],
                        'used': pool_status['used_numbers'],
                        'remaining': pool_status['remaining_numbers'],
                        'usage_percentage': pool_status['usage_percentage'],
                        'pool_health': pool_status['pool_health']
                    }
                }
        
        return {
            'success': False,
            'message': '尚未取得發票號碼區間或統編不存在'
        }
    
    # 取得系統時間 (Y01)
    def get_system_time(self, invoice_title_id=None):
        """取得系統時間 (Y01)"""
        try:
            config = self._get_company_config(invoice_title_id)
            
            payload = {
                "INDEX": {
                    "FUNCTIONCODE": "Y01",
                    "SELLERID": config['seller_id'],
                    "POSID": config['pos_id'],
                    "POSSN": config['channel_key'],
                    "SYSTIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "REPLY": "",
                    "MESSAGE": "",
                    "VERIONUPDATE": "",
                    "ACCOUNT": "0000000000000000",
                    "APPID": "0000000000000000",
                    "ServerType": "invioce_ml",
                    "APPVSERION": "V1.0",
                    "USERID": "",
                    "EcrId": ""
                }
            }
            
            result = self._send_request(payload)
            
            if 'INDEX' in result:
                reply = result['INDEX'].get('REPLY', '0')
                message = result['INDEX'].get('MESSAGE', '')
                
                if reply == '1':
                    system_time = result['INDEX'].get('SYSTIME', '')
                    _logger.info(f"汎宇系統時間: {system_time}")
                    
                    return {
                        'success': True,
                        'system_time': system_time,
                        'message': message or '取得系統時間成功'
                    }
                else:
                    return {
                        'success': False,
                        'system_time': None,
                        'message': f"取得系統時間失敗: {message}"
                    }
            else:
                return {
                    'success': False,
                    'system_time': None,
                    'message': '汎宇回應格式錯誤'
                }
                
        except Exception as e:
            _logger.error(f"取得系統時間失敗: {str(e)}")
            return {
                'success': False,
                'system_time': None,
                'message': f"取得系統時間失敗: {str(e)}"
            }
    
    
    # 取得下期發票字軌資訊 (C01)
    def get_next_period_track_info(self, invoice_title_id=None):
        """取得下期發票字軌資訊 (C01)"""
        try:
            config = self._get_company_config(invoice_title_id)
            
            payload = {
                "INDEX": {
                    "FUNCTIONCODE": "C01",
                    "SELLERID": config['seller_id'],
                    "POSID": config['pos_id'],
                    "POSSN": config['channel_key'],
                    "SYSTIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "REPLY": "",
                    "MESSAGE": "",
                    "VERIONUPDATE": "",
                    "ACCOUNT": "0000000000000000",
                    "APPID": "0000000000000000",
                    "ServerType": "invioce_ml",
                    "APPVSERION": "V1.0",
                    "USERID": "",
                    "TAXMONTH": "",
                    "INVOICEHEADER": "",
                    "INVOICESTART": "",
                    "INVOICEEND": "",
                    "INVOICENUMBER": "",
                    "SECURITY": "",
                    "SELLDETAIL": "",
                    "CHECKSUM": "",
                    "EcrId": ""
                }
            }
            
            result = self._send_request(payload)
            response = self._parse_a01_response(result)  # 重用解析方法
            response['seller_tax_id'] = config['seller_id']
            response['company_name'] = config['invoice_title'].seller_name
            
            if response['success']:
                _logger.info(f"取得下期字軌資訊成功: {response['track_info']['invoice_header']}")
            
            return response
            
        except Exception as e:
            _logger.error(f"汎宇取下期字軌資訊失敗: {str(e)}")
            return {
                'success': False,
                'track_info': None,
                'message': f"取下期字軌資訊失敗: {str(e)}",
                'seller_tax_id': None
            }
