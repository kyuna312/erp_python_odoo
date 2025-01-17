from odoo import models, fields
from odoo.addons.base.models.ir_model import quote
from odoo.exceptions import UserError
import base64
import calendar
from datetime import datetime
from dateutil.relativedelta import relativedelta


class PayUooPDFReportWizard(models.TransientModel):
    _name = 'pay.uoo.pdf.report.wizard'
    _description = 'Pay UOO PDF Report Wizard'

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

    def _get_uoo_results(self, year, month):
        """Retrieve UOO results by inspector"""
        last_day = calendar.monthrange(year, int(month))[1]
        last_date = datetime(year, int(month), last_day).strftime('%Y-%m-%d')
        previous_date = datetime(year, int(month), 1).strftime('%Y-%m-%d')
        company_id = self.company_id.id
        report_year = int(self.uoo_year)
        report_month = int(self.uoo_month)

        # Correctly format income date for the following month
        income_date = datetime(year, int(month), 1) + relativedelta(months=1)
        income_year = income_date.year
        income_month = income_date.month
        income_last_day = calendar.monthrange(income_year, income_month)[1]
        address_type = self.address_type
        period_id = self.env['pay.period'].sudo().search(
            [('company_id', '=', company_id), ('year', '=', str(report_year)),
             ('month', '=', str(report_month).zfill(2)), ('address_type', '=', address_type)], limit=1)
        if not period_id or period_id.state == 'opened':
            query = f"""
            SELECT
                inspector AS inspector_id,
                inspector_name,
                SUM(prev_balance) AS total_prev_balance,
                SUM(reconciled_current_invoice_amount) AS total_reconciled_current_invoice_amount,
                SUM(current_balance) AS total_current_balance,
                SUM(last_balance) AS total_last_balance
            FROM (
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
                AND ROUND(CAST(COALESCE(prev_paid.amount, 0.0) - COALESCE(reconciled_prev_paid.amount, 0.0) AS numeric), 2) + ROUND(CAST(COALESCE(reconciled_current_invoice.amount, 0.0) AS numeric), 2) +ROUND(CAST(COALESCE(payment_current_month.amount, 0.0) - COALESCE(reconciled_payment_current_month.amount, 0.0) AS numeric), 2) + ROUND(CAST(COALESCE(last_payment.amount, 0.0) - COALESCE(last_payment_reconciled.amount, 0.0) AS numeric), 2) != 0.0
                order by inspector.id
            ) subquery
            GROUP BY inspector, inspector_name
            ORDER BY inspector;
        """
        elif not period_id or period_id.state == 'closed':
            query = f"""
                SELECT
                    inspector AS inspector_id,
                    inspector_name,
                    SUM(prev_balance) AS total_prev_balance,
                    SUM(reconciled_current_invoice_amount) AS total_reconciled_current_invoice_amount,
                    SUM(current_balance) AS total_current_balance,
                    SUM(last_balance) AS total_last_balance
                FROM (
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
                    AND ROUND(CAST(COALESCE(prev_paid.amount, 0.0) - COALESCE(reconciled_prev_paid.amount, 0.0) AS numeric), 2) + ROUND(CAST(COALESCE(reconciled_current_invoice.amount, 0.0) AS numeric), 2) +ROUND(CAST(COALESCE(payment_current_month.amount, 0.0) - COALESCE(reconciled_payment_current_month.amount, 0.0) AS numeric), 2) + ROUND(CAST(COALESCE(last_payment.amount, 0.0) - COALESCE(last_payment_reconciled.amount, 0.0) AS numeric), 2) != 0.0
                    order by inspector.id
                ) subquery
                GROUP BY inspector, inspector_name
                ORDER BY inspector;
            """
        self.env.cr.execute(query.format(
            company_id=company_id,
            income_year=income_year,
            income_month=income_month,
            income_last_day=income_last_day,
            report_year=report_year,
            report_month=report_month,
            address_type=address_type,
        ))
        data = self.env.cr.dictfetchall()
        return data

    def download_pdf(self):
        report_action = self.env.ref('ub_kontor.action_pay_uoo', raise_if_not_found=False)
        if not report_action:
            raise UserError('The report action is not defined.')

        logo_data_uri = self.image_data_uri(self.company_id.logo)

        data = {
            'uoo_year': self.uoo_year,
            'uoo_month': self.uoo_month,
            'current_date': self.current_date,
            'company_id': self.company_id.id,
            'company_name': self.company_id.name,
            'address_type': self.get_address_type_display(self.address_type),
            'logo_data_uri': logo_data_uri,
            'uoo_results': self._get_uoo_results(self.uoo_year, int(self.uoo_month)),
        }

        return report_action.report_action(self, data=data)

    def get_address_type_display(self, address_type):
        """Return the display value for the address type."""
        field = self.env['pay.receipt.pdf.report.wizard']._fields['address_type']
        return dict(field.selection).get(address_type, '')

    def image_data_uri(self, logo):
        """Convert the company logo to a data URI."""
        if logo:
            return f'data:image/png;base64,{logo.decode()}'
        return ''
