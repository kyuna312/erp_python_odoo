import base64
import calendar
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api
import io
import xlsxwriter


class PayIncomePdfReportWizard(models.TransientModel):
    _name = 'not.pay.apartment.pdf.report.wizard'
    _description = 'Төлбөр төлөөгүй байрнуудын тайлан'
    company_id = fields.Many2one('res.company', 'ХҮТ', default=lambda self: self.env.user.company_id.id)
    inspector_ids = fields.Many2many('hr.employee', string='Байцаагч', domain=lambda self: [
        ('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)])
    apartment_ids = fields.Many2many('ref.apartment', string='Байр')
    year = fields.Selection(
        [(str(year), str(year)) for year in range(datetime.now().year, 2018, -1)],
        string="Он", required=True
    )
    month = fields.Selection(
        [(str(i).zfill(2), f'{i}-р сар') for i in range(1, 13)],
        string='Сар', required=True
    )
    filename = fields.Char('Filename', readonly=True)

    def download(self):
        report_action = self.env.ref('ub_kontor.action_not_pay_apartment_pdf_report_template')

        return report_action.report_action(self)

    def prepare_data(self):
        inspector_ids = self.inspector_ids.ids
        apartment_ids = self.apartment_ids.ids
        company_id = self.company_id.id
        address_type = self.env.user.access_type
        company_name = self.company_id.name
        condition_of_inspector = ""
        condition_of_apartment = ""
        year = int(self.year)
        month = int(self.month)
        last_day = int(calendar.monthrange(year, month)[1])

        income_date = datetime.strptime(f'{year}-{month}-01', '%Y-%m-%d') + relativedelta(months=1)
        income_year = int(income_date.year)
        income_month = int(income_date.month)
        income_last_day = int(calendar.monthrange(income_year, income_month)[1])
        period_id = self.env['pay.period'].sudo().search(
            [('company_id', '=', company_id), ('address_type', '=', address_type), ('year', '=', str(year)),
             ('month', '=', str(month).zfill(2))], limit=1)
        if (inspector_ids):
            condition_of_inspector = f""" and inspector.id in {tuple(inspector_ids) if len(inspector_ids) > 1 else f"({inspector_ids[0]})"}"""
        if (apartment_ids):
            condition_of_apartment = f""" and address.apartment_id in {tuple(apartment_ids) if len(apartment_ids) > 1 else f"({apartment_ids[0]})"}"""
        if period_id.state == 'opened':
            query = """
                select address.code as address_code, 
                apartment.code as apartment_code, 
                address.address as address_address , 
                address.name as address_name,
                address.inspector_id as inspector_id, 
                inspector.name as inspector_name, 
                address.id as address_id, 
                apartment.id as apartment_id,
                round(cast(coalesce(sum(pre_invoiced.amount),0.0) - coalesce(sum(pre_paid.amount),0.0) as numeric),2) as pre_month_residual, 
                coalesce(current_invoiced.amount,0.0) as current_invoiced_amount,
                coalesce(total_paid.amount,0.0) as total_paid_amount,
                round(cast(coalesce(sum(last_invoiced.amount),0.0) - coalesce(sum(last_paid.amount),0.0) as numeric),2) as last_month_residual, 
                not_paid_invoice.context
                from ref_address address
                inner join ref_apartment apartment on apartment.id = address.apartment_id
                left join (
                    select invoice.address_id as address_id, round(cast(sum(invoice.amount_total) as numeric),2) amount from pay_receipt_address_invoice invoice
                    where invoice.company_id = {company_id} and concat(invoice.year, '-',invoice.month, '-', '01')::date < '{year}-{month}-01'::date
                    group by invoice.address_id
                ) pre_invoiced on pre_invoiced.address_id = address.id
                left join (
                    select invoice.address_id as address_id, round(cast(sum(payment_line.amount) as numeric),2) as amount from pay_receipt_address_invoice invoice
                    inner join pay_address_payment_line payment_line on payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date < '{year}-{month}-01'::date and pp.company_id = {company_id})
                    where concat(invoice.year, '-',invoice.month, '-', '01')::date < '{year}-{month}-01'::date and invoice.company_id = {company_id}
                    group by invoice.address_id
                ) pre_paid on pre_paid.address_id = address.id
                left join (
                    select invoice.address_id as address_id, sum(invoice.amount_total) as amount from pay_receipt_address_invoice invoice
                    where invoice.year::integer = {year}::integer and invoice.month::integer = {month}::integer and invoice.company_id = {company_id}
                    group by invoice.address_id
                ) current_invoiced on current_invoiced.address_id = address.id
                left join (
                    select payment.address_id as address_id, round(cast(sum(payment_line.amount) as numeric), 2) as amount from pay_address_payment payment
                    inner join ref_address address on address.id = payment.address_id and address.company_id={company_id} and address.type='{address_type}'
                    inner join pay_address_payment_line payment_line on payment_line.payment_id = payment.id and payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date = '{year}-{month}-01'::date and pp.company_id = {company_id})
                    group by payment.address_id
                ) total_paid on total_paid.address_id = address.id
                left join (
                    select invoice.address_id as address_id, round(cast(sum(invoice.amount_total) as numeric),2) amount from pay_receipt_address_invoice invoice
                    where invoice.company_id = {company_id} and concat(invoice.year, '-',invoice.month, '-', '01')::date <='{year}-{month}-{last_day_of_month}'::date
                    group by invoice.address_id
                ) last_invoiced on last_invoiced.address_id = address.id
                left join (
                    select invoice.address_id as address_id, round(cast(sum(payment_line.amount) as numeric),2) as amount from pay_receipt_address_invoice invoice
                    inner join pay_address_payment_line payment_line on payment_line.invoice_id = invoice.id and payment_line.period_id in (select pp.id from pay_period pp where concat(pp.year,'-', pp.month, '-01')::date <= '{year}-{month}-{last_day_of_month}'::date and pp.company_id = {company_id})
                    where concat(invoice.year, '-',invoice.month, '-', '01')::date <= '{year}-{month}-{last_day_of_month}'::date and invoice.company_id = {company_id}
                    group by invoice.address_id
                ) last_paid on last_paid.address_id = address.id
                left join (
                    select invoice.address_id as address_id, string_agg(concat(invoice.year, '-', invoice.month), ',') as context from pay_receipt_address_invoice invoice
                    where invoice.company_id = {company_id} and invoice.payment_state != 'paid'
                    group by invoice.address_id
                ) not_paid_invoice on not_paid_invoice.address_id = address.id
                left join hr_employee inspector on inspector.id = address.inspector_id 
                where address.company_id = {company_id} and address.type = '{address_type}' {condition_of_inspector} {condition_of_apartment}
                group by address.id, apartment.id, current_invoiced.amount, total_paid.amount, inspector.id, not_paid_invoice.context
                having round(cast(coalesce(sum(last_invoiced.amount),0.0) - coalesce(sum(last_paid.amount),0.0) as numeric),2) > 0.0
                order by address.inspector_id, apartment.code, address.float_address asc;
            """.format(company_id=company_id, address_type=address_type, year=year, month=month,
                       condition_of_inspector=condition_of_inspector, condition_of_apartment=condition_of_apartment,
                       income_year=income_year, income_month=income_month, income_last_day=income_last_day,
                       last_day_of_month=last_day, )
        elif period_id.state == 'closed':
            query = f"""
                select address.code as address_code,
                apartment.id as apartment_id,
                apartment.code as apartment_code, 
                address.id as address_id,
                address.address address_address,
                address.name as address_name,
                inspector.id as inspector_id, 
                inspector.name as inspector_name, 
                report.first_balance_amount as pre_month_residual, 
                report.invoiced_amount as current_invoiced_amount,
                report.last_balance_amount as last_month_residual, 
                report.total_paid_amount as total_paid_amount,
                report.unpaid_invoices as context
                from pay_period_report report 
                inner join ref_address address on address.id = report.address_id 
                inner join ref_apartment apartment on apartment.id = address.apartment_id 
                inner join hr_employee inspector on report.inspector_id = inspector.id
                where report.last_balance_amount > 0 and report.period_id = {period_id.id} {condition_of_inspector} {condition_of_apartment}
                order by  address.inspector_id, apartment.code, address.float_address asc;
            """
        self.env.cr.execute(query)
        data_section_1 = self.env.cr.dictfetchall()
        return data_section_1, address_type, company_name, year, month, self._image_data_uri(self.company_id.logo)

    def import_xls(self):
        xls_content = io.BytesIO()
        workbook_wt = xlsxwriter.Workbook(xls_content, {'in_memory': True})
        sheet_wt = workbook_wt.add_worksheet()

        headers = [
            'Хэрэглэгчийн Код', 'Байр', 'Тоот',
            'Хэрэглэгчийн Нэр', 'Эхний Үлдэгдэл',
            'Төлбөл Зохих', 'Нийт Төлсөн',
            'Эцсийн Үлдэгдэл', 'Нэхэмжлэлүүд'
        ]

        header_format = workbook_wt.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': '#F5F5F5', 'border': 1
        })
        sheet_wt.write_row(0, 0, headers, header_format)

        report_datas, address_type, company_name, year, month, logo = self.prepare_data()
        total_values, last_data_row = self.write_data_rows(sheet_wt, report_datas, workbook_wt)
        grand_total_row = last_data_row
        self.write_totals(sheet_wt, total_values, grand_total_row, workbook_wt)

        workbook_wt.close()
        xls_content.seek(0)
        xlsx_data = base64.b64encode(xls_content.read()).decode('utf-8')
        self.filename = f"not_pay_apartment_report_{month}_{year}.xlsx"

        return {
            'type': 'ir.actions.act_url',
            'url': f'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{xlsx_data}',
            'target': 'new',
            'nodestroy': True,
        }

    def write_data_rows(self, sheet_wt, report_datas, workbook_wt):
        total_values = self.initialize_totals()
        previous_inspector_id = None
        inspector_totals = {}
        row_i = 0

        for data in report_datas:
            inspector_id = data.get('inspector_id')
            inspector_name = data.get('inspector_name', '')

            if inspector_id != previous_inspector_id:
                if previous_inspector_id is not None:
                    self.write_inspector_totals(sheet_wt, previous_inspector_name, inspector_totals, row_i, workbook_wt)
                    row_i += 1
                else:
                    row_i += 0

                sheet_wt.write(row_i, 0, inspector_name, workbook_wt.add_format({'bold': True}))
                previous_inspector_id = inspector_id
                previous_inspector_name = inspector_name
                inspector_totals = self.initialize_totals()
                row_i += 1

            sheet_wt.write(row_i, 0, data.get('address_code', ''))
            sheet_wt.write(row_i, 1, data.get('apartment_code', ''))
            sheet_wt.write(row_i, 2, data.get('address_address', ''))
            sheet_wt.write(row_i, 3, data.get('address_name', ''))

            for idx, key in enumerate(
                    ['pre_month_residual', 'current_invoiced_amount', 'total_paid_amount', 'last_month_residual'],
                    start=4):
                value = float(data.get(key, 0))
                sheet_wt.write(row_i, idx, value, self.number_format(workbook_wt))
                total_values[key] += value
                inspector_totals[key] += value

            total_values['apartment_count'] += 1
            total_values['address_count'] += 1
            inspector_totals['apartment_count'] += 1
            inspector_totals['address_count'] += 1

            sheet_wt.write(row_i, 8, data.get('context', ''))
            row_i += 1

        if previous_inspector_id is not None:
            self.write_inspector_totals(sheet_wt, previous_inspector_name, inspector_totals, row_i, workbook_wt)
            row_i += 1

        return total_values, row_i

    def initialize_totals(self):
        return {
            'apartment_count': 0,
            'address_count': 0,
            'pre_month_residual': 0,
            'current_invoiced_amount': 0,
            'total_paid_amount': 0,
            'last_month_residual': 0,
        }

    def write_inspector_totals(self, sheet_wt, inspector_name, totals, row_i, workbook_wt):
        bold_format = workbook_wt.add_format({'bold': True})
        sheet_wt.write(row_i, 0, inspector_name, bold_format)
        sheet_wt.write(row_i, 1, totals['apartment_count'], bold_format)
        sheet_wt.write(row_i, 2, totals['address_count'], bold_format)
        sheet_wt.write(row_i, 4, totals['pre_month_residual'], bold_format)
        sheet_wt.write(row_i, 5, totals['current_invoiced_amount'], bold_format)
        sheet_wt.write(row_i, 6, totals['total_paid_amount'], bold_format)
        sheet_wt.write(row_i, 7, totals['last_month_residual'], bold_format)

    def write_totals(self, sheet, total_values, last_row, workbook_wt):
        # Create a format for bold text with number format for numeric cells
        bold_format = workbook_wt.add_format({'bold': True})
        bold_number_format = workbook_wt.add_format({'bold': True, 'num_format': '#,##0.00'})

        # Write the label in bold format
        sheet.write(last_row, 0, 'Нийт:', bold_format)

        # Write counts without number formatting
        sheet.write(last_row, 1, total_values['apartment_count'], bold_format)
        sheet.write(last_row, 2, total_values['address_count'], bold_format)

        # Write numeric totals with bold and number format
        sheet.write(last_row, 4, total_values['pre_month_residual'], bold_number_format)
        sheet.write(last_row, 5, total_values['current_invoiced_amount'], bold_number_format)
        sheet.write(last_row, 6, total_values['total_paid_amount'], bold_number_format)
        sheet.write(last_row, 7, total_values['last_month_residual'], bold_number_format)

    def number_format(self, workbook_wt):
        return workbook_wt.add_format({'num_format': '#,##0.00'})

    def _image_data_uri(self, image: bytes) -> str:
        return f'data:image/png;base64,{base64.b64encode(image).decode()}' if image else ''


class NotPayApartmentPdfReport(models.AbstractModel):
    _name = 'report.ub_kontor.not_pay_apartment_pdf_report_template'
    _description = 'Payment Receipt PDF Report Template'

    @api.model
    def _get_report_values(self, docids, data=None):
        data_section_1, address_type, company_name, year, month, logo = self.env[
            'not.pay.apartment.pdf.report.wizard'].browse(docids).prepare_data()
        total_apartment_count = len(list(set([d.get('apartment_id') for d in data_section_1])))
        return {
            'model': 'not.pay.apartment.pdf.report.wizard',
            'data_section_1': data_section_1,
            'address_type': 'Орон сууц' if address_type == 'OS' else 'Аж ахуй нэгж',
            'company_name': company_name,
            'year': year,
            'month': month,
            'logo_data_uri': logo,
            'total_apartment_count': total_apartment_count
        }
