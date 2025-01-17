from odoo import http
from odoo.http import request
from datetime import datetime, timedelta
from urllib.parse import quote
import requests
import threading
import logging

_logger = logging.getLogger('ub_kontor controller')
class KontorInvoiceController(http.Controller):
    pass
    # @http.route('/ub_kontor/account_move/create_invoice', type='json', auth='public', methods=['POST'], csrf=False)
    # def create_invoice(self, **rec):
    #     _logger.warning("~~~~~~~~~~~~~~~~~~~~~ working ~~~~~~~~~~~~~~~~~~~~~~~~~~`")
    #     _logger.warning(f"~~~~~~~~~~~~~~~~~~~~~ {rec} ~~~~~~~~~~~~~~~~~~~~~~~~~~")
    #     if (rec.get('invoice_list')):
    #         request.env['account.move'].sudo().create(rec.get('invoice_list'))
    #         _logger.warning(f'~~~~~~~~~~~~~~~~~~~~~ DONE ~~~~~~~~~~~~~~~~~~~~~~~~')
    #         return {'message': 'successful'}
