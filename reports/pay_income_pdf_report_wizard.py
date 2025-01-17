from odoo import models, fields, api
from datetime import datetime
from collections import defaultdict


class PayIncomePdfReportWizard(models.TransientModel):
  _name = 'pay.income.pdf.report.wizard'
  _description = 'Payment Income Report Wizard'

  company_id = fields.Many2one(
    'res.company',
    string='ХҮТ',
    index=True,
    default=lambda self: self.env.user.company_id
  )
  address_type = fields.Selection(
    [('OS', 'ОС'), ('AAN', 'ААН')],
    string='Тоотын төрөл',
    required=True,
    default=lambda self: self.env.user.access_type
  )
  income_year = fields.Integer(
    string='Тухайн жилийн он',
    required=True,
    default=lambda self: datetime.now().year
  )
  month = fields.Selection(
    [(str(i), f'{i} сар') for i in range(1, 13)],
    string='Month',
    required=True
  )
  bank_ids = fields.Many2many(
    'pay.bank',
    string='Банк сонгох',
    required=True,
    default=lambda self: self._default_bank_ids()
  )
  current_date = fields.Date(string='Current Date', default=fields.Date.context_today)

  @api.model
  def _default_bank_ids(self):
    bank_names = ['Хаан банк', 'Голомт банк', 'Капитрон банк', 'Төрийн банк', 'ОСНААУГ']
    return self.env['pay.bank'].search([('name', 'in', bank_names)])

  def _prepare_data(self):
    header_data, selected_sub_headers = self._fetch_header_data()
    main_data = self._fetch_main_data(selected_sub_headers)
    return header_data, main_data

  def get_address_type_display(self):
    return dict(self._fields['address_type'].selection).get(self.address_type, 'Unknown')

  def _fetch_header_data(self):
    # Initial static header data
    header_data = [{'header_title': 'Огноо', 'sub_headers': [], 'rowspan': 2, 'colspan': 1}]
    bank_ids = self.bank_ids.ids

    print('bank_ids:', bank_ids)

    if not bank_ids:
      return header_data, {}

    # Query to fetch bank and account data
    query = """
            SELECT account.id AS account_id, bank.name AS bank_name, account.name AS account_name
            FROM pay_bank_account account
            JOIN pay_bank bank ON bank.id = account.bank_id
            WHERE account.company_id = %s AND bank.id = ANY(%s)
            ORDER BY bank.name, account.name; 
        """

    self.env.cr.execute(query, (self.company_id.id, bank_ids))
    results = self.env.cr.fetchall()

    # Organize headers based on bank and account names
    bank_header_map = {}
    for account_id, bank_name, account_name in results:
      bank_header_map.setdefault(bank_name, []).append({'account_name': account_name, 'account_id': account_id})

    header_data.extend([
      {'header_title': bank_name, 'sub_headers': sub_headers, 'rowspan': 1, 'colspan': len(sub_headers)}
      for bank_name, sub_headers in bank_header_map.items()
    ])
    header_data.append({'header_title': 'Нийт дүн', 'sub_headers': [], 'rowspan': 2, 'colspan': 1})
    print('header_data:', header_data)

    return header_data, bank_header_map

  def _fetch_main_data(self, selected_sub_headers):
    next_month = int(self.month) + 1 if int(self.month) < 12 else 1
    income_year = self.income_year if next_month != 1 else self.income_year + 1
    company_id = self.company_id.id
    query = """
        SELECT DISTINCT pap."date" AS paid_date
        FROM pay_address_payment pap
        LEFT JOIN ref_address ra ON pap.address_id = ra.id and ra.company_id = %s
        WHERE 
            EXTRACT(YEAR FROM pap."date") = %s
            AND EXTRACT(MONTH FROM pap."date") = %s
            AND ra.type = %s
        order by pap.date::date asc
    """

    self.env.cr.execute(query, (company_id,income_year, int(next_month), self.address_type))
    unique_dates = [row['paid_date'] for row in self.env.cr.dictfetchall()] # Ensure unique dates

    query = """
        SELECT
            pap."date" AS paid_date,
            pb.name AS bank_name,
            pba.name AS account_name,
            pba.id AS account_id,
            SUM(ROUND(CAST(pap.amount AS numeric), 2)) AS total_amount
        FROM pay_address_payment pap
        JOIN pay_bank_account pba ON pba.id = pap.account_id AND pba.company_id = %s
        JOIN pay_bank pb ON pb.id = pba.bank_id
        LEFT JOIN ref_address ra ON pap.address_id = ra.id
        WHERE
            EXTRACT(YEAR FROM pap."date") = %s
            AND EXTRACT(MONTH FROM pap."date") = %s
            AND ra.type = %s
            AND pb.id = ANY(%s)
        GROUP BY pap."date", pb.name, pba.name, pba.id
    """
    # print(query%)
    self.env.cr.execute(query, (
      self.company_id.id,
      income_year,
      int(next_month),
      self.address_type,
      self.bank_ids.ids
    ))

    fetched_data = self.env.cr.dictfetchall()

    if not isinstance(selected_sub_headers, dict):
      raise TypeError("selected_sub_headers should be a dictionary with bank names as keys.")

    final_data = {date: {'paid_date': date, 'total_amount': 0.0} for date in unique_dates}

    for row in fetched_data:
      date = row['paid_date']
      account_id = row['account_id']
      key = f"{row['bank_name']}_{row['account_name']}_{account_id}"

      if date not in final_data:
        final_data[date] = {'paid_date': date, 'total_amount': 0.0}

      final_data[date]['total_amount'] += row['total_amount']
      final_data[date][key] = final_data[date].get(key, 0.0) + row['total_amount']

    final_data_list = list(final_data.values())
    print('final_data:', final_data_list)
    return final_data_list

  def download_pdf(self):
    header_data, main_data = self._prepare_data()
    current_date_str = self.current_date.strftime('%d/%m/%Y') if self.current_date else ''
    total_amount = sum(data.get('total_amount', 0.0) for data in main_data if data and isinstance(data, dict))
    report_action = self.env.ref('ub_kontor.action_pay_income_pdf_report')

    return report_action.report_action(self, data={
      "company_id": self.company_id.id,
      'company_name': self.env.company.name,
      'header_data': header_data,
      'main_data': main_data,
      'income_year': self.income_year,
      'month': self.month,
      'total_amount': total_amount,
      'current_date': current_date_str,
      'address_type': self.get_address_type_display(self.address_type),
      'logo_data_uri': self.image_data_uri(self.company_id.logo)
    })

  def get_address_type_display(self, address_type):
    """Return the display value for the address type."""
    field = self.env['pay.receipt.pdf.report.wizard']._fields['address_type']
    return dict(field.selection).get(address_type, '')

  def image_data_uri(self, logo):
    """Convert the logo image to a data URI for rendering in the PDF."""
    if logo:
      image = logo.decode('utf-8')
      return f"data:image/png;base64,{image}"
    return ''
