from datetime import datetime
from itertools import groupby, chain
from odoo import models, fields, api
from odoo.exceptions import UserError
from collections import defaultdict
from dateutil.relativedelta import relativedelta


class PayResidualPDFReportWizard(models.TransientModel):
  _name = 'pay.residual.pdf.report.wizard'
  _description = 'Pay Residual PDF Report Wizard'

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
    period_id = self.env['pay.period'].sudo().search(
        [('company_id', '=', company_id), ('address_type', '=', address_type), ('year', '=', str(year)),
         ('month', '=', str(month).zfill(2))], limit=1)

    results = {
        'first_balance': [],
        'pay_receipt': [],
        'total_paid': [],
        'last_balance': [],
        'total_pay': [],
        'two_or_more_months': []
    }

    if period_id.state == 'opened' or not period_id:
        results['first_balance'] = self._get_first_balance_is_period_opened(company_id, address_type, first_day_of_month) or []
        results['pay_receipt'] = self._get_pay_receipts_is_period_opened(company_id, address_type, year, month) or []
        results['total_paid'] = self._get_total_paid_is_period_opened(company_id, address_type, first_day_of_month) or []
        results['last_balance'] = self._get_last_balance_is_period_opened(company_id, address_type, first_day_of_month) or []
        results['total_pay'] = self._get_total_pay_is_period_open(company_id, address_type, first_day_of_month) or []
        results['two_or_more_months'] = self._get_two_or_more_months_is_period_opened(company_id, address_type, first_day_of_month) or []
    elif period_id.state == 'closed':
        results['first_balance'] = self._get_first_balance_is_period_closed(company_id, address_type, year, month, period_id.id) or []
        results['pay_receipt'] = self._get_pay_receipts_is_period_closed(company_id, address_type, year, month, period_id.id) or []
        results['total_paid'] = self._get_total_paid_is_period_closed(company_id, address_type, year, month, period_id.id) or []
        results['last_balance'] = self._get_last_balance_is_period_closed(company_id, address_type, year, month, period_id.id) or []
        results['total_pay'] = self._get_total_pay_is_period_closed(company_id, first_day_of_month, address_type, period_id.id) or []
        results['two_or_more_months'] = self._get_two_or_more_months_is_period_closed(company_id, address_type, year, month) or []

    # Group results
    sorted_results = sorted(
        chain.from_iterable(results.values()),
        key=lambda x: x['inspector_id']
    )

    grouped_data = defaultdict(
        lambda: {'inspector_id': None, 'inspector_name': '', 'pay_receipt_count': 0, 'pay_receipt_amount': 0.0,
                 'pay_receipt_state_subsidy': 0.0, 'total_pay_user_count': 0, 'total_pay_amount': 0.0,
                 'total_paid_user_count': 0, 'total_paid_amount': 0.0, 'last_balance_user_count': 0,
                 'last_balance_amount': 0.0, 'two_months': 0, 'more_months': 0, 'first_balance_user_count': 0,
                 'first_balance': 0.0})

    for key, group in groupby(sorted_results, key=lambda x: x['inspector_id']):
        for item in group:
            grouped_data[key]['inspector_id'] = item['inspector_id']
            grouped_data[key]['inspector_name'] = item['inspector_name']
            for k, v in item.items():
                if k not in ['inspector_id', 'inspector_name']:
                    grouped_data[key][k] += v or 0.0

    grouped_data = dict(grouped_data)

    return (
        grouped_data,
        address_type,
        self.get_company_name(company_id),
        self.date,
        self.image_data_uri(self.company_id.logo)
    )

  def _get_first_balance_is_period_opened(self, company_id, address_type, first_day_of_month):
    query = f"""
      select address.inspector_id as inspector_id, inspector.name as inspector_name,
      COUNT(CASE WHEN ROUND(cast(first_balance.residual as numeric), 2) > 0.0 THEN first_balance.address_id END) AS first_balance_user_count,
      ROUND(cast(SUM(first_balance.residual) as numeric), 2) AS first_balance
      from ref_address address
      inner join hr_employee inspector on inspector.id = address.inspector_id
      left join (
            select first_balance.address_id as address_id, round(cast(sum(first_balance.residual) as numeric),2) as residual
            from (
                SELECT 
                    invoice.address_id as address_id,
                    round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual
                FROM 
                    pay_receipt_address_invoice invoice
                INNER JOIN 
                    ref_address address 
                    ON address.id = invoice.address_id and invoice.company_id = {company_id}
                    AND address.type = '{address_type}'
                    AND concat(invoice.year, '-', invoice.month, '-01')::date < '{first_day_of_month}'::date 
                LEFT JOIN 
                    pay_address_payment_line payment 
                    ON payment.invoice_id = invoice.id 
                    AND payment.period_id IN (
                        SELECT pp.id    
                        FROM pay_period pp 
                        WHERE pp.company_id = {company_id} 
                        AND pp.address_type = '{address_type}' 
                        AND concat(pp.year, '-', pp.month, '-01')::date < '{first_day_of_month}'::date 
                    )
                GROUP BY  invoice.id
            ) first_balance
            where first_balance.residual > 0.0
            group by first_balance.address_id
      ) first_balance on first_balance.address_id = address.id
      where address.company_id = {company_id} and address.type = '{address_type}'
      group by address.inspector_id, inspector.id
    """
    return self._execute_query(query) or []

  def _get_first_balance_is_period_closed(self, company_id, address_type, year, month, period_id):
    query = f"""
      select 
        report.inspector_id as inspector_id,
        inspector.name as inspector_name,
        count(CASE WHEN ROUND(cast(report.first_balance_amount as numeric),2) > 0.0 THEN report.address_id END) as first_balance_user_count,
        SUM(ROUND(cast(report.first_balance_amount as numeric),2)) AS first_balance
      from pay_period_report report
      inner join pay_period period on period.company_id={company_id} and period.address_type='{address_type}' and period.year::integer = {year} and period.month::integer = {month} and report.period_id = period.id
      inner join hr_employee inspector on inspector.id = report.inspector_id 
      where report.first_balance_amount !=0
      group by report.inspector_id, inspector.name 
    """
    return self._execute_query(query) or []

  def _get_pay_receipts_is_period_opened(self, company_id, address_type, year, month):
    query = f"""
      select address.inspector_id as inspector_id, inspector.name as inspector_name, count(address.id) as pay_receipt_count,  sum(pra.total_amount) as pay_receipt_amount, 0 as pay_receipt_state_subsidy
      from ref_address address
      inner join hr_employee inspector on inspector.id = address.inspector_id and address.company_id = {company_id} and address.type = '{address_type}'
      inner join pay_receipt_address pra on pra.address_id = address.id
      inner join pay_receipt pr on pr.company_id = {company_id} and pr.address_type = '{address_type}' and 
      pra.receipt_id = pr.id and pr.year::integer = {year} and pr.month::integer = {month}
      group by address.inspector_id, inspector.id
    """
    return self._execute_query(query) or []

  def _get_pay_receipts_is_period_closed(self, company_id, address_type, year, month, period_id):
    query = f"""
      select 
         report.inspector_id as inspector_id,
         inspector.name as inspector_name,
         count(report.address_id) as pay_receipt_count,
         SUM(ROUND(cast(report.receipt_amount as numeric),2)) AS pay_receipt_amount,
         0 as pay_receipt_state_subsidy
      from pay_period_report report
      inner join pay_period period on period.company_id={company_id} and period.address_type='{address_type}' and period.year::integer = {year} and period.month::integer = {month}
      inner join hr_employee inspector on inspector.id = report.inspector_id 
      where report.receipt_amount != 0 and report.period_id = {period_id}
      group by report.inspector_id , inspector.name
    """
    return self._execute_query(query) or []

  def _get_total_pay_is_period_open(self, company_id, address_type, first_day_of_month):

    query = f"""
      select address.inspector_id as inspector_id, inspector.name as inspector_name,
      count(CASE WHEN round(cast(total_pay.residual as numeric),2) > 0.0 THEN total_pay.address_id END) AS total_pay_user_count,
      sum(total_pay.residual) as total_pay_amount
      from ref_address address
      inner join hr_employee inspector on inspector.id = address.inspector_id
      left join (
        select total_pay.address_id as address_id, round(cast(sum(total_pay.residual) as numeric),2) as residual
        from (
            SELECT 
                invoice.address_id as address_id,
                round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual
            FROM 
                pay_receipt_address_invoice invoice
            INNER JOIN 
                ref_address address 
                ON address.id = invoice.address_id and invoice.company_id = {company_id}
                AND address.type = '{address_type}'
                AND concat(invoice.year, '-', invoice.month, '-01')::date <= '{first_day_of_month}'::date 
            LEFT JOIN 
                pay_address_payment_line payment 
                ON payment.invoice_id = invoice.id 
                AND payment.period_id IN (
                    SELECT pp.id 
                    FROM pay_period pp 
                    WHERE pp.company_id = {company_id} 
                    AND pp.address_type = '{address_type}' 
                    AND concat(pp.year, '-', pp.month, '-01')::date < '{first_day_of_month}'::date 
                )
            GROUP BY  invoice.id
        ) total_pay
        where total_pay.residual > 0.0
        group by total_pay.address_id
      ) total_pay on total_pay.address_id = address.id
      where address.company_id = {company_id} and address.type = '{address_type}'
      group by address.inspector_id, inspector.id
    """
    return self._execute_query(query) or []

  def _get_total_pay_is_period_closed(self, company_id, first_day_of_month, address_type, period_id):
    query = f"""
      SELECT
          inspector.id AS inspector_id,
          inspector.name AS inspector_name,
          COUNT(CASE WHEN round(cast(total_pay.invoiced_amount as numeric),2) > round(cast(total_pay.paid_amount as numeric),2) THEN total_pay.address_id END) AS total_pay_user_count,
          SUM(total_pay.invoiced_amount) - SUM(total_pay.paid_amount) AS total_pay_amount
      FROM pay_period_report report
      inner join hr_employee inspector on inspector.id = report.inspector_id
      LEFT JOIN (
          SELECT invoice.address_id AS address_id, SUM(invoice.amount_total) AS invoiced_amount, COALESCE(paid.amount, 0.0) AS paid_amount
          FROM pay_receipt_address_invoice invoice
          LEFT JOIN (
            SELECT invoice.address_id AS address_id, SUM(payment_line.amount) AS amount
            FROM pay_address_payment_line payment_line
            INNER JOIN pay_receipt_address_invoice invoice ON invoice.id = payment_line.invoice_id AND invoice.company_id = {company_id}
            WHERE invoice.company_id = {company_id} and payment_line.period_id in (select pp.id as id from pay_period pp where concat(pp.year, '-', pp.month, '-01')::date < '{first_day_of_month}'::date and pp.company_id = {company_id} and pp.address_type='{address_type}' )
            GROUP BY invoice.address_id
          ) paid ON invoice.company_id = {company_id} AND paid.address_id = invoice.address_id
          INNER JOIN ref_address address ON address.id = invoice.address_id AND address.type = '{address_type}'
          WHERE invoice.company_id = {company_id} AND CONCAT(invoice.year, '-', invoice.month, '-01')::date <= '{first_day_of_month}'::date
          GROUP BY invoice.address_id, paid.amount
      ) total_pay ON total_pay.address_id = report.address_id
      WHERE report.period_id = {period_id}
      GROUP BY inspector.id;
    """
    query = f"""
        select inspector.id as inspector_id, inspector.name as inspector_name, COUNT(CASE WHEN round(cast(report.first_balance_amount as numeric),2) + round(cast(report.receipt_amount as numeric),2) > 0.0 THEN report.address_id END) as total_pay_user_count,
        sum(round(cast(report.first_balance_amount as numeric),2)) + sum(round(cast(report.receipt_amount as numeric),2)) as total_pay_amount
        from pay_period period
        inner join pay_period_report report on report.period_id = period.id and period.id = {period_id}
        inner join hr_employee inspector on inspector.id = report.inspector_id 
        group by inspector.id 
    """
    return self._execute_query(query) or []

  def _get_total_paid_is_period_opened(self, company_id, address_type, first_day_of_month):
    query = f"""
      select address.inspector_id as inspector_id, inspector.name as inspector_name,
      count(total_paid.address_id) total_paid_user_count,
      round(cast(sum(total_paid.paid_amount) as numeric), 2) as total_paid_amount
      from ref_address address
      inner join hr_employee inspector on inspector.id = address.inspector_id
      left join (
          select invoice.address_id as address_id , round(cast(sum(payment_line.amount) as numeric),2) as paid_amount
          from pay_receipt_address_invoice invoice
          inner join pay_address_payment_line payment_line on payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year, '-', pp.month, '-01')::date = '{first_day_of_month}'::date and pp.company_id = {company_id} and pp.address_type = '{address_type}')
          inner join ref_address address on address.id = invoice.address_id and address.type = '{address_type}'
          where invoice.company_id = {company_id} and concat(invoice.year, '-', invoice.month, '-', '01')::date <= '{first_day_of_month}'::date
          group by invoice.address_id
      ) total_paid on total_paid.address_id = address.id
      where address.company_id = {company_id} and address.type = '{address_type}'
      group by address.inspector_id, inspector.id
    """
    return self._execute_query(query) or []

  def _get_total_paid_is_period_closed(self, company_id, address_type, year, month, period_id):
    query = f"""
      select 
         report.inspector_id as inspector_id,
         inspector.name as inspector_name,
         count(CASE WHEN ROUND(cast(report.total_paid_amount as numeric),2) > 0.0 THEN report.address_id END) as total_paid_user_count,
         SUM(ROUND(cast(report.total_paid_amount as numeric),2)) AS total_paid_amount
      from pay_period_report report
      inner join pay_period period on period.company_id={company_id} and period.address_type='{address_type}' and period.year::integer = {year} and period.month::integer = {month}
      inner join hr_employee inspector on inspector.id = report.inspector_id 
      where report.total_paid_amount != 0 and report.period_id = {period_id}
      group by report.inspector_id , inspector.name 
    """
    return self._execute_query(query) or []

  def _get_last_balance_is_period_opened(self, company_id, address_type, first_day_of_month):
    query = f"""
      select address.inspector_id as inspector_id, inspector.name as inspector_name,
      count(CASE WHEN round(cast(last_balance.residual as numeric),2) > 0.0 THEN last_balance.address_id END) AS last_balance_user_count,
      sum(last_balance.residual) as last_balance_amount
      from ref_address address
      inner join hr_employee inspector on inspector.id = address.inspector_id
      left join (
            select last_balance.address_id as address_id, round(cast(sum(last_balance.residual) as numeric),2) as residual
            from (
                SELECT 
                    invoice.address_id as address_id,
                    round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual
                FROM 
                    pay_receipt_address_invoice invoice
                INNER JOIN 
                    ref_address address 
                    ON address.id = invoice.address_id and invoice.company_id = {company_id}
                    AND address.type = '{address_type}'
                    AND concat(invoice.year, '-', invoice.month, '-01')::date <= '{first_day_of_month}'::date 
                LEFT JOIN 
                    pay_address_payment_line payment 
                    ON payment.invoice_id = invoice.id 
                    AND payment.period_id IN (
                        SELECT pp.id 
                        FROM pay_period pp 
                        WHERE pp.company_id = {company_id} 
                        AND pp.address_type = '{address_type}' 
                        AND concat(pp.year, '-', pp.month, '-01')::date <= '{first_day_of_month}'::date 
                    )
                GROUP BY  invoice.id
            ) last_balance
            where last_balance.residual > 0.0
            group by last_balance.address_id
      ) last_balance on last_balance.address_id = address.id
      where address.company_id = {company_id} and address.type = '{address_type}'
      group by address.inspector_id, inspector.id
    """
    print('query', query)
    return self._execute_query(query) or []

  def _get_last_balance_is_period_closed(self, company_id, address_type, year, month, period_id):
    query = f"""
      select 
         report.inspector_id as inspector_id,
         inspector.name as inspector_name,
         count(CASE WHEN ROUND(cast(report.last_balance_amount as numeric),2) > 0.0 THEN report.address_id END) as last_balance_user_count,
         SUM(ROUND(cast(report.last_balance_amount as numeric),2)) AS last_balance_amount
      from pay_period_report report
      inner join pay_period period on period.company_id={company_id} and period.address_type='{address_type}' and period.year::integer = {year} and period.month::integer = {month}
      inner join hr_employee inspector on inspector.id = report.inspector_id
      where report.last_balance_amount != 0 and report.period_id = {period_id}
      group by report.inspector_id , inspector."name" 
    """
    return self._execute_query(query) or []

  def _get_two_or_more_months_is_period_opened(self, company_id, address_type, first_day_of_month):
    query = f"""
      select tmp.inspector_id, tmp.inspector_name, count(case when tmp.invoice_count = 2 then tmp.address_id end) as two_months,  
         count(case when tmp.invoice_count > 2 then tmp.address_id end) as more_months from (
          select tmp.inspector_id as inspector_id, inspector.name as inspector_name,tmp.address_id as address_id, count(tmp.invoice_id) invoice_count from (
            SELECT 
              invoice.id as invoice_id,
              invoice.address_id as address_id,
              address.inspector_id as inspector_id,
              round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual,
              concat(invoice.year, '-', invoice.month) as invoice_name
            FROM pay_receipt_address_invoice invoice
            INNER JOIN 
                ref_address address 
                ON address.id = invoice.address_id and invoice.company_id = {company_id}
                AND address.type = '{address_type}'
                AND concat(invoice.year, '-', invoice.month, '-01')::date <= '{first_day_of_month}'::date 
            LEFT JOIN 
                pay_address_payment_line payment 
                ON payment.invoice_id = invoice.id 
                AND payment.period_id IN (
                    SELECT pp.id FROM pay_period pp 
                    WHERE pp.company_id = {company_id} AND pp.address_type = '{address_type}' AND concat(pp.year, '-', pp.month, '-01')::date <= '{first_day_of_month}'::date 
                )
            GROUP BY  invoice.id, address.id
            having round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) > 0.0
          ) tmp 
          inner join hr_employee inspector on inspector.id = tmp.inspector_id
          group by tmp.address_id, tmp.inspector_id, inspector.id
        ) tmp
      group by tmp.inspector_id, tmp.inspector_name;
    """
    return self._execute_query(query) or []

  def _get_two_or_more_months_is_period_closed(self, company_id, address_type, year, month):
    query = f"""
      SELECT inspector.id AS inspector_id, inspector.name AS inspector_name, tmp.two_months as two_months, tmp.more_months as more_months
      FROM (
          SELECT report.inspector_id AS inspector_id, COUNT(CASE WHEN array_length(string_to_array(report.unpaid_invoices, ','), 1) = 2 THEN 1 END) AS two_months, COUNT(CASE WHEN array_length(string_to_array(report.unpaid_invoices, ','), 1) >= 3 THEN 1 END) AS more_months
          FROM pay_period_report report
          WHERE report.period_id IN (SELECT pp.id FROM pay_period pp WHERE pp.company_id = {company_id} AND pp.address_type = '{address_type}' AND pp.year::integer = {year} AND pp.month::integer = {month})
          GROUP BY report.inspector_id
      ) tmp
      LEFT JOIN hr_employee inspector ON tmp.inspector_id = inspector.id
      group by inspector.id, inspector.name, tmp.two_months, tmp.more_months
    """
    return self._execute_query(query) or []

  def download_pdf(self):
    """Download the PDF report."""
    if not self.residual_date:
      raise UserError('No residual date selected.')

    grouped_data, address_type, company_name, date, logo_data_uri = self._get_residual_report_values(self.residual_date)

    report_action = self.env.ref('ub_kontor.action_pay_residual_pdf_report', raise_if_not_found=False)
    if not report_action:
      raise UserError('The report action "ub_kontor.action_pay_residual_pdf_report" is not defined.')

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
