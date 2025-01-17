from collections import defaultdict
from itertools import groupby, chain
from datetime import datetime

from odoo import models, fields, api
from odoo.exceptions import UserError


class PayThreeMonthUserResidualListPdfReportWizard(models.TransientModel):
  _name = 'pay.three.month.user.residual.list.pdf.report.wizard'
  _description = 'Pay Three Month User Residual List PDF Report Wizard'

  pay_receipt_id = fields.Many2one('pay.receipt', string='Payment Receipt', required=True,
                                   default=lambda self: self._get_default_pay_receipt())
  company_id = fields.Many2one('res.company', 'ХҮТ', index=True, default=lambda self: self.env.user.company_id.id)
  address_type = fields.Selection(
    [('OS', 'ОС'), ('AAN', 'ААН')],
    string='Тоотын төрөл',
    required=True,
    default=lambda self: self.env.user.access_type
  )
  residual_date = fields.Selection(selection='_get_residual_date_selection', string='Хугацаа сонгох', required=True)
  residual_year = fields.Char(string='Residual Year', compute='_compute_residual_year')
  date = fields.Date(string='Date', default=fields.Date.today)

  def _get_default_pay_receipt(self):
    """Fetch the default pay receipt record."""
    receipt_id = self.env.context.get('active_id')
    if not receipt_id:
      receipt = self.env['pay.receipt'].search([], limit=1)
      if not receipt:
        raise UserError('No Payment Receipt found. Please create a Payment Receipt first.')
      return receipt.id
    return receipt_id

  @api.depends('residual_date')
  def _compute_residual_year(self):
    """Compute the residual year and format it for display."""
    for record in self:
      record.residual_year = (
        f"{record.residual_date.split('/')[0]} Year {record.residual_date.split('/')[1]}"
        if record.residual_date else ''
      )

  @api.model
  def _get_residual_date_selection(self):
    """Fetch and return the list of unique residual dates."""
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
    """Execute a given SQL query and return the results."""
    self.env.cr.execute(query)
    return self.env.cr.dictfetchall() or []

  def _get_residual_report_values(self, residual_date):
    """Fetch residual report values for the selected date."""
    if not residual_date:
      raise UserError('No residual date provided.')

    year, month = map(int, residual_date.split('/'))
    company_id = self.env.company.id
    address_type = self.env.user.access_type
    first_day_of_month = datetime(year, month, 1).strftime('%Y-%m-%d')

    results = self._get_three_month_user_residual_data(company_id, address_type, first_day_of_month)

    # Sort results by inspector_id, inspector_name, address_id, address_address, and apartment_code
    results.sort(key=lambda x: (
      x['inspector_id'], x['inspector_name'], x['address_id'], x['address_address'], x['apartment_code']))

    grouped_datas = defaultdict(lambda: {
      'address_ids': [],
      'address_addresses': [],
      'inspector_name': '',
      'apartment_codes': [],
      'address_names': [],
      'residual': [],
      'invoice_names': defaultdict(set),
      'unique_combinations': set()
    })

    for data in results:
      inspector_key = (data['inspector_id'], data['inspector_name'])
      grouped_datas[inspector_key]['inspector_name'] = data['inspector_name']
      grouped_datas[inspector_key]['address_ids'].append(data['address_id'])
      grouped_datas[inspector_key]['address_addresses'].append(data['address_address'])
      grouped_datas[inspector_key]['apartment_codes'].append(data['apartment_code'])
      grouped_datas[inspector_key]['address_names'].append(data['address_name'])

      combination_key = (data['address_id'], data['address_address'], data['apartment_code'])

      if combination_key not in grouped_datas[inspector_key]['unique_combinations']:
        grouped_datas[inspector_key]['residual'].append(data['residual'])
        grouped_datas[inspector_key]['unique_combinations'].add(combination_key)

      grouped_datas[inspector_key]['invoice_names'][(data['apartment_code'], data['address_address'])].update(
        data['invoice_names'].split(', '))

    for inspector_key, details in grouped_datas.items():
      details['invoice_names'] = {str(key): ', '.join(value) for key, value in details['invoice_names'].items()}
      del details['unique_combinations']

    # Sort grouped_datas by inspector_key
    grouped_data_str_keys = {str(key): value for key, value in sorted(grouped_datas.items())}

    print('grouped_data_str_keys:', grouped_data_str_keys)

    return (
      grouped_data_str_keys,
      address_type,
      self.get_company_name(company_id),
      self.date,
      self.image_data_uri(self.company_id.logo)
    )

  def _get_three_month_user_residual_data(self, company_id, address_type, first_day_of_month):
    query = f"""
          SELECT 
              inspector.id AS inspector_id, 
              inspector.name AS inspector_name, 
              apartment.code AS apartment_code,
              address.address AS address_address, 
              address.name as address_name,
              last_balance.address_id AS address_id, 
              ROUND(CAST(SUM(last_balance.residual) AS numeric), 2) AS residual, 
              STRING_AGG(last_balance.invoice_name, ', ') AS invoice_names
          FROM (
              SELECT 
                  invoice.address_id AS address_id,
                  invoice.id AS invoice_id,
                  ROUND(CAST(invoice.amount_total AS numeric), 2) - ROUND(CAST(COALESCE(SUM(payment.amount), 0) AS numeric), 2) AS residual,
                  CONCAT(invoice.year, '-', invoice.month) AS invoice_name
              FROM pay_receipt_address_invoice invoice
              INNER JOIN ref_address address ON address.id = invoice.address_id 
                  AND invoice.company_id = {company_id}
                  AND address.type = '{address_type}'
                  AND CONCAT(invoice.year, '-', invoice.month, '-01')::date <= '{first_day_of_month}'::date 
              LEFT JOIN pay_address_payment_line payment ON payment.invoice_id = invoice.id 
                  AND payment.period_id IN (
                      SELECT pp.id FROM pay_period pp 
                      WHERE pp.company_id = {company_id} 
                      AND pp.address_type = '{address_type}' 
                      AND CONCAT(pp.year, '-', pp.month, '-01')::date <= '{first_day_of_month}'::date 
                  )
              GROUP BY invoice.address_id, invoice.id
          ) last_balance
          INNER JOIN ref_address address ON address.id = last_balance.address_id
          INNER JOIN ref_apartment apartment ON apartment.id = address.apartment_id 
          INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id 
          WHERE last_balance.residual > 0.0
          GROUP BY last_balance.address_id, inspector.id, address.id, apartment.id
          HAVING COUNT(last_balance.invoice_id) >= 3
          ORDER BY inspector.id DESC, apartment.id DESC, address.float_address ASC
      """

    print('query:', query)

    return self._execute_query(query)

  def download_pdf(self):
    """Download the PDF report."""
    if not self.residual_date:
      raise UserError('No residual date selected.')

    grouped_data, address_type, company_name, date, logo_data_uri = self._get_residual_report_values(self.residual_date)

    report_action = self.env.ref('ub_kontor.action_pay_three_month_user_list_residual_pdf_report',
                                 raise_if_not_found=False)
    if not report_action:
      raise UserError(
        'The report action "ub_kontor.action_pay_three_month_user_list_residual_pdf_report" is not defined.')

    return report_action.report_action(self, data={
      'residual_date': self.residual_date,
      'company_id': self.company_id.id,
      'address_type': self.get_address_type_display(self.address_type),
      'company_name': company_name,
      'logo_data_uri': logo_data_uri,
      'date': date,
      'grouped_data': grouped_data
    })

  def get_company_name(self, company_id):
    """Fetch the name of the company by its ID."""
    company = self.env['res.company'].browse(company_id)
    return company.name if company else 'Unknown Company'

  def get_address_type_display(self, address_type):
    """Return the display value for the address type."""
    field = self.env['pay.receipt.pdf.report.wizard']._fields['address_type']
    return dict(field.selection).get(address_type, '')

  def image_data_uri(self, logo):
    """Convert the company logo to a data URI."""
    if logo:
      return f'data:image/png;base64,{logo.decode()}'
    return ''
