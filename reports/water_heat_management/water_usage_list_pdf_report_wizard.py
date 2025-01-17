from collections import defaultdict
from itertools import groupby
from odoo import models, fields, api
from odoo.exceptions import UserError


class WaterUsageListPdfReportWizard(models.TransientModel):
  _name = 'water.usage.list.pdf.report.wizard'
  _description = 'Water Usage List Pdf Report Wizard'

  company_id = fields.Many2one(
    'res.company', string='ХҮТ', default=lambda self: self.env.user.company_id.id
  )
  address_type = fields.Selection(
    [('OS', 'ОС'), ('AAN', 'ААН')], string='Address Type', required=True,
    default=lambda self: self.env.user.access_type
  )
  water_usage_date = fields.Selection(
    selection='_get_water_usage_date_selection', string='Хугацаа сонгох', required=True
  )
  water_usage_year = fields.Char(
    string='Water Usage Year', compute='_compute_water_usage_year'
  )
  date = fields.Date(
    string='Хугацаа сонгох', default=fields.Date.today
  )

  @api.depends('water_usage_date')
  def _compute_water_usage_year(self):
    for record in self:
      date = record.water_usage_date
      record.water_usage_year = f"{date.split('/')[0]} Year {date.split('/')[1]}" if date else ''

  @api.model
  def _get_water_usage_date_selection(self):
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

  def _get_water_usage_report(self, water_usage_date):
    if not water_usage_date:
      raise UserError('No Residual Date provided.')

    year, month = map(int, water_usage_date.split('/'))
    results = self._fetch_water_report_data(self.address_type, self.company_id.id, year, month)
    sorted_data = sorted(results, key=lambda x: x['address_id'])

    grouped_data = defaultdict(lambda: {
      'address_id': None,
      'address_address': '',
      'family': 0,
      'counters': [],
      'total_difference': 0  # Энд нэмэгдэж байна
    })

    for key, group in groupby(sorted_data, key=lambda x: x['address_id']):
      for data in group:
        grouped_data[key]['address_id'] = data['address_id']
        grouped_data[key]['address_address'] = data['address_address']
        grouped_data[key]['family'] = data['family']
        grouped_data[key]['counters'].append({
          'counter_name': data['counter_name'],
          'first_counter': data['first_counter'],
          'last_counter': data['last_counter'],
          'difference': data['difference']
        })
        grouped_data[key]['total_difference'] += data['difference']

    grouped_data = dict(grouped_data)
    return (
      grouped_data,
      self.address_type,
      self.get_company_name(self.company_id.id),
      self.date,
      self.image_data_uri(self.company_id.logo),
      self.get_header_data()
    )

  def _fetch_water_report_data(self, address_type, company_id, year, month):
    query = f"""
            SELECT
              address.id as address_id, concat(apartment.code, '-', address.address) as address_address,
              address.family as family, counter_line.counter_name as counter_name,
              counter_line.now_counter as first_counter, counter_line.last_counter as last_counter,
              counter_line.difference as difference
            FROM counter_counter_line_group counter_line_group
            INNER JOIN counter_counter_line counter_line ON counter_line.group_id = counter_line_group.id
            INNER JOIN ref_address address ON address.id = counter_line.address_id
            INNER JOIN ref_apartment apartment ON address.apartment_id = apartment.id
            WHERE counter_line_group.company_id = {company_id} AND counter_line_group.address_type = '{address_type}'
              AND counter_line_group.year::integer = {year} AND counter_line_group.month::integer = {month}
            ORDER BY address.id, counter_line.counter_name
        """
    return self._execute_query(query)

  def get_header_data(self):
    return [
      {'counter_name': 'Ванн халуун ус', 'display_name': 'Ванн - Халуун ус'},
      {'counter_name': 'Ванн хүйтэн ус', 'display_name': 'Ванн - Хүйтэн ус'},
      {'counter_name': 'Гал тогоо хүйтэн ус', 'display_name': 'Гал тогоо - Хүйтэн ус'},
      {'counter_name': 'Гал тогоо халуун ус', 'display_name': 'Гал тогоо - Халуун ус'},
      {'counter_name': 'Халуун ус', 'display_name': 'Халуун ус'},
      {'counter_name': 'Хүйтэн ус', 'display_name': 'Хүйтэн ус'},
      {'counter_name': 'Халуун ус буцах', 'display_name': 'Халуун ус буцах'}
    ]

  def download(self):
    grouped_data, address_type, company_name, date, logo_data_uri, header_data = self._get_water_usage_report(
      self.water_usage_date)
    report_action = self.env.ref('ub_kontor.action_water_usage_list_pdf_report', raise_if_not_found=False)

    if not report_action:
      raise UserError('Action not found.')

    return report_action.report_action(
      self,
      data={
        'grouped_data': grouped_data,
        'company_id': self.company_id.id,
        'address_type': self.get_address_type_display(self.address_type),
        'company_name': company_name,
        'water_usage_date': self.water_usage_date,
        'report_date': date,
        'logo_data_uri': logo_data_uri,
        'user_balance_list_date': self.water_usage_date,
        'header_data': header_data
      }
    )

  def image_data_uri(self, logo):
    if logo:
      return f'data:image/png;base64,{logo.decode()}'
    return ''

  def get_company_name(self, company_id):
    company = self.env['res.company'].browse(company_id)
    return company.name if company else 'Unknown Company'

  def get_address_type_display(self, address_type):
    return dict(self._fields['address_type'].selection).get(address_type, '')
