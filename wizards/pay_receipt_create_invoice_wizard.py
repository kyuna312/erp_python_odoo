from odoo import api, fields, models, _, registry, SUPERUSER_ID
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import threading
import logging
from itertools import groupby
import concurrent.futures
import requests

logger = logging.getLogger('pay.receipt.create.invoice :')
def send_request(url, data):
    try:
        response = requests.post(url, json=data)
        return response.status_code
    except requests.RequestException as e:
        return e

class PayReceiptCreateInvoice(models.TransientModel):
    _name = 'pay.receipt.create.invoice'
    pay_receipt_id = fields.Many2one('pay.receipt', 'Төлбөрийн баримт', required=True)

    def create_invoice_test(self, invoice_list:list):
        CHUNK_SIZE = 100
        splited_lenght = int(len(invoice_list)/CHUNK_SIZE)+1

        url = f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/ub_kontor/account_move/create_invoice"
        futures = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            for i in range(splited_lenght):
                data = {
                    "jsonrpc": "2.0",
                    "params": {
                        "invoice_list": invoice_list[:CHUNK_SIZE]
                    }
                }
                futures += [executor.submit(send_request, url, data)]
                del invoice_list[:CHUNK_SIZE]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()



    def create_account_moves(self, db_name, _context, data):
        db_registry = registry(db_name)
        with api.Environment.manage(), db_registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, _context)
            env['account.move'].create(data)


    def create_invoice_v2(self):
        for obj in self:
            self.env.cr.execute(f"""
                select ra.code as payment_reference, round(cast(pra.total_amount as numeric),2) as amount_total, round(cast(pra.total_amount as numeric),2) as amount_residual, 
                round(cast(pra.noat as numeric),2) as amount_tax, round(cast(pra.amount as numeric),2) as amount_untaxed, pr.company_id as company_id, pra.id as receipt_address_id, pra.address_id as address_id,
                pr.year as year, pr.month as month, count(prai.id) as invoice_count
                from pay_receipt_address pra 
                inner join ref_address ra on ra.id = pra.address_id 
                inner join pay_receipt pr on pr.id = pra.receipt_id
                left join pay_receipt_address_invoice prai on prai.receipt_address_id = pra.id
                where pr.id = {obj.pay_receipt_id.id}
                group by pra.id, pr.id, ra.id
                having count(prai.id) = 0
            """)
            invoice_data = self.env.cr.dictfetchall()
            invoice_data = [
                {
                    'payment_reference': invoice.get('payment_reference'),
                    'amount_total': invoice.get('amount_total'),

                    'amount_residual': invoice.get('amount_residual'),
                    'amount_tax': invoice.get('amount_tax'),
                    'amount_untaxed': invoice.get('amount_untaxed'),

                    'company_id': invoice.get('company_id'),
                    'receipt_address_id': invoice.get('receipt_address_id'),
                    'address_id': invoice.get('address_id'),
                    'year': invoice.get('year'),
                    'month': invoice.get('month'),
                    'payment_state': 'not_paid',
                    'state': 'posted',
                } for invoice in invoice_data
            ]
            self.env['pay.receipt.address.invoice'].create(invoice_data)
            self.env.cr.execute(f"""
                select pra.receipt_id from pay_receipt_address pra 
                left join pay_receipt_address_invoice prai on prai.receipt_address_id = pra.id
                where prai.id is null and pra.receipt_id = {obj.pay_receipt_id.id}
            """)
            obj.pay_receipt_id.clear_invoice_difference()
            if(not self.env.cr.dictfetchall()):
                self.env.cr.execute(f"""
                    UPDATE pay_receipt set state = 'invoice_created' where id = {obj.pay_receipt_id.id} 
                """)
