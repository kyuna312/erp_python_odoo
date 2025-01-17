from datetime import datetime
from odoo import api, fields, models

ADDRESS_TYPE = [
  ('OS', 'Орон сууц'),
  ('AAN', 'Аж ахуй нэгж'),
]


def get_years():
  curr_year = int(datetime.now().strftime('%Y'))
  return [(str(year), str(year)) for year in range(curr_year, 2019, -1)]


class OsnaugPeriod(models.Model):
  _name = 'osnaug.period'
  _description = 'ОСНААУГ Санхүүгийн Мөчлөг'

  _sql_constraints = [
    ('account_period_unique', 'unique(name)', 'Санхүүгийн мөчлөг давхцаж байна!')
  ]

  name = fields.Char(string='Name', required=True)
  year = fields.Char(string='Year', required=False, default=lambda self: str(datetime.now().year))
  month = fields.Selection(
    [(f'{str(i).zfill(2)}', f'{i}-р сар') for i in range(1, 13)],
    string='Сар',
    required=False
  )
  address_type = fields.Selection(
    ADDRESS_TYPE,
    string='Тоотын төрөл',
    default='OS',
    required=False,
  )
  state = fields.Char(string='State')
  company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

  @api.model
  def get_years(self):
    curr_year = int(datetime.now().strftime('%Y'))
    return [(str(year), str(year)) for year in range(curr_year, 2019, -1)]

  @api.model
  def get_months(self):
    return [(f'{str(i).zfill(2)}', f'{i}-р сар') for i in range(1, 13)]
