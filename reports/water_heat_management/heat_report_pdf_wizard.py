from collections import defaultdict
from itertools import groupby
from odoo import models, fields, api
from odoo.exceptions import UserError


class HeatReportPdfWizard(models.TransientModel):
    _name = 'heat.report.pdf.wizard'
    _description = 'Heat Report Pdf Wizard'

    company_id = fields.Many2one('res.company', string='ХҮТ', default=lambda self: self.env.user.company_id.id)
    address_type = fields.Selection([('OS', 'ОС'), ('AAN', 'ААН')], string='Address Type', required=True,
                                    default=lambda self: self.env.user.access_type)
    heat_report_date = fields.Selection(selection='_get_heat_report_date_selection', string='Хугацаа сонгох',
                                        required=True)
    heat_report_year = fields.Char(string='Heat Report Year', compute='_compute_heat_report_year')
    date = fields.Date(string='Хугацаа сонгох', default=fields.Date.today)

    @api.depends('heat_report_date')
    def _compute_heat_report_year(self):
        for record in self:
            if record.heat_report_date:
                year, month = record.heat_report_date.split('/')
                record.heat_report_year = f"{year} Year {month}"

    @api.model
    def _get_heat_report_date_selection(self):
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

    def _get_uom_headers(self, results):
        headers = set()
        for item in results:
            headers.add(item['pricelist_name'])  # Use 'uom_name' as the header
        return sorted(headers)  # Ensure the headers are sorted

    def _get_heat_report(self, heat_report_date):
        if not heat_report_date:
            raise UserError("No Residual Date provided.")

        year, month = map(int, heat_report_date.split('/'))
        results = self._fetch_heat_report_data(self.address_type, self.company_id.id, year, month)
        uom_headers = self._get_uom_headers(results)  # Extract headers from results

        grouped_data = defaultdict(lambda: {'uom_data': {}, 'apartment_code': ''})
        for item in results:
            apartment_id = item['apartment_id']
            grouped_data[apartment_id]['apartment_code'] = item['apartment_code']
            grouped_data[apartment_id]['uom_data'][item['pricelist_name']] = item['total_price']

        # Ensure all uom_headers exist for each apartment_id
        for apartment_id, data in grouped_data.items():
            for header in uom_headers:
                if header not in data['uom_data']:
                    data['uom_data'][header] = 0

        return grouped_data, self.address_type, self.get_company_name(
            self.company_id.id), heat_report_date, self.image_data_uri(self.company_id.logo), uom_headers

    def _fetch_heat_report_data(self, address_type, company_id, year, month):
        query = f"""
            select 
                apartment.id as apartment_id, apartment.code as apartment_code, pricelist.uom_id as uom_id, uu.name as uom_name, 
                pricelist.price as price, round(cast(sum(address_line.total_amount) as numeric), 2) as total_price, 
                pricelist.id as pricelist_id, concat(service_type.name, ' ', pricelist.name) as pricelist_name
            from pay_receipt reciept
            inner join pay_receipt_address receipt_address on receipt_address.receipt_id = reciept.id 
                and reciept.company_id = {company_id} and reciept.address_type = '{address_type}' 
                and reciept.year::integer = {year} and reciept.month::integer = {month}
            inner join pay_receipt_address_line address_line on address_line.receipt_address_id = receipt_address.id
            inner join ref_pricelist pricelist on pricelist.id = address_line.pricelist_id and pricelist.report_type = 'heating'
            inner join uom_uom uu on uu.id = pricelist.uom_id 
            inner join ref_service_type service_type on service_type.id = pricelist.service_type_id 
            inner join ref_address address on address.id = receipt_address.address_id 
            inner join ref_apartment apartment on apartment.id = address.apartment_id 
            group by apartment.id, pricelist.id, uu.id, service_type.id
            order by pricelist.id, apartment.id;
        """
        return self._execute_query(query)

    def download(self):
        grouped_data, address_type, company_name, date, logo_data_uri, uom_headers = self._get_heat_report(
            self.heat_report_date)
        report_action = self.env.ref('ub_kontor.action_heat_report_pdf', raise_if_not_found=False)

        return report_action.report_action(
            self,
            data={
                'grouped_data': grouped_data,
                'company_id': self.company_id.id,
                'address_type': self.get_address_type_display(self.address_type),
                'uom_headers': uom_headers,
                'company_name': company_name,
                'heat_report_date': self.heat_report_date,
                'report_date': date,
                'logo_data_uri': logo_data_uri,
                'user_balance_list_date': self.heat_report_date
            }
        )

    def image_data_uri(self, logo):
        return f'data:image/png;base64,{logo.decode()}' if logo else ''

    def get_company_name(self, company_id):
        company = self.env['res.company'].browse(company_id)
        return company.name if company else 'Unknown Company'

    def get_address_type_display(self, address_type):
        return dict(self._fields['address_type'].selection).get(address_type, '')
