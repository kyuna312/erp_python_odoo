from collections import defaultdict
from itertools import groupby
from odoo import models, fields, api
from odoo.exceptions import UserError


class CounterListInspectorReportWizard(models.TransientModel):
  _name = 'counter.list.inspector.report.wizard'
  _description = 'Counter List Inspector Report Wizard'

  company_id = fields.Many2one('res.company', string='ХҮТ', default=lambda self: self.env.user.company_id.id)
  inspector_ids = fields.Many2many('hr.employee', string='Байцаагч',
                                   domain=lambda self: [
                                     ('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)])
  address_type = fields.Selection([('OS', 'ОС'), ('AAN', 'ААН')], string='Address Type', required=True,
                                  default=lambda self: self.env.user.access_type)
  counter_list_report_date = fields.Selection(selection='_get_counter_list_report_date_selection',
                                              string='Хугацаа сонгох',
                                              required=True)
  counter_list_report_year = fields.Char(string='Counter List Report Year', compute='_compute_counter_list_report_year')
  date = fields.Date(string='Хугацаа сонгох', default=fields.Date.today)

  @api.depends('counter_list_report_date')
  def _compute_counter_list_report_year(self):
    for record in self:
      if record.counter_list_report_date:
        year, month = record.counter_list_report_date.split('/')
        record.counter_list_report_year = f"{year} Year {month}"

  @api.model
  def _get_counter_list_report_date_selection(self):
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

  def _get_counter_list_inspector_report(self, counter_list_report_date):
    if not counter_list_report_date:
      raise UserError("No Residual Date provided.")

    year, month = map(int, counter_list_report_date.split('/'))
    results = self._fetch_counter_list_report_data(self.address_type, self.company_id.id, year, month,
                                                   self.inspector_ids)
    sorted_data = sorted(results, key=lambda x: x['inspector_id'])
    grouped_data = defaultdict(lambda: {
      'inspector_id': None,
      'inspector_name': '',
      'address_id': None,
      'address_address': '',
      'family': 0,
      'counters': [],
      'total_price': 0
    })

    for (inspector_id, address_id), group in groupby(sorted_data, key=lambda x: (x['inspector_id'], x['address_id'])):
      for data in group:
        key = f"{inspector_id}_{address_id}"
        grouped_data[key]['inspector_id'] = data['inspector_id']
        grouped_data[key]['inspector_name'] = data['inspector_name']
        grouped_data[key]['address_id'] = data['address_id']
        grouped_data[key]['address_address'] = data['address_address']
        grouped_data[key]['family'] = data['family']
        grouped_data[key]['counters'].append({
          'counter_name': data['counter_name'],
          'first_counter': data['first_counter'],
          'last_counter': data['last_counter'],
          'difference': data['difference']
        })
        grouped_data[key]['total_price'] += data['difference']

    grouped_data = dict(grouped_data)
    return (
      grouped_data,
      self.address_type,
      self.get_company_name(self.company_id.id),
      self.date,
      self.image_data_uri(self.company_id.logo),
      self.get_header_data()
    )

  def _fetch_counter_list_report_data(self, address_type, company_id, year, month, inspector_ids=None):
    """Fetch the residual report values with optimized query."""
    inspector_filter = ""
    if inspector_ids:
      inspector_ids_str = ','.join(map(str, inspector_ids.ids))
      inspector_filter = f"AND (inspector.id = {inspector_ids_str})"

    query = f"""
            select
              inspector.id as inspector_id, inspector.name as inspector_name,
              address.id as address_id, concat(apartment.code, '-', address.id) as address_address,
              address.family as family, counter_line.counter_name as counter_name,
              counter_line.now_counter as first_counter, counter_line.last_counter as last_counter,
              counter_line.difference as difference
            FROM counter_counter_line_group counter_line_group
            INNER JOIN counter_counter_line counter_line ON counter_line.group_id = counter_line_group.id
            INNER JOIN ref_address address ON address.id = counter_line.address_id
            INNER JOIN ref_apartment apartment ON address.apartment_id = apartment.id
            inner join hr_employee inspector on inspector.id = address.inspector_id 
            WHERE counter_line_group.company_id = {company_id} AND counter_line_group.address_type = '{address_type}'
              AND counter_line_group.year::integer = {year} AND counter_line_group.month::integer = {month} {inspector_filter}
            ORDER by inspector.id, address.id, counter_line.counter_name
        """
    print('query', query)
    return self._execute_query(query)

  def get_header_data(self):
    return [
      {'counter_name': 'Ванн халуун ус', 'display_name': 'Ванн - Халуун ус'},
      {'counter_name': 'Ванн хүйтэн ус', 'display_name': 'Ванн - Хүйтэн ус'},
      {'counter_name': 'Гал тогоо хүйтэн ус', 'display_name': 'Гал тогоо - Хүйтэн ус'},
      {'counter_name': 'Гал тогоо халуун ус', 'display_name': 'Гал тогоо - Халуун ус'},
      {'counter_name': 'Халуун ус', 'display_name': 'Халуун ус'},
      {'counter_name': 'Хүйтэн ус', 'display_name': 'Хүйтэн ус'},
      {'counter_name': 'Халуун ус буцах', 'display_name': 'Халуун ус буцах'},
      {'counter_name': 'Авто угаалга', 'display_name': 'Авто угаалга'},
    ]

  def download(self):
    grouped_data, address_type, company_name, date, logo_data_uri, header_data = self._get_counter_list_inspector_report(
      self.counter_list_report_date)
    report_action = self.env.ref('ub_kontor.action_counter_list_inspector_report', raise_if_not_found=False)

    if not report_action:
      raise UserError('Action not found.')

    return report_action.report_action(
      self,
      data={
        'grouped_data': grouped_data,
        'company_id': self.company_id.id,
        'address_type': self.get_address_type_display(self.address_type),
        'company_name': company_name,
        'report_date': date,
        'logo_data_uri': logo_data_uri,
        'user_balance_list_date': self.counter_list_report_date,
        'header_data': header_data
      }
    )

  def image_data_uri(self, logo):
    return f'data:image/png;base64,{logo.decode()}' if logo else ''

  def get_company_name(self, company_id):
    company = self.env['res.company'].browse(company_id)
    return company.name if company else 'Unknown Company'

  def get_address_type_display(self, address_type):
    return dict(self._fields['address_type'].selection).get(address_type, '')
