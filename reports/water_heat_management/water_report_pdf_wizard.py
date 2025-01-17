from collections import defaultdict
from itertools import groupby
from odoo import models, fields, api
from odoo.exceptions import UserError


class WaterReportPdfWizard(models.TransientModel):
  _name = 'water.report.pdf.wizard'
  _description = 'Water Report Pdf Wizard'

  company_id = fields.Many2one('res.company', string='ХҮТ', default=lambda self: self.env.user.company_id.id)
  address_type = fields.Selection([('OS', 'ОС'), ('AAN', 'ААН')], string='Address Type', required=True,
                                  default=lambda self: self.env.user.access_type)
  water_report_date = fields.Selection(selection='_get_water_report_date_selection', string='Хугацаа сонгох',
                                       required=True)
  water_report_year = fields.Char(string='Water Report Year', compute='_compute_water_report_year')
  date = fields.Date(string='Хугацаа сонгох', default=fields.Date.today)

  @api.depends('water_report_date')
  def _compute_water_report_year(self):
    for record in self:
      if record.water_report_date:
        year, month = record.water_report_date.split('/')
        record.water_report_year = f"{year} Year {month}"

  @api.model
  def _get_water_report_date_selection(self):
    query = """
            SELECT DISTINCT TO_CHAR(TO_DATE(CONCAT(year, '-', month, '-01'), 'YYYY-MM-DD'), 'YYYY/MM') AS invoice_date
            FROM pay_receipt_address_invoice
            WHERE year IS NOT NULL AND month IS NOT NULL
                AND TO_DATE(CONCAT(year, '-', month, '-01'), 'YYYY-MM-DD') >= '2024-01-01'
            ORDER BY invoice_date
        """
    self.env.cr.execute(query)
    return [(result[0], result[0]) for result in self.env.cr.fetchall()]

  def _execute_query(self, query):
    self.env.cr.execute(query)
    return self.env.cr.dictfetchall()

  def _get_water_report(self, water_report_date):
    if not water_report_date:
      raise UserError("No Residual Date provided.")

    # Extract year and month from the input date
    year, month = map(int, water_report_date.split('/'))

    # Fetch the raw data from the database
    results = self._fetch_water_report_data(self.address_type, self.company_id.id, year, month)

    # Sort the results by apartment_id
    sorted_data = sorted(results, key=lambda x: x['apartment_id'])

    # Group the data by apartment_id
    grouped_data = defaultdict(list)
    for apartment_id, group in groupby(sorted_data, key=lambda x: x['apartment_id']):
      for item in group:
        grouped_data[apartment_id].append({
          'apartment_id': item.get('apartment_id', ''),
          'apartment_code': item.get('apartment_code', ''),
          'customer_name': item.get('customer_name', ''),
          'address': item.get('address', ''),
          'address_family': item.get('address_family', 0),
          'square': item.get('square', 0),
          'total_difference': item.get('total_difference', 0),
          'hot_water': item.get('hot_water', 0),
          'cold_water_difference': item.get('cold_water_difference', 0),
        })

    # Prepare the data for the report
    return (
      grouped_data,
      self.address_type,
      self.get_company_name(self.company_id.id),
      water_report_date,
      self.image_data_uri(self.company_id.logo),
    )

  def _fetch_water_report_data(self, address_type, company_id, year, month):
    query = f"""
         SELECT 
            apartment.id apartment_id, 
            apartment.code as apartment_code, 
            address.name as customer_name, 
            address.address as address, 
            address.family as address_family, 
            square.square,
            CASE 
                WHEN counter_line.counter_type = 'hot_water' THEN counter_line.difference 
                ELSE 0 
            END + 
            CASE 
                WHEN counter_line.counter_type = 'cold_water' THEN counter_line.difference 
                ELSE 0 
            END AS total_difference,
            case when counter_line.counter_type = 'hot_water' then counter_line.difference else 0 end as hot_water,
            case when counter_line.counter_type = 'cold_water' then counter_line.difference else 0  end as cold_water_difference
         FROM counter_counter_line_group counter_line_group
         INNER JOIN counter_counter_line counter_line ON counter_line.group_id = counter_line_group.id AND counter_line.counter_category = 'counter'
         INNER JOIN counter_counter counter ON counter.id = counter_line.counter_id
         INNER JOIN ref_address address ON address.id = counter_line.address_id
         INNER JOIN ref_apartment apartment ON apartment.id = address.apartment_id
         LEFT JOIN (
            SELECT address.id as address_id, SUM(square.square) as square
            FROM ref_address_square square
            INNER JOIN ref_address address ON address.id = square.address_id AND address.company_id = {company_id}
            WHERE square.state='active'
            GROUP BY address.id
         ) square ON square.address_id = address.id
         WHERE counter_line_group.company_id = {company_id} AND counter_line_group.address_type = '{address_type}' AND counter_line_group.year::integer={year} AND counter_line_group.month::integer={month}
         ORDER BY apartment.id, address.id DESC
    """
    return self._execute_query(query)

  def download(self):
    grouped_data, address_type, company_name, date, logo_data_uri = self._get_water_report(self.water_report_date)
    report_action = self.env.ref('ub_kontor.action_water_report_pdf', raise_if_not_found=False)

    return report_action.report_action(
      self,
      data={
        'grouped_data': grouped_data,
        'company_id': self.company_id.id,
        'address_type': self.get_address_type_display(self.address_type),
        'company_name': company_name,
        'water_report_date': self.water_report_date,
        'report_date': date,
        'logo_data_uri': logo_data_uri,
        'user_balance_list_date': self.water_report_date
      }
    )

  def image_data_uri(self, logo):
    return f'data:image/png;base64,{logo.decode()}' if logo else ''

  def get_company_name(self, company_id):
    company = self.env['res.company'].browse(company_id)
    return company.name if company else 'Unknown Company'

  def get_address_type_display(self, address_type):
    return dict(self._fields['address_type'].selection).get(address_type, '')
