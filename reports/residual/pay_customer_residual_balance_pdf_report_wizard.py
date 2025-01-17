from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
from dateutil.relativedelta import relativedelta
import xlsxwriter
import base64
import io
import logging

_logger = logging.getLogger('KHATNAA:')


class PayCustomerResidualBalancePDFReportWizard(models.TransientModel):
    _name = 'pay.customer.residual.balance.pdf.report.wizard'
    _description = 'Pay Customer Residual Balance PDF Report Wizard'

    pay_receipt_id = fields.Many2one('pay.receipt', string='Payment Receipt', required=True,
                                     default=lambda self: self._get_default_pay_receipt())
    company_id = fields.Many2one('res.company', 'ХҮТ', index=True,
                                 default=lambda self: self.env.user.company_id.id)
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
        return self.env.cr.fetchall() or []

    def _get_residual_report_values(self, residual_date):
        """Fetch residual report values for the selected date."""
        if not residual_date:
            raise UserError('No residual date provided.')

        year, month = map(int, residual_date.split('/'))
        next_month = month + 1 if month < 12 else 1
        company_id = self.env.company.id
        address_type = self.env.user.access_type
        first_day_of_month = datetime(year, month, 1).strftime('%Y-%m-%d')
        last_day_of_month = (datetime(year, month, 1) + relativedelta(months=1, days=-1)).strftime('%Y-%m-%d')
        period_id = self.env['pay.period'].sudo().search(
            [('company_id', '=', company_id), ('address_type', '=', address_type), ('year', '=', str(year)),
             ('month', '=', str(month).zfill(2))], limit=1)

        results = {
            'residual_balance': [],
        }

        _logger.warning("------------------------------------------------------------------------")

        # Fetch data
        if not period_id or period_id.state == 'opened':
            results['residual_balance'] = self._get_residual_balance_is_period_opened(company_id, address_type,
                                                                                      first_day_of_month,
                                                                                      last_day_of_month, year, month,
                                                                                      next_month)
            _logger.warning(len(results['residual_balance']))

        elif not period_id or period_id.state == 'closed':
            results['residual_balance'] = self._get_residual_balance_is_period_closed(company_id, address_type,
                                                                                      first_day_of_month,
                                                                                      last_day_of_month, year, month,
                                                                                      next_month)
            _logger.warning(len(results['residual_balance']))
        _logger.warning("------------------------------------------------------------------------")

        # print('residual_balance', residual_balance)
        report_data = [
            {
                'address_id': row[0],
                'address_name': row[1],
                'address_code': row[2],
                'inspector_id': row[3],
                'inspector_name': row[4],
                'pre_month_residual': row[5],
                'current_invoiced': row[6],
                'advance_payment_amount': row[7],
                'c1_payment_amount': row[8],
                'tz_payment_amount': row[9],
                'paid_amount': row[10],
                'last_residual': row[11],
            }
            for row in results['residual_balance']
        ]

        return (
            report_data,
            address_type,
            self.get_company_name(company_id),
            self.date,
            self.image_data_uri(self.company_id.logo),
        )

    def _get_residual_balance_is_period_opened(self, company_id, address_type, first_day_of_month, last_day_of_month,
                                               year, month, next_month):
        query = f"""
        WITH pre_data AS (
          SELECT
            address.id AS address_id, address.name AS address_name, address.code AS address_code, 
            address.inspector_id AS inspector_id, inspector.name AS inspector_name, 
            sum(coalesce(first_balance.amount,0.0)) AS pre_month_residual, COALESCE(current_invoiced.amount, 0.0) AS current_invoiced, 
            COALESCE(advance_payment.amount, 0.0) AS advance_payment_amount, COALESCE(c1_payment.amount, 0.0) AS c1_payment_amount, 
            COALESCE(tz_payment.amount, 0.0) AS tz_payment_amount, COALESCE(total_paid.amount, 0.0) AS paid_amount
          FROM ref_address address
          INNER join hr_employee inspector ON inspector.id = address.inspector_id AND address.company_id = {company_id} AND address.type = '{address_type}'
          LEFT JOIN (
             select report.address_id as address_id,report.last_balance_amount as amount from pay_period_report report
             inner join pay_period period on period.id = report.period_id and period.company_id = {company_id} and period.address_type = '{address_type}' 
               and concat(period.year, '-', period.month, '-01')::date = '{first_day_of_month}'::date - INTERVAL '1 month'
          ) first_balance ON first_balance.address_id = address.id
          LEFT JOIN (
            select invoice.address_id AS address_id, SUM(invoice.amount_total) AS amount
            FROM pay_receipt_address_invoice invoice
            where invoice.year::integer = {year} AND invoice.month::integer = {month}::integer AND invoice.company_id = {company_id}
            GROUP BY invoice.address_id
          ) current_invoiced ON current_invoiced.address_id = address.id
          LEFT JOIN (
            select invoice.address_id AS address_id, SUM(payment_line.amount) AS amount
            FROM pay_address_payment_line payment_line
            INNER join pay_receipt_address_invoice invoice ON invoice.id = payment_line.invoice_id
              AND invoice.year::integer = {year}::integer AND invoice.month::integer = {month}::integer AND invoice.company_id = {company_id}
            INNER join pay_address_payment payment ON payment.id = payment_line.payment_id AND payment.date <= '{last_day_of_month}'::date
            GROUP BY invoice.address_id
          ) advance_payment ON advance_payment.address_id = address.id
          LEFT JOIN (
            select invoice.address_id AS address_id, SUM(payment_line.amount) AS amount
            FROM pay_receipt_address_invoice invoice
            INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id
            INNER join pay_address_payment payment ON payment.id = payment_line.payment_id
              AND EXTRACT(YEAR FROM payment.date)::integer = {year}::integer AND EXTRACT(MONTH FROM payment.date)::integer = {next_month}::integer
            where invoice.company_id = {company_id} AND CONCAT(invoice.year, '-', invoice.month, '-', '01')::date < '{first_day_of_month}'::date
            GROUP BY invoice.address_id
          ) c1_payment ON c1_payment.address_id = address.id
          LEFT JOIN (
            select invoice.address_id AS address_id, SUM(payment_line.amount) AS amount
            FROM pay_receipt_address_invoice invoice
            INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id
            INNER join pay_address_payment payment ON payment.id = payment_line.id and EXTRACT(YEAR FROM payment.date)::integer = {year}
              AND EXTRACT(MONTH FROM payment.date)::integer = {next_month}::integer
            where invoice.company_id = {company_id} AND invoice.year::integer = {year}::integer AND invoice.month::integer = {month}::integer
            GROUP BY invoice.address_id
          ) tz_payment ON tz_payment.address_id = address.id
          LEFT JOIN (
            select payment.address_id AS address_id, SUM(payment_line.amount) AS amount
            FROM pay_address_payment payment
            INNER join ref_address address ON address.id = payment.address_id AND address.company_id = {company_id} AND address.type = '{address_type}'
            INNER join pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
              AND payment_line.period_id IN (
                SELECT pp.id FROM pay_period pp
                WHERE CONCAT(pp.year, '-', pp.month, '-01')::date = '{first_day_of_month}'::date AND company_id = {company_id}
              )
            GROUP BY payment.address_id
          ) total_paid ON total_paid.address_id = address.id
          GROUP BY address.id, current_invoiced.amount, total_paid.amount, advance_payment.amount, c1_payment.amount, tz_payment.amount, inspector.id
        ),
        last_data AS (
          select last_balance.address_id as address_id, round(cast(sum(last_balance.residual) as numeric),2) as last_residual
            from (
                SELECT invoice.address_id as address_id, round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual
                FROM pay_receipt_address_invoice invoice
                INNER JOIN ref_address address ON address.id = invoice.address_id and invoice.company_id = {company_id}
                    AND address.type = '{address_type}' AND concat(invoice.year, '-', invoice.month, '-01')::date <= '{first_day_of_month}'::date 
                LEFT JOIN pay_address_payment_line payment ON payment.invoice_id = invoice.id 
                    AND payment.period_id IN (
                        SELECT pp.id FROM pay_period pp 
                        WHERE pp.company_id = {company_id} AND pp.address_type = '{address_type}' AND concat(pp.year, '-', pp.month, '-01')::date <= '{first_day_of_month}'::date 
                    )
                GROUP BY  invoice.id
            ) last_balance
            where last_balance.residual > 0.0
            group by last_balance.address_id
        )
        SELECT
          p.address_id, p.address_name, p.address_code, p.inspector_id, p.inspector_name,
          COALESCE(p.pre_month_residual, 0) AS pre_month_residual, COALESCE(p.current_invoiced, 0) AS current_invoiced,
          COALESCE(p.advance_payment_amount, 0) AS advance_payment_amount, COALESCE(p.c1_payment_amount, 0) AS c1_payment_amount,
          COALESCE(p.tz_payment_amount, 0) AS tz_payment_amount, COALESCE(p.paid_amount, 0) AS paid_amount,
          COALESCE(l.last_residual, 0) AS last_residual
        FROM pre_data p
        LEFT JOIN last_data l ON p.address_id = l.address_id
        order by p.inspector_id;
    """
        return self._execute_query(query) or []

    def _get_residual_balance_is_period_closed(self, company_id, address_type, first_day_of_month, last_day_of_month,
                                               year, month, next_month):
        query = f"""
        WITH pre_data AS (
            SELECT
                address.id AS address_id,
                address.name AS address_name,
                address.code AS address_code,
                address.inspector_id AS inspector_id,
                inspector.name AS inspector_name,
                COALESCE(report.first_balance_amount, 0.0) AS pre_month_residual,
                COALESCE(report.receipt_amount, 0.0) AS current_invoiced,
                COALESCE(advance_payment.amount, 0.0) AS advance_payment_amount,
                COALESCE(c1_payment.amount, 0.0) AS c1_payment_amount,
                COALESCE(tz_payment.amount, 0.0) AS tz_payment_amount,
                COALESCE(total_paid.amount, 0.0) AS paid_amount,
                COALESCE(report.last_balance_amount, 0.0) AS last_residual
            FROM pay_period_report report
            INNER JOIN pay_period period ON period.id = report.period_id and period.company_id = {company_id} and period.year::integer = {year} and period.month::integer = {month} and period.address_type = '{address_type}'
            INNER JOIN hr_employee inspector ON inspector.id = report.inspector_id
            INNER JOIN ref_address address ON address.id = report.address_id
            LEFT JOIN (
                SELECT invoice.address_id, SUM(payment_line.amount) AS amount
                FROM pay_address_payment_line payment_line
                INNER JOIN pay_receipt_address_invoice invoice ON invoice.id = payment_line.invoice_id
                INNER JOIN pay_address_payment payment ON payment.id = payment_line.payment_id
                WHERE invoice.year::integer = {year} AND invoice.month::integer = {month} AND invoice.company_id = {company_id}
                    AND payment.date <= '{last_day_of_month}'
                GROUP BY invoice.address_id
            ) advance_payment ON advance_payment.address_id = address.id
            LEFT JOIN (
                SELECT invoice.address_id, SUM(payment_line.amount) AS amount
                FROM pay_receipt_address_invoice invoice
                INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id
                INNER JOIN pay_address_payment payment ON payment.id = payment_line.payment_id
                WHERE EXTRACT(YEAR FROM payment.date) = {year} AND EXTRACT(MONTH FROM payment.date) = {next_month}
                    AND invoice.company_id = {company_id} AND CONCAT(invoice.year, '-', invoice.month, '-01')::date < '{first_day_of_month}'
                GROUP BY invoice.address_id
            ) c1_payment ON c1_payment.address_id = address.id
            LEFT JOIN (
                SELECT invoice.address_id, SUM(payment_line.amount) AS amount
                FROM pay_receipt_address_invoice invoice
                INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id
                INNER JOIN pay_address_payment payment ON payment.id = payment_line.id
                WHERE EXTRACT(YEAR FROM payment.date) = {year} AND EXTRACT(MONTH FROM payment.date) = {next_month}
                    AND invoice.company_id = {company_id} AND invoice.year::integer = {year} AND invoice.month::integer = {month}
                GROUP BY invoice.address_id
            ) tz_payment ON tz_payment.address_id = address.id
            LEFT JOIN (
                SELECT payment.address_id, SUM(payment_line.amount) AS amount
                FROM pay_address_payment payment
                INNER JOIN ref_address address ON address.id = payment.address_id AND address.company_id = {company_id} AND address.type = '{address_type}'
                INNER JOIN pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
                WHERE payment_line.period_id IN (
                    SELECT pp.id FROM pay_period pp
                    WHERE CONCAT(pp.year, '-', pp.month, '-01')::date = '{first_day_of_month}' AND company_id = {company_id}
                )
                GROUP BY payment.address_id
            ) total_paid ON total_paid.address_id = address.id
            where report.last_balance_amount > 0.0
            GROUP BY address.id, report.id, total_paid.amount, advance_payment.amount, c1_payment.amount, tz_payment.amount, inspector.id, inspector.name
        )
        SELECT
            p.address_id, p.address_name, p.address_code, p.inspector_id, p.inspector_name,
            COALESCE(p.pre_month_residual, 0) AS pre_month_residual,
            COALESCE(p.current_invoiced, 0) AS current_invoiced,
            COALESCE(p.advance_payment_amount, 0) AS advance_payment_amount,
            COALESCE(p.c1_payment_amount, 0) AS c1_payment_amount,
            COALESCE(p.tz_payment_amount, 0) AS tz_payment_amount,
            COALESCE(p.paid_amount, 0) AS paid_amount,
            COALESCE(p.last_residual, 0) AS last_residual
        FROM pre_data p
        order by p.inspector_id;
    """
        print(query)
        return self._execute_query(query) or []

    def download_pdf(self):
        """Download the PDF report."""
        if not self.residual_date:
            raise UserError('No residual date selected.')

        report_action = self.env.ref('ub_kontor.action_pay_customer_residual_balance_pdf_report',
                                     raise_if_not_found=False)

        # Fetching residual report values based on the selected residual date
        report_data, address_type, company_name, report_date, logo_data_uri = self._get_residual_report_values(
            self.residual_date)

        return report_action.report_action(self, data={
            'residual_date': self.residual_date,
            'company_id': self.company_id.id,
            'address_type': self.get_address_type_display(self.address_type),
            'report_data': report_data,
            'company_name': company_name,
            'report_date': report_date,
            'logo_data_uri': logo_data_uri,
        })

    def import_xls(self):
        xls_content = io.BytesIO()
        workbook = xlsxwriter.Workbook(xls_content)
        sheet = workbook.add_worksheet()

        report_data, address_type, company_name, report_date, logo_data_uri = self._get_residual_report_values(
            self.residual_date)

        # Setting up XLS headers
        self._setup_xls_headers(sheet, workbook)

        # Define number format for currency
        number_format = workbook.add_format({'align': 'right', 'num_format': '#,##0.00'})

        # Populate data (rows and calculations)
        row_index = 2
        last_inspector = None
        for row in report_data:
            current_inspector = row.get('inspector_name', '')
            if current_inspector != last_inspector:
                # Inspector row
                sheet.merge_range(row_index, 0, row_index, 9, f'Байцаагч: {current_inspector}',
                                  workbook.add_format(
                                      {'bold': True, 'bg_color': '#f0f0f0',
                                       'align': 'left'}))  # Align inspector name to left
                row_index += 1
                last_inspector = current_inspector

            # Regular row with payment details
            sheet.write(row_index, 0, row.get('address_code', '0'), workbook.add_format({'align': 'right'}))
            sheet.write(row_index, 1, row.get('address_name', '0'),
                        workbook.add_format({'align': 'left'}))  # Align address name to left
            sheet.write_number(row_index, 2, float(row.get('pre_month_residual', '0') or 0), number_format)
            sheet.write_number(row_index, 3, float(row.get('current_invoiced', '0') or 0), number_format)
            sheet.write_number(row_index, 4, float(row.get('advance_payment_amount', '0') or 0), number_format)
            sheet.write_number(row_index, 5, float(row.get('uo_payment_amount', '0') or 0), number_format)
            sheet.write_number(row_index, 6, float(row.get('c1_payment_amount', '0') or 0), number_format)
            sheet.write_number(row_index, 7, float(row.get('tz_payment_amount', '0') or 0), number_format)
            sheet.write_number(row_index, 8, float(row.get('paid_amount', '0') or 0), number_format)
            sheet.write_number(row_index, 9, float(row.get('last_residual', '0') or 0), number_format)
            row_index += 1

        # Summary Row (Total)
        totals_format = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'align': 'right'})
        sheet.merge_range(row_index, 0, row_index, 1, 'Нийт', totals_format)
        sheet.write(row_index, 2, sum([float(row.get('pre_month_residual', '0') or 0) for row in report_data]),
                    number_format)
        sheet.write(row_index, 3, sum([float(row.get('current_invoiced', '0') or 0) for row in report_data]),
                    number_format)
        sheet.write(row_index, 4, sum([float(row.get('advance_payment_amount', '0') or 0) for row in report_data]),
                    number_format)
        sheet.write(row_index, 5, sum([float(row.get('uo_payment_amount', '0') or 0) for row in report_data]),
                    number_format)
        sheet.write(row_index, 6, sum([float(row.get('c1_payment_amount', '0') or 0) for row in report_data]),
                    number_format)
        sheet.write(row_index, 7, sum([float(row.get('tz_payment_amount', '0') or 0) for row in report_data]),
                    number_format)
        sheet.write(row_index, 8, sum([float(row.get('paid_amount', '0') or 0) for row in report_data]), number_format)
        sheet.write(row_index, 9, sum([float(row.get('last_residual', '0') or 0) for row in report_data]),
                    number_format)

        workbook.close()
        xls_content.seek(0)
        xlsx_data = base64.b64encode(xls_content.read()).decode('utf-8')

        return {
            'type': 'ir.actions.act_url',
            'url': f'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{xlsx_data}',
            'target': 'new',
            'nodestroy': True,
        }

    def _setup_xls_headers(self, sheet, workbook):
        # Define header formatting
        header_format = workbook.add_format(
            {'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': 1})

        # Define the static headers as per your template
        static_headers = [
            ('Хэрэглэгчийн', 2),  # User related (split into 2 columns later)
            'Эхний үлдэгдэл',  # Previous residual
            'Төлбөл зохих',  # Due amount
            'Нийт төлөх',  # Total to pay
            'УОО-с төлсөн',  # Paid by UOO
            'С1-ээс төлсөн',  # Paid by C1
            'ТЗ-оос төлсөн',  # Paid by TZ
            'Нийт төлсөн',  # Total paid
            'Эцсийн үлдэгдэл'  # Final residual
        ]

        # Write the first header row
        col = 0
        for header in static_headers:
            if isinstance(header, tuple):
                sheet.merge_range(1, col, 1, col + header[1] - 1, header[0], header_format)
                col += header[1]
            else:
                sheet.write(1, col, header, header_format)
                col += 1

        # Write the second header row (for "Код" and "Байцаагч")
        sheet.write(2, 0, 'Код', header_format)  # Address code
        sheet.write(2, 1, 'Байцаагч', header_format)  # Inspector name

        # Set column widths for better appearance
        column_widths = [15, 20] + [18] * 8
        for i, width in enumerate(column_widths):
            sheet.set_column(i, i, width)

        # Optional: Freeze the header rows for scrolling
        sheet.freeze_panes(3, 0)

    def get_company_name(self, company_id):
        """Retrieve the company name based on company ID."""
        company = self.env['res.company'].browse(company_id)
        return company.name if company else ''

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
