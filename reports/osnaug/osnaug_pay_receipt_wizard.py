from odoo import api, fields, models
from odoo.exceptions import UserError
from datetime import datetime

ADDRESS_TYPE = [
  ('OS', 'Орон сууц'),
  ('AAN', 'Аж ахуй нэгж'),
]


class OsnaugPayReceiptWizard(models.TransientModel):
  _name = 'osnaug.pay.receipt.wizard'
  _description = 'ОСНААУГ Төлбөрийн Нэхэмжлэл Wizard'

  year = fields.Selection(
    selection=lambda self: self._get_years(),
    string='Year',
    required=True,
    default=lambda self: str(datetime.now().year)
  )
  month = fields.Selection(
    selection=lambda self: self._get_months(),
    string='Month',
    required=True
  )
  address_type = fields.Selection(ADDRESS_TYPE, string='Address Type', required=True, default='OS')

  @api.model
  def _get_years(self):
    current_year = int(datetime.now().strftime('%Y'))
    return [(str(year), str(year)) for year in range(current_year, 2019, -1)]

  @api.model
  def _get_months(self):
    return [(f'{str(i).zfill(2)}', f'{i}-р сар') for i in range(1, 13)]

  def action_get_osnaug_pay_receipt(self):
    self.ensure_one()
    osnaug_pay_receipt_obj = self.env['osnaug.pay.receipt']
    year, month, address_type = self.year, self.month, self.address_type

    query = """
            WITH numbered_receipts AS (
                SELECT
                    pr.name, pr.year, pr.month, pr.company_id,
                    rc.name AS company_name, pr.state,
                    SUM(ROUND(CAST(pral.amount AS NUMERIC), 2)) AS amount,
                    SUM(ROUND(CAST(pral.total_amount AS NUMERIC), 2)) AS total_amount,
                    ROW_NUMBER() OVER (PARTITION BY pr.name ORDER BY pr.company_id) as row_num
                FROM pay_receipt pr
                INNER JOIN pay_receipt_address pra ON pra.receipt_id = pr.id
                INNER JOIN pay_receipt_address_line pral ON pral.receipt_address_id = pra.id
                INNER JOIN res_company rc ON rc.id = pr.company_id
                WHERE pr.year = %s AND pr.month = %s AND pr.address_type = %s
                GROUP BY pr.name, pr.year, pr.month, pr.company_id, rc.name, pr.state
            )
            SELECT 
                CASE 
                    WHEN row_num > 1 THEN name || '-' || row_num
                    ELSE name 
                END as name,
                year, month, company_id, company_name, state, amount, total_amount
            FROM numbered_receipts
            ORDER BY name
        """

    self.env.cr.execute(query, (year, month, address_type))
    pay_receipts = self.env.cr.dictfetchall()

    if not pay_receipts:
      raise UserError("Сонгосон огнооны төлбөрийн нэхэмжлэл олдсонгүй.")

    for receipt in pay_receipts:
      try:
        # Create savepoint for each record
        self.env.cr.execute('SAVEPOINT osnaug_receipt_save')

        # Check if receipt exists
        existing_receipt = osnaug_pay_receipt_obj.search([
          ('name', '=', receipt['name']),
          ('company_id', '=', receipt['company_id'])
        ], limit=1)

        receipt_vals = {
          'year': receipt['year'],
          'month': receipt['month'],
          'state': receipt['state'],
          'amount': receipt['amount'],
          'total_amount': receipt['total_amount'],
          'address_type': address_type,
        }

        if existing_receipt:
          existing_receipt.write(receipt_vals)
        else:
          receipt_vals.update({
            'name': receipt['name'],
            'company_id': receipt['company_id'],
            'date': fields.Date.today(),
          })
          osnaug_pay_receipt_obj.create(receipt_vals)

        self.env.cr.execute('RELEASE SAVEPOINT osnaug_receipt_save')

      except Exception as e:
        self.env.cr.execute('ROLLBACK TO SAVEPOINT osnaug_receipt_save')
        raise UserError(f"Error processing receipt {receipt['name']}: {str(e)}")

    # Return the action to display the tree view of osnaug.pay.receipt
    return {
      'type': 'ir.actions.act_window',
      'name': 'ОСНААУГ Санхүүгийн Төлбөрийн баримт',
      'res_model': 'osnaug.pay.receipt',
      'view_mode': 'tree,form',
      'target': 'current',
      'views': [
        (self.env.ref('ub_kontor.view_osnaug_pay_receipt_tree').id, 'tree'),
        (self.env.ref('ub_kontor.view_osnaug_pay_receipt_form').id, 'form')
      ],
      'context': {'search_default_filter': 1}  # Optional: Adjust the context as needed
    }
