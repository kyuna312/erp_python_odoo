from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
from dateutil.relativedelta import relativedelta
from itertools import groupby, chain
from collections import defaultdict


class PayUserResidualPDFReportWizard(models.TransientModel):
  _name = 'pay.user.residual.pdf.report.wizard'
  _description = 'Pay User Residual PDF Report Wizard'

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

    current_date_str = residual_date.replace('/',
                                             '-') + '-01'  # Replace '/' with '-' and append day to match '%Y-%m-%d' format
    current_date = datetime.strptime(current_date_str, '%Y-%m-%d')
    next_date = current_date + relativedelta(months=1)

    next_month = next_date.month
    next_year = next_date.year

    company_id = self.env.company.id
    address_type = self.env.user.access_type
    first_day_of_month = datetime(current_date.year, current_date.month, 1).strftime('%Y-%m-%d')
    last_day_of_month = (
        datetime(current_date.year, current_date.month, 1) + relativedelta(months=1, days=-1)).strftime('%Y-%m-%d')

    # last_day_of_next_month = (next_date + relativedelta(months=1, day=1) - relativedelta(days=1)).strftime('%Y-%m-%d')
    # print('last_day_of_next_month', last_day_of_next_month)

    period_id = self.env['pay.period'].sudo().search(
      [('company_id', '=', company_id), ('address_type', '=', address_type), ('year', '=', str(current_date.year)),
       ('month', '=', str(current_date.month).zfill(2))], limit=1)

    results = {
      'first_balance_results': [],
      'pay_receipt_results': [],
      'total_pay_results': [],
      'advance_payments_results': [],
      'c1_payments_results': [],
      'tz_payments_results': [],
      'total_paid_results': [],
      'last_balance_results': [],
      'uoo_residual_paid_results': [],
      'current_month_uoo_paid_results': [],
      'two_or_more_months_results': []
    }

    if not period_id or period_id.state == 'opened':
      results['first_balance_results'] = self._get_first_balance_is_period_opened(company_id, address_type,
                                                                                  first_day_of_month) or []
      results['pay_receipt_results'] = self._get_pay_receipts_is_period_opened(company_id, address_type,
                                                                               current_date.year,
                                                                               current_date.month) or []
      results['total_pay_results'] = self._get_total_pay_is_period_opened(company_id, address_type,
                                                                          first_day_of_month) or []
      results['advance_payments_results'] = self._get_advance_payments_is_period_opened(company_id, address_type,
                                                                                        last_day_of_month,
                                                                                        current_date.year,
                                                                                        current_date.month) or []
      results['c1_payments_results'] = self._get_c1_payments_is_period_opened(company_id, address_type,
                                                                              first_day_of_month, current_date.year,
                                                                              current_date.month) or []
      results['tz_payments_results'] = self._get_tz_payments_is_period_opened(company_id, address_type,
                                                                              current_date.year,
                                                                              current_date.month) or []
      results['total_paid_results'] = self._get_total_paid_is_period_opened(company_id, address_type, current_date.year,
                                                                            current_date.month) or []
      results['last_balance_results'] = self._get_last_balance_is_period_opened(company_id, address_type,
                                                                                first_day_of_month) or []
      results['uoo_residual_paid_results'] = self._get_uoo_residual_paid_is_period_opened(company_id, address_type,
                                                                                          first_day_of_month,
                                                                                          last_day_of_month) or []
      results['current_month_uoo_paid_results'] = self._get_current_month_uoo_paid_is_period_opened(company_id,
                                                                                                    address_type,
                                                                                                    first_day_of_month,
                                                                                                    next_month,
                                                                                                    next_year) or []
      results['two_or_more_months_results'] = self._get_two_or_more_months_is_period_opened(company_id, address_type,
                                                                                            first_day_of_month) or []
    elif not period_id or period_id.state == 'closed':
      results['first_balance_results'] = self._get_first_balance_is_period_closed(company_id, address_type,
                                                                                  current_date.year, current_date.month,
                                                                                  period_id.id) or []
      results['pay_receipt_results'] = self._get_pay_receipts_is_period_closed(company_id, address_type,
                                                                               current_date.year, current_date.month,
                                                                               period_id.id) or []
      results['total_pay_results'] = self._get_total_pay_is_period_closed(company_id, first_day_of_month, address_type,
                                                                          period_id.id) or []
      results['advance_payments_results'] = self._get_advance_payments_is_period_closed(company_id, address_type,
                                                                                        last_day_of_month,
                                                                                        current_date.year,
                                                                                        current_date.month,
                                                                                        period_id.id) or []
      results['c1_payments_results'] = self._get_c1_payments_is_period_closed(company_id, address_type,
                                                                              first_day_of_month, current_date.year,
                                                                              current_date.month, period_id.id) or []
      results['tz_payments_results'] = self._get_tz_payments_is_period_closed(company_id, address_type,
                                                                              current_date.year, current_date.month,
                                                                              period_id.id) or []
      results['total_paid_results'] = self._get_total_paid_is_period_closed(company_id, address_type, current_date.year,
                                                                            current_date.month,
                                                                            period_id.id) or []
      results['last_balance_results'] = self._get_last_balance_is_period_closed(company_id, address_type,
                                                                                current_date.year, current_date.month,
                                                                                period_id.id) or []
      results['uoo_residual_paid_results'] = self._get_uoo_residual_paid_is_period_closed(company_id, address_type,
                                                                                          period_id.id,
                                                                                          first_day_of_month,
                                                                                          last_day_of_month) or []
      results['current_month_uoo_paid_results'] = self._get_current_month_uoo_paid_is_period_closed(company_id,
                                                                                                    address_type,
                                                                                                    period_id.id,
                                                                                                    next_month,
                                                                                                    next_year,
                                                                                                    first_day_of_month) or []
      results['two_or_more_months_results'] = self._get_two_or_more_months_is_period_closed(company_id, address_type,
                                                                                            current_date.year,
                                                                                            current_date.month) or []

    # Group results
    sorted_results = sorted(
      chain.from_iterable(results.values()),
      key=lambda x: x['inspector_id']
    )

    # Group the sorted results using defaultdict
    grouped_data = defaultdict(
      lambda: {
        'inspector_id': None, 'inspector_name': '', 'first_balance_user_count': 0, 'first_balance_amount': 0,
        'pay_receipt_count': 0, 'pay_receipt_amount': 0.0, 'pay_receipt_state_subsidy': 0.0, 'total_pay_user_count': 0,
        'total_pay_amount': 0.0, 'advanced_paid_user_count': 0, 'advanced_paid_amount': 0.0,
        'c1_user_count': 0, 'c1_amount': 0.0, 'tz_user_count': 0, 'tz_amount': 0.0,
        'total_paid_user_count': 0, 'total_paid_amount': 0.0, 'last_balance_user_count': 0, 'last_balance_amount': 0.0,
        'uoo_paid_user_count': 0, 'uoo_paid_amount': 0.0, 'current_user_count': 0, 'current_amount': 0.0,
        'two_months': 0.0, 'more_months': 0.0
      }
    )

    for key, group in groupby(sorted_results, key=lambda x: x['inspector_id']):
      for item in group:
        grouped_data[key]['inspector_id'] = item['inspector_id']
        grouped_data[key]['inspector_name'] = item['inspector_name']
        for k, v in item.items():
          if k not in ['inspector_id', 'inspector_name']:
            grouped_data[key][k] += v or 0.0

    grouped_data = dict(grouped_data)
    print('grouped_data', grouped_data)

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
      ROUND(cast(SUM(first_balance.residual) as numeric), 2) AS first_balance_amount
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
        SUM(ROUND(cast(report.first_balance_amount as numeric),2)) AS first_balance_amount
      from pay_period_report report
      inner join pay_period period on period.company_id={company_id} and period.address_type='{address_type}' and period.year::integer = {year} and period.month::integer = {month} and report.period_id = period.id
      inner join hr_employee inspector on inspector.id = report.inspector_id 
      where report.first_balance_amount !=0
      group by report.inspector_id, inspector.name 
    """
    return self._execute_query(query) or []

  def _get_pay_receipts_is_period_opened(self, company_id, address_type, year, month):
    query = f"""
       SELECT 
           address.inspector_id AS inspector_id, 
           inspector.name AS inspector_name, 
           COUNT(address.id) AS pay_receipt_count,
           SUM(pra.total_amount)  AS pay_receipt_amount,
           0 AS pay_receipt_state_subsidy
       FROM ref_address address
       INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id  AND address.company_id = {company_id} AND address.type = '{address_type}'
       INNER JOIN pay_receipt_address pra ON pra.address_id = address.id
       INNER JOIN pay_receipt pr  ON pr.company_id = {company_id} AND pr.address_type = '{address_type}' AND pra.receipt_id = pr.id AND pr.year::integer = {year} AND pr.month::integer = {month}
       GROUP BY  address.inspector_id, inspector.id;
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

  def _get_total_pay_is_period_opened(self, company_id, address_type, first_day_of_month):
    query = f"""
      select address.inspector_id as inspector_id, inspector.name as inspector_name,
      count(CASE WHEN round(cast(total_pay.invoiced_amount as numeric),2) > round(cast(total_pay.paid_amount as numeric),2) THEN total_pay.address_id END) AS total_pay_user_count,
      sum(total_pay.invoiced_amount)- sum(total_pay.paid_amount) as total_pay_amount
      from ref_address address
      inner join hr_employee inspector on inspector.id = address.inspector_id
      left join (
        select invoice.address_id as address_id , sum(invoice.amount_total) as invoiced_amount, coalesce(paid.amount,0.0) as paid_amount
        from pay_receipt_address_invoice invoice
        left join (
          select invoice.address_id as address_id, sum(payment_line.amount) as amount
          from pay_address_payment_line payment_line
          inner join pay_receipt_address_invoice invoice on invoice.id = payment_line.invoice_id and invoice.company_id = {company_id} and payment_line.period_id in ( select pp.id from pay_period pp where concat(pp.year, '-', pp.month, '-01')::date < '{first_day_of_month}'::date and pp.company_id = {company_id} and pp.address_type= '{address_type}' )
          where invoice.company_id = {company_id}
          group by invoice.address_id
        ) paid on invoice.company_id = {company_id} and paid.address_id = invoice.address_id
        inner join ref_address address on address.id = invoice.address_id and address.type = '{address_type}'
        where invoice.company_id = {company_id} and concat(invoice.year, '-', invoice.month, '-', '01')::date <= '{first_day_of_month}'::date
        group by invoice.address_id, paid.amount
      ) total_pay on total_pay.address_id = address.id
      where address.company_id = {company_id} and address.type = '{address_type}'
      group by address.inspector_id, inspector.id
    """
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
    return self._execute_query(query)

  def _get_total_pay_is_period_closed(self, company_id, first_day_of_month, address_type, period_id):
    query = f"""
      SELECT inspector.id AS inspector_id, inspector.name AS inspector_name,
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
    return self._execute_query(query)

  def _get_advance_payments_is_period_opened(self, company_id, address_type, last_day_of_month, year, month):
    query = f"""
      SELECT
        address.inspector_id AS inspector_id,
        inspector.name AS inspector_name,
        COUNT(CASE WHEN round(cast(advance_payment.amount as numeric),2) > round(cast(advance_payment.amount as numeric),2) THEN advance_payment.address_id END) AS advanced_paid_user_count,
        round(cast(coalesce(SUM(advance_payment.amount),0.0) as numeric),2) AS advanced_paid_amount
      FROM ref_address address
      INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id
      left join (
        select invoice.address_id as address_id, sum(payment_line.amount) as amount 
        from pay_address_payment_line payment_line
        inner join pay_receipt_address_invoice invoice on invoice.id = payment_line.invoice_id and invoice.year::integer = {year} and invoice.month::integer = {month} and invoice.company_id = {company_id}
        inner join pay_address_payment payment on payment.id = payment_line.payment_id and payment.date <= '{last_day_of_month}'
        where payment_line.period_id in (select pp.id as id from pay_period pp where pp.company_id = {company_id} and pp.address_type = '{address_type}' and pp.year::integer = {year} and pp.month::integer = {month})
        group by invoice.address_id
      ) advance_payment on advance_payment.address_id = address.id 
      WHERE address.company_id = {company_id} AND address.type = '{address_type}'
      GROUP BY address.inspector_id, inspector.id;
    """
    return self._execute_query(query) or []

  def _get_advance_payments_is_period_closed(self, company_id, address_type, last_day_of_month, year, month, period_id):
    query = f"""
      SELECT
        inspector.id AS inspector_id,
        inspector.name AS inspector_name,
        COUNT(CASE WHEN round(cast(advance_payment.amount as numeric),2) > 0 THEN advance_payment.address_id END) AS advanced_paid_user_count,
        round(cast(coalesce(SUM(advance_payment.amount),0.0) as numeric),2) AS advanced_paid_amount
      FROM pay_period_report report
      inner join hr_employee inspector on inspector.id = report.inspector_id 
      left join (
        select invoice.address_id as address_id, sum(payment_line.amount) as amount 
        from pay_address_payment_line payment_line
        inner join pay_receipt_address_invoice invoice on invoice.id = payment_line.invoice_id and invoice.year::integer = {year} and invoice.month::integer = {month} and invoice.company_id = {company_id}
        inner join pay_address_payment payment on payment.id = payment_line.payment_id and payment.date <= '{last_day_of_month}'
        where payment_line.period_id in (select pp.id as id from pay_period pp where pp.company_id = {company_id} and pp.address_type = '{address_type}' and pp.year::integer = {year} and pp.month::integer = {month})
        group by invoice.address_id
      ) advance_payment on advance_payment.address_id = report.address_id
      WHERE report.period_id = {period_id}
      GROUP BY inspector.id;
    """
    return self._execute_query(query) or []

  def _get_c1_payments_is_period_opened(self, company_id, address_type, first_day_of_month, year, month):
    query = f"""
      SELECT inspector.id AS inspector_id, inspector.name AS inspector_name, SUM(CASE WHEN c1_payment.amount > 0 THEN c1_payment.user_count ELSE 0 END) AS c1_user_count, SUM(CASE WHEN c1_payment.amount > 0 THEN c1_payment.amount ELSE 0 END) AS c1_amount
      FROM (
        SELECT * FROM hr_employee inspector
        WHERE inspector.id IN (
          SELECT address.inspector_id FROM ref_address address 
          WHERE address.company_id = {company_id} AND address.type = '{address_type}'
          GROUP BY address.inspector_id
        )
      ) inspector
      LEFT JOIN (
        SELECT address.inspector_id AS inspector_id, SUM(payment_line.amount) AS amount, COUNT(address.id) AS user_count 
        FROM pay_receipt_address_invoice invoice
        INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where pp.company_id={company_id} and pp.address_type='{address_type}' and pp.year::integer = {year} and pp.month::integer = {month})
        INNER JOIN pay_address_payment payment ON payment.id = payment_line.payment_id 
        INNER JOIN ref_address address ON address.id = invoice.address_id
        WHERE invoice.company_id = {company_id} AND CONCAT(invoice.year, '-', invoice.month, '-', '01')::date < '{first_day_of_month}'::date
        GROUP BY address.inspector_id
      ) c1_payment 
      ON c1_payment.inspector_id = inspector.id
      GROUP BY inspector.id, inspector.name;
    """
    return self._execute_query(query) or []

  def _get_c1_payments_is_period_closed(self, company_id, address_type, first_day_of_month, year, month, period_id):
    query = f"""
      SELECT inspector.id AS inspector_id, inspector.name AS inspector_name, SUM(CASE WHEN c1_payment.amount > 0 THEN c1_payment.user_count ELSE 0 END) AS c1_user_count, SUM(CASE WHEN c1_payment.amount > 0 THEN c1_payment.amount ELSE 0 END) AS c1_amount
      from  (
          SELECT report.inspector_id AS inspector_id, SUM(payment_line.amount) AS amount, COUNT(report.address_id) AS user_count 
          FROM pay_receipt_address_invoice invoice
          INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where pp.company_id={company_id} and pp.address_type='{address_type}' and pp.year::integer = {year} and pp.month::integer = {month})
          INNER JOIN pay_address_payment payment ON payment.id = payment_line.payment_id 
          INNER JOIN pay_period_report report ON report.address_id = invoice.address_id and report.period_id = {period_id}
          WHERE invoice.company_id = {company_id} AND CONCAT(invoice.year, '-', invoice.month, '-', '01')::date < '{first_day_of_month}'::date
          GROUP BY report.inspector_id
      ) c1_payment
      left join hr_employee inspector on inspector.id = c1_payment.inspector_id
      GROUP BY inspector.id, inspector.name;
    """
    return self._execute_query(query) or []

  def _get_tz_payments_is_period_opened(self, company_id, address_type, year, month):
    query = f"""
      SELECT 
        inspector.id AS inspector_id, 
        inspector.name AS inspector_name, 
        SUM(CASE WHEN tz_payment.amount > 0 THEN tz_payment.user_count ELSE 0 END) AS tz_user_count, 
        SUM(CASE WHEN tz_payment.amount > 0 THEN tz_payment.amount ELSE 0 END) AS tz_amount
      FROM (
        SELECT * FROM hr_employee inspector
        WHERE inspector.id IN (
          SELECT address.inspector_id FROM ref_address address 
          WHERE address.company_id = {company_id} AND address.type = '{address_type}'
          GROUP BY address.inspector_id
        )
      ) inspector
      LEFT JOIN (
        SELECT address.inspector_id AS inspector_id, SUM(payment_line.amount) AS amount, COUNT(address.id) AS user_count 
        FROM pay_receipt_address_invoice invoice
        INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where pp.company_id={company_id} and pp.address_type='{address_type}' and pp.year::integer = {year} and pp.month::integer = {month})
        INNER JOIN pay_address_payment payment ON payment.id = payment_line.payment_id 
        INNER JOIN ref_address address ON address.id = invoice.address_id
        WHERE invoice.company_id = {company_id} AND invoice.year::integer = '{year}'::integer AND invoice.month::integer = '{month}'::integer
        GROUP BY address.inspector_id
      ) tz_payment 
      ON tz_payment.inspector_id = inspector.id
      GROUP BY inspector.id, inspector.name;
    """
    return self._execute_query(query) or []

  def _get_tz_payments_is_period_closed(self, company_id, address_type, year, month, period_id):
    query = f"""
      	SELECT 
          inspector.id AS inspector_id, 
          inspector.name AS inspector_name, 
          SUM(CASE WHEN tz_payment.amount > 0 THEN tz_payment.user_count ELSE 0 END) AS tz_user_count, 
          SUM(CASE WHEN tz_payment.amount > 0 THEN tz_payment.amount ELSE 0 END) AS tz_amount
        from  (
          SELECT report.inspector_id AS inspector_id, SUM(payment_line.amount) AS amount, COUNT(report.address_id) AS user_count 
          FROM pay_receipt_address_invoice invoice
          INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where pp.company_id={company_id} and pp.address_type='{address_type}' and pp.year::integer = {year} and pp.month::integer = {month})
          INNER JOIN pay_address_payment payment ON payment.id = payment_line.payment_id 
          INNER JOIN pay_period_report report ON report.address_id = invoice.address_id and report.period_id = {period_id}
          WHERE invoice.company_id = {company_id} AND invoice.year::integer = '{year}'::integer AND invoice.month::integer = '{month}'::integer
          GROUP BY report.inspector_id
        ) tz_payment 
        left join hr_employee inspector ON tz_payment.inspector_id = inspector.id
        GROUP BY inspector.id, inspector.name;
    """
    return self._execute_query(query) or []

  def _get_total_paid_is_period_opened(self, company_id, address_type, year, month):
    query = f"""
      SELECT address.inspector_id AS inspector_id, inspector.name AS inspector_name, COUNT(CASE WHEN total_paid.paid_amount > 0.0 THEN 1 END) AS total_paid_user_count, SUM(total_paid.paid_amount) as total_paid_amount
      FROM ref_address address
      INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id
      LEFT JOIN (
        SELECT invoice.address_id AS address_id, sum(payment_line.amount) AS paid_amount
        FROM pay_receipt_address_invoice invoice
        inner join pay_address_payment_line payment_line on payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where pp.company_id={company_id} and pp.address_type='{address_type}' and pp.year::integer = {year} and pp.month::integer = {month})
        group by invoice.address_id   	
      ) total_paid ON total_paid.address_id = address.id
      WHERE address.company_id = {company_id} AND address.type = '{address_type}'
      GROUP BY address.inspector_id, inspector.id;
    """
    return self._execute_query(query) or []

  def _get_total_paid_is_period_closed(self, company_id, address_type, year, month, period_id):
    query = f"""
      select 
         report.inspector_id as inspector_id,
         inspector.name as inspector_name,
         count(report.address_id) as total_paid_user_count,
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
      SELECT 
        address.inspector_id AS inspector_id, 
        inspector.name AS inspector_name,
        COUNT(CASE WHEN round(cast(last_balance.invoiced_amount as numeric),2) > round(cast(last_balance.paid_amount as numeric),2) THEN last_balance.address_id END) AS last_balance_user_count,
        SUM(last_balance.invoiced_amount) - SUM(last_balance.paid_amount) AS last_balance_amount
      FROM ref_address address
      INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id
      LEFT JOIN (
        SELECT invoice.address_id AS address_id, SUM(invoice.amount_total) AS invoiced_amount, COALESCE(paid.amount, 0.0) AS paid_amount
        FROM pay_receipt_address_invoice invoice
        LEFT JOIN (
          SELECT invoice.address_id AS address_id, SUM(payment_line.amount) AS amount
          FROM pay_address_payment_line payment_line
          INNER JOIN 
            pay_receipt_address_invoice invoice ON invoice.id = payment_line.invoice_id 
            AND invoice.company_id = {company_id} 
            AND payment_line.period_id IN (
              SELECT pp.id 
              FROM pay_period pp 
              WHERE TO_DATE(CONCAT(pp.year, '-', LPAD(pp.month::text, 2, '0'), '-01'), 'YYYY-MM-DD') <= '{first_day_of_month}' 
              AND pp.company_id = {company_id}
              AND pp.address_type = '{address_type}'
            )
          WHERE invoice.company_id = {company_id}
          GROUP BY invoice.address_id
        ) paid ON invoice.company_id = {company_id} AND paid.address_id = invoice.address_id
        INNER JOIN ref_address address ON address.id = invoice.address_id AND address.type = '{address_type}'
        WHERE invoice.company_id = {company_id} AND TO_DATE(CONCAT(invoice.year, '-', LPAD(invoice.month::text, 2, '0'), '-01'), 'YYYY-MM-DD') <= '{first_day_of_month}'
        GROUP BY invoice.address_id, paid.amount
      ) last_balance ON last_balance.address_id = address.id
      WHERE address.company_id = {company_id} AND address.type = '{address_type}'
      GROUP BY address.inspector_id, inspector.id;
    """
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
    return self._execute_query(query) or []

  def _get_last_balance_is_period_closed(self, company_id, address_type, year, month, period_id):
    query = f"""
      select 
         report.inspector_id as inspector_id,
         inspector.name as inspector_name,
         count(report.address_id) as last_balance_user_count,
         SUM(ROUND(cast(report.last_balance_amount as numeric),2)) AS last_balance_amount
      from pay_period_report report
      inner join pay_period period on period.company_id={company_id} and period.address_type='{address_type}' and period.year::integer = {year} and period.month::integer = {month}
      inner join hr_employee inspector on inspector.id = report.inspector_id
      where report.last_balance_amount != 0 and report.period_id = {period_id}
      group by report.inspector_id , inspector."name" 
    """
    return self._execute_query(query) or []

  def _get_uoo_residual_paid_is_period_opened(self, company_id, address_type, first_day_of_month,
                                              last_day_of_next_month):
    print('last_day_of_next_month', last_day_of_next_month)
    query = f"""
      SELECT address.inspector_id AS inspector_id, inspector.name AS inspector_name, COUNT(CASE WHEN round(cast(payment.amount as numeric),2) > round(cast(paid.amount as numeric),2) THEN payment.address_id END) AS uoo_paid_user_count, SUM(payment.amount) - SUM(paid.amount) AS uoo_paid_amount
      FROM ref_address address
      INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id
      LEFT JOIN (
        select payment.address_id as address_id, round(cast(sum(payment.amount) as numeric),2) as amount 
        from pay_address_payment payment
        inner join ref_address address on address.id = payment.address_id and address.company_id = {company_id} and address.type = '{address_type}'
        where payment.date <= '{last_day_of_next_month}'
        group by payment.address_id
      ) payment ON payment.address_id = address.id
      LEFT JOIN (
        select payment.address_id as address_id, round(cast(sum(payment_line.amount) as numeric),2) as amount 
        from pay_address_payment payment
        inner join ref_address address on address.id = payment.address_id and address.company_id = {company_id} and address.type = '{address_type}'
        inner join pay_address_payment_line payment_line on payment_line.payment_id = payment.id and payment_line.period_id in (select pp.id as id from pay_period pp where pp.company_id = {company_id} and pp.address_type = '{address_type}' and concat(pp.year,'-', pp.month, '-01')::date <= '{first_day_of_month}'::date)
        where payment.date <= '{last_day_of_next_month}'
        group by payment.address_id
      ) paid ON paid.address_id = address.id
      WHERE address.company_id = {company_id} AND address.type = '{address_type}'
      GROUP BY address.inspector_id, inspector.id;
    """
    return self._execute_query(query) or []

  def _get_uoo_residual_paid_is_period_closed(self, company_id, address_type, period_id, first_day_of_month,
                                              last_day_of_next_month):
    query = f"""
      SELECT 
        report.inspector_id AS inspector_id, 
        inspector.name AS inspector_name, 
        COUNT(CASE WHEN round(cast(payment.amount as numeric),2) > round(cast(paid.amount as numeric),2) THEN payment.address_id END) AS uoo_paid_user_count, 
        SUM(payment.amount) - SUM(paid.amount) AS uoo_paid_amount
      FROM pay_period_report report
      INNER JOIN hr_employee inspector ON inspector.id = report.inspector_id
      LEFT JOIN (
          select payment.address_id as address_id, round(cast(sum(payment.amount) as numeric),2) as amount 
          from pay_address_payment payment
          inner join ref_address address on address.id = payment.address_id and address.company_id = {company_id} and address.type = '{address_type}'
          where payment.date <= '{last_day_of_next_month}'
          group by payment.address_id
        ) payment ON payment.address_id =report.address_id
      LEFT JOIN (
        select payment.address_id as address_id, round(cast(sum(payment_line.amount) as numeric),2) as amount 
        from pay_address_payment payment
        inner join ref_address address on address.id = payment.address_id and address.company_id = {company_id} and address.type = '{address_type}'
        inner join pay_address_payment_line payment_line on payment_line.payment_id = payment.id and payment_line.period_id in (select pp.id as id from pay_period pp where pp.company_id = {company_id} and pp.address_type = '{address_type}' and concat(pp.year,'-', pp.month, '-01')::date <= '{first_day_of_month}'::date)
        where payment.date <= '{last_day_of_next_month}'
        group by payment.address_id
      ) paid ON paid.address_id = report.address_id
      WHERE report.period_id = {period_id}
      GROUP BY report.inspector_id, inspector.id;
    """
    return self._execute_query(query) or []

  def _get_current_month_uoo_paid_is_period_opened(self, company_id, address_type, first_day_of_month, next_month,
                                                   next_year):
    query = f"""
      SELECT address.inspector_id AS inspector_id, inspector.name AS inspector_name, 
        count(
          case 
            WHEN ROUND(COALESCE(payment.amount, 0.0)::numeric, 2) > ROUND(COALESCE(paid.amount, 0.0)::numeric, 2) 
            THEN paid.address_id 
          end
        ) AS current_user_count,
        round(cast(coalesce(sum(payment.amount),0.0) - coalesce(sum(paid.amount),0.0) as numeric), 2) as current_amount
      FROM ref_address address
      INNER JOIN hr_employee inspector ON inspector.id = address.inspector_id
      left join (
        select payment.address_id as address_id, sum(payment.amount) as amount 
        from pay_address_payment payment
        inner join ref_address address on payment.address_id = address.id and address.company_id = {company_id} and address.type = '{address_type}'
        where extract(year from payment.date) = {next_year} and extract(month from payment.date) = {next_month}
        group by payment.address_id
      ) payment on payment.address_id = address.id 
      left join (
        select payment.address_id as address_id, sum(payment_line.amount) as amount 
        from pay_address_payment payment
        inner join pay_address_payment_line payment_line on payment_line.payment_id = payment.id and payment_line.period_id in (select pp.id as id from pay_period pp where pp.company_id = {company_id} and pp.address_type = '{address_type}' and concat(pp.year,'-',pp.month,'-01') <= '{first_day_of_month}')
        inner join ref_address address on payment.address_id = address.id and address.company_id = {company_id} and address.type = '{address_type}'
        where extract(year from payment.date) = {next_year} and extract(month from payment.date) = {next_month}
        group by payment.address_id
      ) paid on paid.address_id = address.id
      WHERE address.company_id = {company_id} AND address.type = '{address_type}'
      GROUP BY address.inspector_id, inspector.id;
    """
    return self._execute_query(query) or []

  def _get_current_month_uoo_paid_is_period_closed(self, company_id, address_type, period_id, next_month, next_year,
                                                   first_day_of_month):
    query = f"""
      SELECT report.inspector_id AS inspector_id, inspector.name AS inspector_name, 
        count(
          case 
            WHEN ROUND(COALESCE(payment.amount, 0.0)::numeric, 2) > ROUND(COALESCE(paid.amount, 0.0)::numeric, 2) 
            THEN paid.address_id 
          end
        ) AS current_user_count,
        round(cast(coalesce(sum(payment.amount),0.0) - coalesce(sum(paid.amount),0.0) as numeric), 2) as current_amount
      FROM pay_period_report report
      INNER JOIN hr_employee inspector ON inspector.id = report.inspector_id
      left join (
        select payment.address_id as address_id, sum(payment.amount) as amount 
        from pay_address_payment payment
        inner join ref_address address on payment.address_id = address.id and address.company_id = {company_id} and address.type = '{address_type}'
        where extract(year from payment.date) = {next_year} and extract(month from payment.date) = {next_month}
        group by payment.address_id
      ) payment on payment.address_id = report.address_id 
      left join (
        select payment.address_id as address_id, sum(payment_line.amount) as amount 
        from pay_address_payment payment
        inner join pay_address_payment_line payment_line on payment_line.payment_id = payment.id and payment_line.period_id in (select pp.id as id from pay_period pp where pp.company_id = {company_id} and pp.address_type = '{address_type}' and concat(pp.year,'-',pp.month,'-01') <= '{first_day_of_month}')
        inner join ref_address address on payment.address_id = address.id and address.company_id = {company_id} and address.type = '{address_type}'
        where extract(year from payment.date) = {next_year} and extract(month from payment.date) = {next_month}
        group by payment.address_id
      ) paid on paid.address_id = report.address_id 
      WHERE report.period_id = {period_id}
      GROUP BY report.inspector_id, inspector.id;
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
                    SELECT pp.id 
                    FROM pay_period pp 
                    WHERE pp.company_id = {company_id}
                    AND pp.address_type = '{address_type}' 
                    AND concat(pp.year, '-', pp.month, '-01')::date <= '{first_day_of_month}'::date 
                )
            GROUP BY  invoice.id, address.id
            having round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) > 0.0
          ) tmp 
          inner join hr_employee inspector on inspector.id = tmp.inspector_id
          group by tmp.address_id, tmp.inspector_id, inspector.id
        ) tmp
      group by tmp.inspector_id, tmp.inspector_name;
    """
    return self._execute_query(query)

  def _get_two_or_more_months_is_period_closed(self, company_id, address_type, year, month):
    query = f"""
      SELECT inspector.id AS inspector_id, inspector.name AS inspector_name, tmp.two_months  as two_months, tmp.more_months as more_months
      FROM (
          SELECT report.inspector_id AS inspector_id, COUNT(CASE WHEN array_length(string_to_array(report.unpaid_invoices, ','), 1) = 2 THEN 1 END) AS two_months, COUNT(CASE WHEN array_length(string_to_array(report.unpaid_invoices, ','), 1) >= 3 THEN 1 END) AS more_months
          FROM pay_period_report report
          WHERE report.period_id IN (SELECT pp.id FROM pay_period pp WHERE pp.company_id = {company_id} AND pp.address_type = '{address_type}' AND pp.year::integer = {year} AND pp.month::integer = {month})
          GROUP BY report.inspector_id
      ) tmp
      LEFT JOIN hr_employee inspector ON tmp.inspector_id = inspector.id
      group by inspector.id, inspector.name, tmp.two_months, tmp.more_months
    """
    return self._execute_query(query)

  def download_pdf(self):
    """Download the PDF report."""
    if not self.residual_date:
      raise UserError('No residual date selected.')

    grouped_data, address_type, company_name, date, logo_data_uri = self._get_residual_report_values(
      self.residual_date)

    report_action = self.env.ref('ub_kontor.action_pay_user_residual_pdf_report', raise_if_not_found=False)
    if not report_action:
      raise UserError('The report action "ub_kontor.action_pay_user_residual_pdf_report" is not defined.')

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
