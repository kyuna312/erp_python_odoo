import base64
from datetime import datetime
from odoo import models, fields, api
from odoo.exceptions import UserError


class PaymentDetailsPdfReportWizard(models.TransientModel):
    _name = 'payment.details.pdf.report.wizard'
    _description = 'Төлбөрийн дэлгэрэнгүй тайлан'

    company_id = fields.Many2one('res.company', 'ХҮТ', default=lambda self: self.env.user.company_id.id)

    year = fields.Selection(
        [(str(year), str(year)) for year in range(datetime.now().year, 2018, -1)],
        string="Он", required=True
    )
    month = fields.Selection(
        [(str(i).zfill(2), f'{i}-р сар') for i in range(1, 13)],
        string='Сар', required=True
    )

    apartment_ids = fields.Many2many(
        'ref.apartment',
        string='Байр',
        required=True,
        domain="[('company_id', '=', company_id)]"
    )
    # address_ids = fields.Many2many(
    #     'ref.address',
    #     string='Тоот',
    #     domain="[('apartment_id', 'in', apartment_ids), ('company_id', '=', company_id)]"
    # )
    address_id = fields.Many2one('ref.address', 'Тоот', domain="[('apartment_id', 'in', apartment_ids), ('company_id', '=', company_id)]", required=True)

    def prepare_data(self):
        """Prepare the data required for generating the report."""
        if not self.address_id:
            raise UserError("At least one address must be selected.")

        selected_month_first_day = datetime(int(self.year), int(self.month), 1)
        query = """
            SELECT
              apartment.code AS apartment_code,
              address.address AS address_address,
              invoice.year AS year,
              invoice.month AS month,
              ROUND(CAST(COALESCE(pre_invoiced.amount, 0.0) - COALESCE(pre_paid.amount, 0.0) AS numeric), 2) AS first_balance,
              COALESCE(invoice.amount_total, 0.0) AS invoiced_amount,
              COALESCE(SUM(payment.amount), 0.0) AS paid_amount,
              ROUND(CAST(COALESCE(last_invoiced.amount, 0.0) - COALESCE(last_paid.amount, 0.0) AS numeric), 2) AS last_balance
          FROM pay_receipt_address_invoice invoice
          INNER JOIN ref_address address ON address.id = invoice.address_id
          INNER JOIN ref_apartment apartment ON apartment.id = address.apartment_id
          LEFT JOIN pay_address_payment payment ON payment.address_id = invoice.address_id 
              AND EXTRACT(YEAR FROM payment.date - INTERVAL '1 months')::INTEGER = invoice.year::INTEGER 
              AND EXTRACT(MONTH FROM payment.date - INTERVAL '1 months')::INTEGER = invoice.month::INTEGER
          CROSS JOIN LATERAL (
              SELECT SUM(prai.amount_total) AS amount 
              FROM pay_receipt_address_invoice prai 
              WHERE prai.address_id = address.id 
                  AND CONCAT(prai.year, '-', prai.month, '-', '01')::DATE < CONCAT(invoice.year, '-', invoice.month, '-', '01')::DATE
          ) pre_invoiced
          CROSS JOIN LATERAL (
              SELECT SUM(pap.amount) AS amount 
              FROM pay_address_payment pap 
              WHERE pap.address_id = address.id 
                  AND pap.date < CONCAT(invoice.year, '-', invoice.month, '-', '01')::DATE+ INTERVAL '1 months'
          ) pre_paid
          CROSS JOIN LATERAL (
              SELECT SUM(prai.amount_total) AS amount 
              FROM pay_receipt_address_invoice prai 
              WHERE prai.address_id = address.id 
                  AND CONCAT(prai.year, '-', prai.month, '-', '01')::DATE <= CONCAT(invoice.year, '-', invoice.month, '-', '01')::DATE
          ) last_invoiced
          CROSS JOIN LATERAL (
              SELECT SUM(pap.amount) AS amount 
              FROM pay_address_payment pap 
              WHERE pap.address_id = address.id 
                  AND pap.date < CONCAT(invoice.year, '-', invoice.month, '-', '01')::DATE + INTERVAL '2 months'
          ) last_paid
          WHERE invoice.address_id = {address_id} and concat(invoice.year, '-',invoice.month, '-01')::date <= '{first_day}'
          GROUP BY invoice.id, apartment.id, address.id, pre_invoiced.amount, pre_paid.amount, last_invoiced.amount, last_paid.amount
          ORDER BY CONCAT(invoice.year, '-', invoice.month, '-', '01')::DATE ASC
        """.format(address_id=self.address_id.id, first_day=selected_month_first_day )
        print(query)
        self.env.cr.execute(query)
        prepared_data = self.env.cr.dictfetchall()
        invoice_residual = self.address_id.invoice_residual
        payment_residual = self.address_id.payment_residual


        address_type = self.env.user.access_type
        company_name = self.company_id.name

        return {
            'address_type': address_type,
            'company_name': company_name,
            'image_data_uri': self._image_data_uri(self.company_id.logo),  # Ensure to get the logo here
            'year': self.year,
            'month': self.month,
            'prepared_data': prepared_data,
            'invoice_residual': invoice_residual or 0.0,
            'payment_residual': payment_residual or 0.0
        }

    def download(self):
        """Trigger PDF report download."""
        report_action = self.env.ref('ub_kontor.action_payment_details_pdf_report', raise_if_not_found=False)
        if not report_action:
            raise UserError('Report not found. Please check the report action configuration.')
        return report_action.report_action(self)

    def _image_data_uri(self, image: bytes) -> str:
        return f'data:image/png;base64,{base64.b64encode(image).decode()}' if image else ''


class PaymentDetailsPdfReport(models.AbstractModel):
    _name = 'report.ub_kontor.payment_details_pdf_report_template'
    _description = 'Төлбөрийн дэлгэрэнгүй тайлан'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Provide data to the report template."""
        wizard = self.env['payment.details.pdf.report.wizard'].browse(docids)
        prepared_data = wizard.prepare_data()

        print('prepared_data', prepared_data['prepared_data'])

        return {
            'doc_ids': docids,
            'doc_model': 'payment.details.pdf.report.wizard',
            'data': prepared_data,  # Ensure this is a dictionary
            'docs': wizard,
            'company_name': prepared_data['company_name'],
            'year': prepared_data['year'],
            'month': prepared_data['month'],
            'address_type': 'Орон сууц' if prepared_data['address_type'] == 'OS' else 'Аж ахуй нэгж',
            'prepare_data': prepared_data['prepared_data'],  # This should be the list of dictionaries
            'image_data_uri': prepared_data['image_data_uri'],  # Ensure to pass the correct key here
            'invoice_residual': prepared_data['invoice_residual'],
            'payment_residual': prepared_data['payment_residual']
        }
