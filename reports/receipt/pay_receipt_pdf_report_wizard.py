from odoo import models, fields, api
from odoo.exceptions import UserError
from itertools import groupby
from datetime import datetime, timedelta


class PayReceiptPdfReportWizard(models.TransientModel):
    _name = 'pay.receipt.pdf.report.wizard'
    _description = 'Payment Receipt Report Wizard'

    pay_receipt_id = fields.Many2one('pay.receipt', 'Баримтийн хугацаа сонгох', required=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', index=True, default=lambda self: self.env.user.company_id.id)
    address_type = fields.Selection(
        [('OS', 'ОС'), ('AAN', 'ААН')],
        string='Тоотын төрөл',
        required=True,
        default=lambda self: self.env.user.access_type
    )
    date = fields.Date(string='Date', default=fields.Date.today)

    def download_pdf(self):
        if not self.pay_receipt_id:
            raise UserError("The pay receipt record does not exist or has been deleted.")

        report_action = self.env.ref('ub_kontor.action_pay_receipt_pdf_report', raise_if_not_found=False)
        if not report_action:
            raise UserError("The report action 'ub_kontor.action_pay_receipt_pdf_report' is not defined.")

        return report_action.report_action(self.pay_receipt_id)


class PayReceiptPdfReport(models.AbstractModel):
    _name = 'report.ub_kontor.template_pay_receipt_pdf_report'
    _description = 'Payment Receipt PDF Report Template'

    @api.model
    def _get_report_values(self, docids, data=None):
        if not docids:
            raise UserError("No document IDs provided.")

        results = self._get_detailed_results(docids)
        new_results = self._get_aggregated_results(docids)
        residual_results = self._get_residual_data(docids)

        if not results:
            raise UserError("No results found for the provided document IDs.")

        grouped_results = {key: list(group) for key, group in groupby(results, key=lambda x: x['service_type_id'])}

        docs = self.env['pay.receipt'].browse(docids)
        address_type = docs[0].address_type if docs else ''
        company_logo = self.env.company.logo
        return {
            'model': self._name,
            'docs': docs,
            'logo_data_uri': self.image_data_uri(company_logo),
            'results': grouped_results,
            'address_type': self.get_address_type_display(address_type),
            'service_type_ids': list({r['service_type_id'] for r in results}),
            'format_number': self.format_number,
            'new_results': new_results,
            'residual_results': residual_results
        }

    def image_data_uri(self, image):
        if not image:
            return ''
        return 'data:image/png;base64,' + image.decode('utf-8')

    def _get_detailed_results(self, docids):

        self.env.cr.execute(f"""
             select sp.receipt_id as receipt_id,
             (sp.work_amount * 0.1)+ sp.work_amount as work_amount,
             (sp.material_amount * 0.1)+ sp.material_amount as material_amount, 
             (sp.bill_amount * 0.1)+ sp.bill_amount as bill_amount, 
            (sp.heating_price * 0.1)+ sp.heating_price as heating_price,
            (sp.water_heating_price * 0.1)+ sp.water_heating_price as water_heating_price, (sp.total_amount * 0.1)+ sp.total_amount as total_amount, 
            sp.payment_service_count as payment_service_count,
            sp.work_amount_count as work_amount_count,
            sp.material_amount_count as material_amount_count,
            sp.bill_amount_count as bill_amount_count,
            sp.heating_price_count as heating_price_count,
            sp.water_heating_price_count as water_heating_price_count
            from (
                select pra.receipt_id as receipt_id, count(pral.service_type_id) as payment_service_count, 
                sum(sp.work_amount) as work_amount, 
                sum(sp.material_amount) as material_amount, 
                sum(sp.bill_amount) as bill_amount, 
                sum(sp.heating_price) as heating_price, 
                sum(sp.water_heating_price) as water_heating_price, 
                sum(sp.total_amount) as total_amount,
                
                count(case when sp.work_amount > 0.0 then 1 end) work_amount_count,
                count(case when sp.material_amount > 0.0 then 1 end) material_amount_count,
                count(case when sp.bill_amount > 0.0 then 1 end) bill_amount_count,
                count(case when sp.heating_price > 0.0 then 1 end) heating_price_count,
                count(case when sp.water_heating_price > 0.0 then 1 end) water_heating_price_count
                from pay_receipt_address pra
                inner join pay_receipt_address_line pral on pral.receipt_address_id = pra.id
                inner join ref_service_type service on service.id = pral.service_type_id and service.category = 'service_payment'
                inner join service_payment sp on sp.id = pral.service_payment_id and sp.active = True
                where pra.receipt_id in {tuple(docids) if len(docids) > 1 else f"({docids[0]})"}
                group by pra.receipt_id
            ) sp
        """)
        service_payment_list = self.env.cr.dictfetchone()
        if service_payment_list:
            # service_name =  {
            #     'work_amount': 'Ажлын хөлс',
            #     'material_amount': 'Материалын хөлс',
            #     'bill_amount': 'ТҮ хуудас үнэ',
            #     'heating_price': 'Халаалт буулгасан үнэ',
            #     'water_heating_price': 'Ус буулгасан үнэ',
            # }
            service_type = self.env['ref.service.type'].search([('category', '=', 'service_payment')], order="id asc", limit=1)
            service_id = service_type.id
            service_payment_list = [
                {
                    'service_type_id': service_id,
                    'service_name': service_type.name,
                    'uom_name': 'Ажлын хөлс',
                    'vat_type': 'VAT_ABLE',
                    'qty': service_payment_list.get("work_amount_count"),
                    'total_vat': service_payment_list.get('work_amount')/1.1 * 0.1,
                    'total_amount': service_payment_list.get('work_amount'),
                    'is_payment_service': True
                },
                {
                    'service_type_id': service_id,
                    'service_name': service_type.name,
                    'uom_name': 'Материалын хөлс',
                    'vat_type': 'VAT_ABLE',
                    'qty': service_payment_list.get("material_amount_count"),
                    'total_vat': service_payment_list.get('material_amount') / 1.1 * 0.1,
                    'total_amount': service_payment_list.get('material_amount'),
                    'is_payment_service': True
                },
                {
                    'service_type_id': service_id,
                    'service_name': service_type.name,
                    'uom_name': 'ТҮ хуудас үнэ',
                    'vat_type': 'VAT_ABLE',
                    'qty': service_payment_list.get("bill_amount_count"),
                    'total_vat': service_payment_list.get('bill_amount') / 1.1 * 0.1,
                    'total_amount': service_payment_list.get('bill_amount'),
                },
                {
                    'service_type_id': service_id,
                    'service_name': service_type.name,
                    'uom_name': 'Халаалт буулгасан үнэ',
                    'vat_type': 'VAT_ABLE',
                    'qty': service_payment_list.get("heating_price_count"),
                    'total_vat': service_payment_list.get('heating_price') / 1.1 * 0.1,
                    'total_amount': service_payment_list.get('heating_price'),
                    'is_payment_service': True
                },
                {
                    'service_type_id': service_id,
                    'service_name': service_type.name,
                    'uom_name': 'Ус буулгасан үнэ',
                    'vat_type': 'VAT_ABLE',
                    'qty': service_payment_list.get("water_heating_price_count"),
                    'total_vat': service_payment_list.get('water_heating_price') / 1.1 * 0.1,
                    'total_amount': service_payment_list.get('water_heating_price'),
                    'is_payment_service': True
                },
            ]
        else:
            service_payment_list= []
        query = f"""
            SELECT 
                rst.id AS service_type_id, 
                coalesce(uu.id, uom_pricelist.id) AS uom_id,  -- Use MAX to get the UOM ID; you can change this based on your logic.
                rst.name AS service_name, 
                 coalesce(uu.name, uom_pricelist.name) AS uom_name,  -- Use COALESCE to show '-' when UOM is NULL
                MAX(rp.price) AS pricelist_price, 
                MAX(rp.vat_type) AS vat_type,  
                ROUND(CAST(SUM(pral.amount / NULLIF(pral.price, 0)) AS NUMERIC), 2) AS qty, 
                SUM(ROUND(CAST(pral.noat as numeric), 2)) AS total_vat, 
                SUM(ROUND(CAST(pral.total_amount as numeric), 2)) AS total_amount,  -- Total amount summed across service types
                pr.company_id
            FROM pay_receipt pr 
            JOIN pay_receipt_address pra ON pra.receipt_id = pr.id
            JOIN pay_receipt_address_line pral ON pra.id = pral.receipt_address_id
            LEFT JOIN ref_service_type rst ON rst.id = pral.service_type_id
            LEFT JOIN uom_uom uu ON uu.id = pral.uom_id 
            LEFT JOIN ref_pricelist rp ON rp.id = pral.pricelist_id
            LEFT JOIN uom_uom uom_pricelist on uom_pricelist.id = rp.uom_id 
            WHERE pr.id IN %s { "and rst.category != 'service_payment'" if service_payment_list else ""}
            GROUP BY rst.id, rst.name, pr.company_id, uu.id, pral.pricelist_id, uom_pricelist.id 
            ORDER BY rst.name
        """
        params = (tuple(docids),)
        self.env.cr.execute(query, params)
        return self.env.cr.dictfetchall()+service_payment_list

    def _get_residual_data(self, docids):
        pay_receipt = self.env['pay.receipt'].browse(docids[:1])
        company_id = self.env.company.id
        address_type = pay_receipt.address_type
        year = int(pay_receipt.year)  # String утгыг integer болгож хөрвүүлнэ
        month = int(pay_receipt.month)  # String утгыг integer болгож хөрвүүлнэ
        current_month_first = datetime(year, month, 1)

        if not company_id or not address_type:
            raise UserError("Company ID or address type could not be determined.")

        # Calculate the 25th day of the selected month
        selected_month_25th = datetime(year, month, 25)

        # Calculate the 5th day of the current month
        current_date = datetime.now()
        next_month_5th = datetime(current_date.year, (current_date.month % 12) + 1, 5)
        amount_residual = pay_receipt.first_balance
        # Check if the current date falls within the range of the 25th of the selected month and the 5th of the next month
        # if selected_month_25th <= current_date <= next_month_5th:
        # Fetch the residual amount
        query = f"""
            SELECT  ROUND(CAST(SUM(residual.amount_residual) AS NUMERIC), 2) AS amount_residual
            FROM (
                SELECT 
                    last_balance.address_id AS address_id, 
                    ROUND(CAST(SUM(last_balance.residual) AS NUMERIC), 2) AS amount_residual, 
                    STRING_AGG(last_balance.invoice_name, ', ') AS invoice_names
                FROM (
                    SELECT 
                        invoice.address_id AS address_id,
                        ROUND(CAST(invoice.amount_total AS NUMERIC), 2) - 
                        ROUND(CAST(COALESCE(SUM(payment.amount), 0) AS NUMERIC), 2) AS residual,
                        CONCAT(invoice.year, '-', invoice.month) AS invoice_name
                    FROM pay_receipt_address_invoice invoice
                    INNER JOIN ref_address address 
                        ON address.id = invoice.address_id 
                        AND invoice.company_id = {company_id}
                        AND address.type = '{address_type}'
                        AND CONCAT(invoice.year, '-', invoice.month, '-01')::DATE < '{current_month_first}'::DATE
                    LEFT JOIN pay_address_payment_line payment 
                        ON payment.invoice_id = invoice.id 
                        AND payment.period_id IN (
                            SELECT pp.id 
                            FROM pay_period pp 
                            WHERE pp.company_id = {company_id}
                            AND pp.address_type = '{address_type}' 
                            AND CONCAT(pp.year, '-', pp.month, '-01')::DATE < '{current_month_first}'::DATE
                        )
                    GROUP BY invoice.id
                ) last_balance
                WHERE last_balance.residual > 0.0
                GROUP BY last_balance.address_id
            ) residual;
        """
        self.env.cr.execute(query)
        result = self.env.cr.dictfetchone()

        amount_residual = result.get('amount_residual', 0) if result else 0

        # Update the first_balance field in the pay_receipt table
        update_query = """
            UPDATE pay_receipt
            SET first_balance = %s
            WHERE id = %s
        """
        self.env.cr.execute(update_query, (amount_residual, pay_receipt.id))
        return {'amount_residual': amount_residual}

    def _get_aggregated_results(self, docids):
        detailed_results = self._get_detailed_results(docids)
        total_amount = sum(result['total_amount'] for result in detailed_results)
        total_vat = sum(result['total_vat'] for result in detailed_results)

        pay_receipt = self.env['pay.receipt'].browse(docids[:1])
        company_id = pay_receipt.company_id.id
        address_type = pay_receipt.address_type

        if not company_id or not address_type:
            raise UserError("Company ID or address type could not be determined.")

        query = """
            SELECT 
                COUNT(DISTINCT apartment_id) AS "Нийт байр",
                COALESCE(SUM(family), 0) AS "Нийт ам бүл",
                COUNT(DISTINCT praid) AS "Нийт өрх",
                COUNT(DISTINCT CASE WHEN us_tooluur > 0 THEN praid END) AS "Усны тоолууртай",
                COUNT(DISTINCT praid) - COUNT(DISTINCT CASE WHEN us_tooluur > 0 THEN praid END) AS "Усны тоолуургүй",
                COALESCE(SUM(CASE WHEN us_tooluur > 0 THEN family ELSE 0 END), 0) AS "Ам бүл Усны тоолууртай",
                COALESCE(SUM(CASE WHEN us_tooluur = 0 THEN family ELSE 0 END), 0) AS "Ам бүл Усны тоолуургүй",
                COUNT(DISTINCT CASE WHEN dulaan_tooluur > 0 THEN praid END) AS "Дулааны тоолууртай",
                COUNT(DISTINCT praid) - COUNT(DISTINCT CASE WHEN dulaan_tooluur > 0 THEN praid END) AS "Дулааны тоолуургүй",
                %s AS "Нийт дүн",
                %s AS "Нөат дүн"
            FROM (
                SELECT
                    max(pra.apartment_id) as apartment_id,
                    max(pra.address_id) as address_id,
                    max(pra.family) as family,
                    pra.id as praid,
                    COUNT(CASE WHEN cc.category = 'counter' THEN 1 END) AS us_tooluur,
                    COUNT(CASE WHEN cc.category = 'thermal_counter' THEN 1 END) AS dulaan_tooluur
                FROM pay_receipt pr
                INNER JOIN pay_receipt_address pra ON pr.id = pra.receipt_id
                INNER JOIN pay_receipt_address_line pral ON pra.id = pral.receipt_address_id
                LEFT JOIN ref_pricelist rpl ON pral.pricelist_id = rpl.id
                INNER JOIN ref_address ra ON pra.address_id = ra.id
                LEFT JOIN counter_counter cc ON cc.address_id = ra.id
                WHERE pr.company_id = %s AND pr.address_type = %s AND pr.year = %s AND pr.month = %s
                GROUP BY pra.id
            ) as tem 
        """

        self.env.cr.execute(query,
                            (total_amount, total_vat, company_id, address_type, pay_receipt.year, pay_receipt.month))
        return self.env.cr.dictfetchall()

    def format_number(self, value):
        return "{:,.2f}".format(value or 0)

    def get_address_type_display(self, address_type):
        """Return the display value for the address type."""
        field = self.env['pay.receipt.pdf.report.wizard']._fields['address_type']
        return dict(field.selection).get(address_type, '')
