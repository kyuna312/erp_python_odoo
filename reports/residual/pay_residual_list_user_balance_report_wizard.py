from collections import defaultdict
from itertools import groupby, chain

from odoo import models, fields, api
from odoo.exceptions import UserError


class PayResidualListUserBalanceReportWizard(models.TransientModel):
  _name = 'pay.residual.list.user.balance.report.wizard'
  _description = 'Pay Residual List User Balance Report Wizard'

  company_id = fields.Many2one(
    'res.company', string='ХҮТ', default=lambda self: self.env.user.company_id.id
  )

  inspector_ids = fields.Many2many(
    'hr.employee', string='Байцаагч',
    domain=lambda self: [('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)]
  )

  address_type = fields.Selection(
    [('OS', 'ОС'), ('AAN', 'ААН')], string='Address Type', required=True,
    default=lambda self: self.env.user.access_type
  )

  user_balance_list_date = fields.Selection(
    selection='_get_residual_date_selection', string='Хугацаа сонгох', required=True
  )

  user_balance_list_year = fields.Char(
    string='Residual Year', compute='_compute_residual_year'
  )

  date = fields.Date(
    string='Хугацаа сонгох', default=fields.Date.today
  )

  @api.depends('user_balance_list_date')
  def _compute_residual_year(self):
    """Compute the residual year for display."""
    for record in self:
      date = record.user_balance_list_date
      record.user_balance_list_year = f"{date.split('/')[0]} Year {date.split('/')[1]}" if date else ''

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

  def _execute_query(self, query, params=None):
    """Execute a SQL query with optional parameters."""
    self.env.cr.execute(query, params or ())
    return self.env.cr.dictfetchall()

  def _get_residual_list_user_report(self, user_balance_list_date):
    if not user_balance_list_date:
      raise UserError('No Residual Date provided.')

    year, month = map(int, user_balance_list_date.split('/'))
    first_day_of_month = f"{year}-{str(month).zfill(2)}-01"

    company_id = self.company_id.id
    address_type = self.env.user.access_type
    period_id = self.env['pay.period'].sudo().search(
      [('company_id', '=', company_id), ('address_type', '=', address_type), ('year', '=', str(year)),
       ('month', '=', str(month).zfill(2))], limit=1)

    # if period_id.state == 'opened':
    #   data = chain(self._fetch_residual_data_is_period_opened(self.address_type, self.company_id.id, first_day_of_month, self.inspector_ids))
    # else:
    #   data = chain(self._fetch_residual_data_is_period_closed(self.address_type, self.company_id.id, year, month, self.inspector_ids))
    data = chain(self._fetch_residual_data_is_period_opened(self.address_type, self.company_id.id, first_day_of_month,
                                                            self.inspector_ids))

    sorted_results = sorted(data, key=lambda x: x['inspector_id'])

    grouped_data = defaultdict(list)
    for key, group in groupby(sorted_results, key=lambda x: x['inspector_id']):
      grouped_data[key].extend(group)

    return (
      grouped_data,
      self.address_type,
      self.get_company_name(self.company_id.id),
      self.date,
      self.image_data_uri(self.company_id.logo)
    )

  def _fetch_residual_data_is_period_opened(self, address_type, company_id, first_day_of_month, inspector_ids=None):
    """Fetch the residual report values with optimized query."""
    inspector_filter = ""
    if inspector_ids:
      inspector_ids_str = ','.join(map(str, inspector_ids.ids))
      inspector_filter = f"AND (inspector.id = {inspector_ids_str})"

    query = f"""
        select 
            inspector.id AS inspector_id,
            inspector.name AS inspector_name,
            apartment.code AS apartment_name,
            address.address AS address_name,
            count(not_paid_invoice.invoice_id) as invoice_count 
        from (
          select 
              address.id as address_id,
              invoice.id as invoice_id ,
              round(cast(invoice.amount_total as numeric)), 
              round(cast(sum(coalesce(paid.amount,0.0)) as numeric),2) 
          from pay_receipt_address_invoice invoice
          inner join ref_address address on address.id = invoice.address_id and address.type = '{address_type}' and address.company_id = {company_id}
          left join pay_address_payment_line paid on invoice.company_id = {company_id} and paid.invoice_id = invoice.id and paid.period_id in (
              SELECT pp.id as id FROM pay_period AS pp 
              WHERE TO_DATE(CONCAT(pp.year, '-', LPAD(pp.month::text, 2, '0'), '-01'), 'YYYY-MM-DD') <= '{first_day_of_month}'
                AND pp.company_id = {company_id}
                AND pp.address_type = '{address_type}'
          )
          where 
              CONCAT(invoice.year, '-', LPAD(invoice.month::text, 2, '0'), '-01')::date <= '{first_day_of_month}'
          group by address.id, invoice.id
          having round(cast(invoice.amount_total as numeric),2) >  round(cast(sum(coalesce(paid.amount,0.0)) as numeric),2)
        ) not_paid_invoice
        inner join ref_address address on address.id = not_paid_invoice.address_id and address.company_id={company_id} and address.type = '{address_type}'
        inner join hr_employee inspector on inspector.id = address.inspector_id
        inner join ref_apartment AS apartment ON apartment.id = address.apartment_id
        {inspector_filter}
        group by address.id, inspector.id, apartment.id 
        order by inspector.id desc, apartment.code asc, address.float_address asc
    """
    return self._execute_query(query)

  def _fetch_residual_data_is_period_closed(self, address_type, company_id, year, month, inspector_ids=None):
    """Fetch the residual report values with optimized query."""
    inspector_filter = ""
    if inspector_ids:
      inspector_ids_str = ','.join(map(str, inspector_ids.ids))
      inspector_filter = f"AND (inspector.id = {inspector_ids_str})"

    query = f"""
      SELECT 
          address.inspector_id AS inspector_id,
          inspector.name AS inspector_name,
          apartment.code AS apartment_name,
          address.address AS address_name,
          SUM(
              CASE 
                  WHEN report.unpaid_invoices IS NOT NULL 
                  THEN array_length(string_to_array(report.unpaid_invoices, ','), 1)
                  ELSE 0
              END
          ) AS invoice_count,
          report.unpaid_invoices as unpaid_invoices
      FROM ref_address address
      INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id
      INNER JOIN pay_period period ON period.address_type = '{address_type}' AND period.company_id = {company_id} AND period."year"::integer = '{year}' AND LPAD(period."month"::TEXT, 2, '0') = LPAD('{month}'::TEXT, 2, '0')
      INNER JOIN pay_period_report report ON report.address_id = address.id AND report.period_id = period.id AND report.unpaid_invoices IS NOT NULL
      INNER JOIN ref_apartment apartment ON apartment.id = address.apartment_id
      {inspector_filter}
      GROUP BY address.inspector_id, inspector.name, apartment.code, address.address, report.unpaid_invoices 
      ORDER BY address.inspector_id, inspector.name, apartment.code asc, address.float_address asc, report.unpaid_invoices;
    """
    return self._execute_query(query)

  def download(self):
    grouped_data, address_type, company_name, date, logo_data_uri = self._get_residual_list_user_report(
      self.user_balance_list_date
    )
    report_action = self.env.ref('ub_kontor.action_pay_residual_list_user_balance_report', raise_if_not_found=False)

    if not report_action:
      raise UserError('Action not found.')

    return report_action.report_action(
      self,
      data={
        'grouped_data': grouped_data,
        'company_id': self.company_id.id,
        'address_type': self.get_address_type_display(self.address_type),
        'company_name': company_name,
        'user_balance_list_date': self.user_balance_list_date,
        'report_date': date,
        'logo_data_uri': logo_data_uri,
        'user_balance_list_date': self.user_balance_list_date
      }
    )

  def image_data_uri(self, logo):
    """Convert the company logo to a data URI."""
    if logo:
      return f'data:image/png;base64,{logo.decode()}'
    return ''

  def get_company_name(self, company_id):
    """Retrieve the name of the company based on ID."""
    company = self.env['res.company'].browse(company_id)
    return company.name if company else 'Unknown Company'

  def get_address_type_display(self, address_type):
    """Return the display value for the address type."""
    return dict(self._fields['address_type'].selection).get(address_type, '')
