import io

from odoo import models, fields, api
from odoo.exceptions import UserError
import base64
import calendar
from datetime import datetime
from dateutil.relativedelta import relativedelta
import xlsxwriter


class PayUooDetailPDFReportWizard(models.TransientModel):
    _name = 'pay.uoo.detail.pdf.report.wizard'
    _description = 'Pay UOO Detail PDF Report Wizard'

    company_id = fields.Many2one(
        'res.company',
        string='ХҮТ',
        index=True,
        default=lambda self: self.env.user.company_id,
    )

    address_type = fields.Selection(
        [('OS', 'ОС'), ('AAN', 'ААН')],
        string='Тоотын төрөл',
        required=True,
        default=lambda self: self.env.user.access_type,
    )

    uoo_year = fields.Integer(
        string='УУО он',
        required=True,
        default=lambda self: fields.Date.today().year,
    )

    uoo_month = fields.Selection(
        [(str(i), f'{i} сар') for i in range(1, 13)],
        string='УУО сар',
        required=True,
        default=lambda self: str(fields.Date.today().month),
    )

    current_date = fields.Date(
        string='Одоогийн огноо',
        default=fields.Date.today
    )

    def _image_data_uri(self, logo):
        """Convert the company logo to a data URI."""
        if logo:
            return f'data:image/png;base64,{logo.decode()}'
        return ''

    def _get_uoo_results(self, year, month):
        last_day = calendar.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day).strftime('%Y-%m-%d')
        previous_date = datetime(year, month, 1).strftime('%Y-%m-%d')
        company_id = self.company_id.id
        report_year = int(self.uoo_year)
        report_month = int(self.uoo_month)
        income_date = datetime.strptime(f'{report_year}-{report_month}-01', '%Y-%m-%d').date() + relativedelta(months=1)
        income_year = income_date.year
        income_month = income_date.month
        income_last_day = calendar.monthrange(income_year, income_month)[1]
        address_type = self.address_type
        period_id = self.env['pay.period'].sudo().search([('company_id', '=', company_id), ('year', '=', str(report_year)), ('month', '=', str(report_month).zfill(2)), ('address_type', '=', address_type)], limit=1)
        query = ""
        if period_id.state == 'opened':
            query = f"""
                SELECT
                address.code AS address_code,
                CONCAT( apartment.code, '-', address.address) AS address_address,
                address.name AS user_name,
                ROUND(cast(COALESCE(prev_paid.amount, 0.0) - COALESCE(reconciled_prev_paid.amount, 0.0) as numeric),2) AS prev_balance,
                ROUND(cast(COALESCE(reconciled_current_invoice.amount, 0.0) as numeric),2) AS reconciled_current_invoice_amount,
                ROUND(cast(COALESCE(payment_current_month.amount, 0.0) - COALESCE(reconciled_payment_current_month.amount, 0.0) as numeric),2) AS current_balance,
                ROUND(cast(COALESCE(last_payment.amount, 0.0) - COALESCE(last_payment_reconciled.amount, 0.0) as numeric),2) AS last_balance,
                inspector.id AS inspector,
                inspector.name AS inspector_name
                FROM
                ref_address address
                INNER JOIN
                ref_apartment apartment ON apartment.id = address.apartment_id
                LEFT JOIN (
                SELECT
                    SUM(payment.amount) AS amount,
                    payment.address_id
                    FROM pay_address_payment payment
                    INNER JOIN
                    pay_bank_account account ON account.id = payment.account_id
                    WHERE
                    account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date < '{income_year}-{income_month}-01'
                    GROUP BY payment.address_id
                ) prev_paid ON prev_paid.address_id = address.id
                LEFT JOIN (
                    SELECT
                    payment.address_id AS address_id,
                    SUM(payment_line.amount) AS amount
                    FROM
                    pay_address_payment_line payment_line
                    INNER JOIN
                    pay_address_payment payment ON payment.id = payment_line.payment_id
                    INNER JOIN
                    pay_bank_account account ON account.id = payment.account_id
                    WHERE   
                    account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date < '{income_year}-{income_month}-01'
                    AND payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date < '{report_year}-{report_month}-01'::date and company_id = {company_id} and pp.address_type = '{address_type}')
                    GROUP BY
                    payment.address_id
                ) reconciled_prev_paid ON reconciled_prev_paid.address_id = address.id
                LEFT JOIN (
                    SELECT
                    payment.address_id AS address_id,
                    SUM(payment_line.amount) AS amount
                    FROM
                    pay_address_payment payment
                    INNER JOIN
                    pay_bank_account account ON account.id = payment.account_id
                    INNER JOIN
                    pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
                    INNER JOIN
                    pay_receipt_address_invoice invoice ON invoice.id = payment_line.invoice_id and invoice.year::integer = {report_year} AND invoice.month::integer = {report_month}
                    WHERE
                    account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date < '{income_year}-{income_month}-01'
                    AND payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date <= '{report_year}-{report_month}-01'::date and company_id = {company_id} and pp.address_type = '{address_type}')
                    GROUP BY
                    payment.address_id
                ) reconciled_current_invoice ON reconciled_current_invoice.address_id = address.id
                LEFT JOIN (
                    SELECT
                    payment.address_id, SUM(payment.amount) AS amount
                    FROM pay_address_payment payment
                    INNER JOIN pay_bank_account account ON account.id = payment.account_id
                    WHERE account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND EXTRACT(YEAR FROM payment.date) = {income_year}
                    AND EXTRACT(MONTH FROM payment.date) = {income_month}
                    GROUP BY
                    payment.address_id
                ) payment_current_month ON payment_current_month.address_id = address.id
                LEFT JOIN (
                    SELECT 
                    payment.address_id AS address_id, -- This comma is necessary and correct
                        SUM(payment.amount) AS amount
                    FROM 
                        pay_address_payment payment
                    INNER JOIN 
                        pay_bank_account account ON account.id = payment.account_id
                    WHERE 
                        account.type = 'incoming'
                        AND account.company_id = {company_id}
                        AND payment.date <= '{income_year}-{income_month}-{income_last_day}'
                    GROUP BY 
                        payment.address_id
                ) last_payment ON last_payment.address_id = address.id
                LEFT JOIN (
                    SELECT payment.address_id, SUM(payment_line.amount) AS amount
                    FROM pay_address_payment payment
                    INNER JOIN pay_bank_account account ON account.id = payment.account_id
                    INNER JOIN pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
                    WHERE account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date <= '{income_year}-{income_month}-{income_last_day}'
                    AND payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date <= '{report_year}-{report_month}-01'::date and company_id = {company_id} and pp.address_type = '{address_type}')
                    GROUP BY payment.address_id
                ) last_payment_reconciled ON last_payment_reconciled.address_id = address.id
                LEFT JOIN (
                    SELECT payment.address_id, SUM(payment_line.amount) AS amount
                    FROM pay_address_payment payment
                    INNER JOIN pay_bank_account account ON account.id = payment.account_id
                    INNER JOIN pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
                    WHERE account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND EXTRACT(YEAR FROM payment.date) = {income_year}
                    AND EXTRACT(MONTH FROM payment.date) = {income_month}
                    GROUP BY
                    payment.address_id
                ) reconciled_payment_current_month ON reconciled_payment_current_month.address_id = address.id
                INNER JOIN
                hr_employee inspector ON inspector.id = address.inspector_id
                WHERE
                address.type = '{address_type}'
                AND address.company_id = {company_id}
                AND ROUND(CAST(COALESCE(prev_paid.amount, 0.0) - COALESCE(reconciled_prev_paid.amount, 0.0) AS numeric), 2) + ROUND(CAST(COALESCE(last_payment.amount, 0.0) - COALESCE(last_payment_reconciled.amount, 0.0) AS numeric), 2) != 0.0
                order by inspector.id
            """
        elif period_id.state == 'closed':
            query = f"""
                SELECT
                address.code AS address_code,
                CONCAT( apartment.code, '-', address.address) AS address_address,
                address.name AS user_name,
                ROUND(cast(COALESCE(prev_paid.amount, 0.0) - COALESCE(reconciled_prev_paid.amount, 0.0) as numeric),2) AS prev_balance,
                ROUND(cast(COALESCE(reconciled_current_invoice.amount, 0.0) as numeric),2) AS reconciled_current_invoice_amount,
                ROUND(cast(COALESCE(payment_current_month.amount, 0.0) - COALESCE(reconciled_payment_current_month.amount, 0.0) as numeric),2) AS current_balance,
                ROUND(cast(COALESCE(last_payment.amount, 0.0) - COALESCE(last_payment_reconciled.amount, 0.0) as numeric),2) AS last_balance,
                inspector.id AS inspector,
                inspector.name AS inspector_name
                FROM
                ref_address address
                INNER JOIN
                ref_apartment apartment ON apartment.id = address.apartment_id
                LEFT JOIN (
                SELECT
                    SUM(payment.amount) AS amount,
                    payment.address_id
                    FROM pay_address_payment payment
                    INNER JOIN
                    pay_bank_account account ON account.id = payment.account_id
                    WHERE
                    account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date < '{income_year}-{income_month}-01'
                    GROUP BY payment.address_id
                ) prev_paid ON prev_paid.address_id = address.id
                LEFT JOIN (
                    SELECT
                    payment.address_id AS address_id,
                    SUM(payment_line.amount) AS amount
                    FROM
                    pay_address_payment_line payment_line
                    INNER JOIN
                    pay_address_payment payment ON payment.id = payment_line.payment_id
                    INNER JOIN
                    pay_bank_account account ON account.id = payment.account_id
                    WHERE   
                    account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date < '{income_year}-{income_month}-01'
                    AND payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date < '{report_year}-{report_month}-01'::date and company_id = {company_id} and pp.address_type = '{address_type}')
                    GROUP BY
                    payment.address_id
                ) reconciled_prev_paid ON reconciled_prev_paid.address_id = address.id
                LEFT JOIN (
                    SELECT
                    payment.address_id AS address_id,
                    SUM(payment_line.amount) AS amount
                    FROM
                    pay_address_payment payment
                    INNER JOIN
                    pay_bank_account account ON account.id = payment.account_id
                    INNER JOIN
                    pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
                    INNER JOIN
                    pay_receipt_address_invoice invoice ON invoice.id = payment_line.invoice_id and invoice.year::integer = {report_year} AND invoice.month::integer = {report_month}
                    WHERE
                    account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date < '{income_year}-{income_month}-01'
                    AND payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date <= '{report_year}-{report_month}-01'::date and company_id = {company_id} and pp.address_type = '{address_type}')
                    GROUP BY
                    payment.address_id
                ) reconciled_current_invoice ON reconciled_current_invoice.address_id = address.id
                LEFT JOIN (
                    SELECT
                    payment.address_id, SUM(payment.amount) AS amount
                    FROM pay_address_payment payment
                    INNER JOIN pay_bank_account account ON account.id = payment.account_id
                    WHERE account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND EXTRACT(YEAR FROM payment.date) = {income_year}
                    AND EXTRACT(MONTH FROM payment.date) = {income_month}
                    GROUP BY
                    payment.address_id
                ) payment_current_month ON payment_current_month.address_id = address.id
                LEFT JOIN (
                    SELECT 
                    payment.address_id AS address_id, -- This comma is necessary and correct
                        SUM(payment.amount) AS amount
                    FROM 
                        pay_address_payment payment
                    INNER JOIN 
                        pay_bank_account account ON account.id = payment.account_id
                    WHERE 
                        account.type = 'incoming'
                        AND account.company_id = {company_id}
                        AND payment.date <= '{income_year}-{income_month}-{income_last_day}'
                    GROUP BY 
                        payment.address_id
                ) last_payment ON last_payment.address_id = address.id
                LEFT JOIN (
                    SELECT payment.address_id, SUM(payment_line.amount) AS amount
                    FROM pay_address_payment payment
                    INNER JOIN pay_bank_account account ON account.id = payment.account_id
                    INNER JOIN pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
                    WHERE account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND payment.date <= '{income_year}-{income_month}-{income_last_day}'
                    AND payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date <= '{report_year}-{report_month}-01'::date and company_id = {company_id} and pp.address_type = '{address_type}')
                    GROUP BY payment.address_id
                ) last_payment_reconciled ON last_payment_reconciled.address_id = address.id
                LEFT JOIN (
                    SELECT payment.address_id, SUM(payment_line.amount) AS amount
                    FROM pay_address_payment payment
                    INNER JOIN pay_bank_account account ON account.id = payment.account_id
                    INNER JOIN pay_address_payment_line payment_line ON payment_line.payment_id = payment.id
                    WHERE account.type = 'incoming'
                    AND account.company_id = {company_id}
                    AND EXTRACT(YEAR FROM payment.date) = {income_year}
                    AND EXTRACT(MONTH FROM payment.date) = {income_month}
                    GROUP BY
                    payment.address_id
                ) reconciled_payment_current_month ON reconciled_payment_current_month.address_id = address.id
                inner join pay_period_report report on report.period_id = {period_id.id} and report.address_id = address.id
                INNER JOIN hr_employee inspector ON inspector.id = report.inspector_id
                WHERE
                address.type = '{address_type}'
                AND address.company_id = {company_id}
                AND ROUND(CAST(COALESCE(prev_paid.amount, 0.0) - COALESCE(reconciled_prev_paid.amount, 0.0) AS numeric), 2) + ROUND(CAST(COALESCE(last_payment.amount, 0.0) - COALESCE(last_payment_reconciled.amount, 0.0) AS numeric), 2) != 0.0
                order by inspector.id
            """
        self.env.cr.execute(query)
        data = self.env.cr.dictfetchall()
        return data

    def download_pdf(self):
        report_action = self.env.ref('ub_kontor.action_pay_uoo_detail', raise_if_not_found=False)
        if not report_action:
            raise UserError('The report action is not defined.')

        data = {
            'company_name': self.company_id.name,
            'uoo_year': self.uoo_year,
            'uoo_month': self.uoo_month,
            'current_date': self.current_date,
            'company_id': self.company_id.id,
            'address_type': self.get_address_type_display(self.address_type),
            'logo_data_uri': self._image_data_uri(self.company_id.logo),
            'uoo_results': self._get_uoo_results(self.uoo_year, int(self.uoo_month)),
        }

        return report_action.report_action(self, data=data)

    def _write_xls_data(self, sheet, data, workbook):
        """Helper function to write the UOO results into the sheet."""
        row = 1
        prev_inspector = None

        # Initialize formats once
        normal_format = workbook.add_format({'align': 'right', 'border': 1})
        inspector_row_format = workbook.add_format({'bold': True, 'bg_color': '#F5F5F5', 'border': 1})

        # Initialize totals for inspector
        inspector_totals = {
            'prev_balance': 0,
            'reconciled_current_invoice_amount': 0,
            'current_balance': 0,
            'last_balance': 0
        }

        for record in data:
            inspector = record['inspector_name']

            # Handle inspector change
            if inspector != prev_inspector:
                if prev_inspector is not None:
                    # Write inspector totals before switching inspectors
                    sheet.write_row(row, 0, [
                        f"Нийт (Байцаагч: {prev_inspector})",
                        '', '', '',  # Empty cells to match header structure
                        inspector_totals['prev_balance'],
                        inspector_totals['reconciled_current_invoice_amount'],
                        inspector_totals['current_balance'],
                        inspector_totals['last_balance']
                    ], inspector_row_format)
                    row += 1

                # Reset totals for the new inspector
                inspector_totals = {key: 0 for key in inspector_totals}

                # Write inspector name row
                sheet.write(row, 0, f"Байцаагч: {inspector}", inspector_row_format)
                row += 1

            # Write individual record row
            sheet.write(row, 0, record['address_code'])  # Address code
            sheet.write(row, 1, record['address_address'])  # Address
            sheet.write(row, 2, record['user_name'])  # User name
            sheet.write(row, 3, record['inspector_name'])  # Inspector name
            sheet.write(row, 4, record['prev_balance'], normal_format)  # Previous balance
            sheet.write(row, 5, record['reconciled_current_invoice_amount'], normal_format)  # Reconciled amount
            sheet.write(row, 6, record['current_balance'], normal_format)  # Current balance
            sheet.write(row, 7, record['last_balance'], normal_format)  # Last balance

            # Accumulate totals for inspector
            inspector_totals['prev_balance'] += record['prev_balance']
            inspector_totals['reconciled_current_invoice_amount'] += record['reconciled_current_invoice_amount']
            inspector_totals['current_balance'] += record['current_balance']
            inspector_totals['last_balance'] += record['last_balance']

            prev_inspector = inspector
            row += 1

        # Handle the final inspector's totals
        if prev_inspector:
            sheet.write_row(row, 0, [
                f"Нийт (Байцаагч: {prev_inspector})",
                '', '', '',  # Empty cells to match header structure
                inspector_totals['prev_balance'],
                inspector_totals['reconciled_current_invoice_amount'],
                inspector_totals['current_balance'],
                inspector_totals['last_balance']
            ], inspector_row_format)

    def import_xls(self):
        """Generate XLSX file with UOO results."""
        uoo_results = self._get_uoo_results(self.uoo_year, int(self.uoo_month))

        # Create a new workbook and add a worksheet
        xls_content = io.BytesIO()
        workbook = xlsxwriter.Workbook(xls_content, {'in_memory': True})
        sheet = workbook.add_worksheet()

        # Define headers matching the QWeb template
        headers = [
            'Код', 'Байр, тоот', 'Хэрэглэгчийн нэр',
            'Байцаагчийн нэр', 'Эхний үлдэгдэл',
            'Тухайн сарын төлбөл зохихоос хаагдсан',
            'Тухайн сарын УОО', 'Эцсийн үлдэгдэл'
        ]
        header_format = workbook.add_format({
            'bold': True, 'align': 'center', 'border': 1, 'fg_color': '#F5F5F5'
        })

        # Write headers
        sheet.write_row(0, 0, headers, header_format)

        # Write UOO data using the helper function
        self._write_xls_data(sheet, uoo_results, workbook)

        # Finalize and close the workbook
        workbook.close()

        # Convert XLS content to base64 and return as a downloadable link
        xlsx_data = base64.b64encode(xls_content.getvalue()).decode('utf-8')
        xls_content.close()

        # Return as a downloadable link
        return {
            'type': 'ir.actions.act_url',
            'url': f'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{xlsx_data}',
            'target': 'new',
            'nodestroy': True,
        }

    def format_currency(self, amount: float) -> str:
        return f"{self.env.company.currency_id.symbol} {amount:.2f}"

    def get_formatted_current_date(self):
        return self.current_date.strftime('%d/%m/%Y') if self.current_date else 'N/A'

    def get_address_type_display(self, address_type):
        """Return the display value for the address type."""
        field = self.env['pay.receipt.pdf.report.wizard']._fields['address_type']
        return dict(field.selection).get(address_type, '')