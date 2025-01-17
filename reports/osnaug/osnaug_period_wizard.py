from odoo import api, fields, models
from odoo.exceptions import UserError

ADDRESS_TYPE = [
  ('OS', 'Орон сууц'),
  ('AAN', 'Аж ахуй нэгж'),
]


class OsnaugPeriodWizard(models.TransientModel):
  _name = 'osnaug.period.wizard'
  _description = 'ОСНААУГ Санхүүгийн Мөчлөг Wizard'

  address_type = fields.Selection(ADDRESS_TYPE, string='Тоотын төрөл', required=True, default='OS')

  def action_get_osnaug_period(self):
    self.ensure_one()
    osnaug_period_obj = self.env['osnaug.period']
    address_type = self.address_type

    query = """
            SELECT pp.id as period_id, pp.name as period_company_name, pp.year as period_year,
                   pp.month as period_month, pp.state as period_state, pp.company_id as period_company_id, pp.address_type as period_address_type
            FROM pay_period pp
            WHERE pp.address_type = %s
            ORDER BY pp.name
        """
    self.env.cr.execute(query, (address_type,))
    pay_periods = self.env.cr.dictfetchall()

    if not pay_periods:
      raise UserError("Хүснэгт олдсонгүй.")

    existing_period_names = set(
      self.env['osnaug.period'].search([('name', 'in', [p['period_company_name'] for p in pay_periods])]).mapped('name')
    )
    new_periods = [
      p for p in pay_periods
      if p['period_company_name'] not in existing_period_names
    ]

    if new_periods:
      try:
        for p in new_periods:
          if not osnaug_period_obj.search([('name', '=', p['period_company_name'])]):
            osnaug_period_obj.create({
              'name': p['period_company_name'],
              'year': p['period_year'],
              'month': p['period_month'],
              'address_type': p['period_address_type'],
              'state': p['period_state'],
              'company_id': p['period_company_id']
            })
      except Exception as e:
        raise UserError(f"Failed to create osnaug.period records: {str(e)}")

    # Return the action to display the tree view of osnaug.period
    return {
      'type': 'ir.actions.act_window',
      'name': 'ОСНААУГ Санхүүгийн Мөчлөг',
      'res_model': 'osnaug.period',
      'view_mode': 'tree,form',
      'target': 'current',
      'views': [
        (self.env.ref('ub_kontor.view_osnaug_period_tree').id, 'tree'),
        (self.env.ref('ub_kontor.view_osnaug_period_form').id, 'form')
      ],
      'context': {'search_default_filter': 1}  # Optional: Adjust the context as needed
    }
