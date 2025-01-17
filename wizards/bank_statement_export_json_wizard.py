import requests

from odoo import api, fields, models, _
import json
import base64

from odoo.addons.test_convert.tests.test_env import field
from odoo.exceptions import UserError, ValidationError
from datetime import datetime

from odoo.http import request
import mimetypes

class BankStatementExportJson(models.TransientModel):
    _name = "bank.statement.export.json"


    receipt_id = fields.Many2one('pay.receipt', 'Төлбөрийн баримт', required=True)
    method = fields.Selection([('receipt','Төлбөрийн баримтаар'),('apartment', 'Байр'),('address', 'Тоот')], required=True)

    url = fields.Char('холбоос', compute="_compute_url", store=False)

    result_html = fields.Html(default='', readonly=True)
    apartment_id = fields.Many2one('ref.apartment', string='Байрнууд')
    address_ids = fields.Many2many('ref.address', string='Тоотууд')
    file = fields.Binary('file')

    @api.depends('receipt_id')
    def _compute_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('ub_kontor.kontor_web')
        if(not self.method):
            self.url = ''
            return
        if(self.method == 'address'):
            # self.url = f'{base_url}/bank/bl_single/{self.address_ids.ids}/?token=kdisoe9e93eiiwow;;830woieafj24&pay_receipt={self.receipt_id.id}'
            response = requests.post(f"{base_url}/bank/multiple", json={
                "token": "kdisoe9e93eiiwow;;830woieafj24",
                "pay_receipt_id": self.receipt_id.id,
                "address_ids": self.address_ids.ids
            })
            if(response.status_code in (200, 201)):
                file_content = response.content
                content_type = response.headers.get('Content-Type', '')
                extension = mimetypes.guess_extension(content_type)
                file_data_base64 = base64.b64encode(file_content)
                self.result_html = f"<h2>Ачаалсан өгөгдлийн нийт дүн: {response.headers._store.get('x-total-amount')[1]}₮</h2>"
                self.write({
                    'file': file_data_base64
                })
                name = f'kontor_pay_receipt{extension}'
                self.url = f'/web/content/?model=bank.statement.export.json&id={self.id}&field=file&filename_field={name}&download=true&filename={name}'
            else:
                self.url = f''
        elif(self.method == 'apartment'):
            self.url = f"{base_url}/bank/files/?token=kdisoe9e93eiiwow;;830woieafj24&pay_receipt={self.receipt_id.id}&apartment={self.apartment_id.id}"
            response = requests.get(self.url)
            if(response.status_code == 200):
                self.result_html = f"<h2>Ачаалсан өгөгдлийн нийт дүн: {response.headers._store.get('x-total-amount')[1]}₮</h2>"

        elif(self.method == 'receipt'):
            self.url = f"{base_url}/bank/files/?token=kdisoe9e93eiiwow;;830woieafj24&pay_receipt={self.receipt_id.id}&apartment="
            response = requests.get(self.url)
            if (response.status_code == 200):
                self.result_html = f"<h2>Ачаалсан өгөгдлийн нийт дүн: {response.headers._store.get('x-total-amount')[1]}₮</h2>"
            # response = requests.get(f"{base_url}/bank/bl_log/?token=kdisoe9e93eiiwow;;830woieafj24&pay_receipt={self.receipt_id.id}&apartment=")
            # if(response.status_code == 200):
            #     response = response.json()
            #     self.result_html = f"<h2>Нийт ачаалалсан өгөгдлийн хэмжээ: {response.get('total')}</h2>"


    def export(self):
        result =  {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": self.url,
        }
        return result