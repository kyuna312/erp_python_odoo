from datetime import datetime

from odoo import api, fields, models

ADDRESS_TYPE = [
  ('OS', 'Орон сууц'),
  ('AAN', 'Аж ахуй нэгж'),
]

PAY_RECEIPT_STATE = [
  ('draft', 'Ноорог'),
  ('confirmed', 'Баталгаажсан'),
  ('invoice_created', 'Нэхэмжлэл үүссэн'),
  ('cancelled', 'Цуцалсан')
]


class OsnaugPayReceipt(models.Model):
  _name = 'osnaug.pay.receipt'
  _description = 'ОСНААУГ Төлбөрийн Нэхэмжлэл'

  _sql_constraints = [
    ('pay_receipt_unique', 'unique(name)', 'Төлбөрийн нэхэмжлэл давхцаж байна!')
  ]

  name = fields.Char(string='Name', required=True)
  year = fields.Selection(
    selection='_get_years',
    string='Year',
    required=True,
    default=lambda self: str(datetime.now().year)
  )
  month = fields.Selection(
    [(f'{str(i).zfill(2)}', f'{i}-р сар') for i in range(1, 13)],
    string='Month',
    required=True
  )
  company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
  company_name = fields.Char(string='Company Name', related='company_id.name', store=True)
  address_type = fields.Selection(ADDRESS_TYPE, string='Address Type', required=True, default='OS')
  date = fields.Date('Огноо', default=fields.Date.today)
  state = fields.Selection(PAY_RECEIPT_STATE, string='State')
  amount = fields.Float(string='Amount')
  total_amount = fields.Float(string='Total Amount')

  @api.model
  def _get_years(self):
    current_year = int(datetime.now().strftime('%Y'))
    return [(str(year), str(year)) for year in range(current_year, 2019, -1)]
