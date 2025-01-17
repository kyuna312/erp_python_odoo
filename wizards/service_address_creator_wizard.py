from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime


def get_years():
    year_list = []
    curr_year = int(datetime.now().strftime('%Y'))
    for i in range(curr_year, 2019, -1):
        year_list.append((str(i), str(i)))
    return year_list


class ServiceAddressCreator(models.TransientModel):
    _name = 'service.address.creator'

    address_ids = fields.Many2many('ref.address', string='Тоот', required=False)
    description = fields.Text('Тайлбар', required=False)
    value = fields.Float('Утга', default=1.0, required=False)
    percent = fields.Float('Хувь', default=100.0, required=False)
    service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээ', required=False, domain="[('org_id', '=', org_id)]")
    org_id = fields.Many2one('ref.organization', 'Байгууллага', required=False)
    is_noat = fields.Boolean('НӨАТ тооцох', default=False)
    pricelist_id = fields.Many2one('ref.pricelist', 'Тариф', domain="[('service_type_id', '=', service_type_id)]")
    year = fields.Selection(get_years(), string="Он", required=False)
    month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Сар', required=False)
    day = fields.Integer('Өдөр', default=30)
    price = fields.Float('Үнийн дүн')
    type = fields.Selection([
        ('user_service', 'Хэрэглэгчийн үйлчилгээ'),
        ('additional_service', 'Нэмэлт үйлчилгээ')
    ])

    def create_lines(self):
        ids = []
        for address in self.address_ids:
            obj = self.env['service.address'].create({
                'description': self.description,
                'value': self.value,
                'percent': self.percent,
                'service_type_id': self.service_type_id.id,
                'org_id': self.org_id.id,
                'is_noat': self.is_noat,
                'pricelist_id': self.pricelist_id.id,
                'day': self.day,
                'price': self.price,
                'type': self.type,
                'address_id': address.id,
                'year': self.year,
                'month': self.month
            })
            ids.append(obj.id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Амжилттай үүслээ',
                'message': 'Үйлчилгээ амжилттай үүслээ.',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                }
            }
        }