from odoo import api, fields, models, _
from datetime import datetime, timedelta
import base64
import xlsxwriter
import io


class WriteOffDebtReport(models.TransientModel):
    _name = 'write.off.debt.report'
    start_date = fields.Date('Эхлэх огноо', required=True)
    end_date = fields.Date('Дуусах огноо', required=True,  default=fields.Date.today)
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True, default=lambda self: self.env.company)
    bank_id = fields.Many2one('pay.bank', 'Банк', required=True, default=lambda self: self._default_bank_id())
    period_id = fields.Many2one('pay.period', 'Мөчлөг', required=True, default=lambda self: self._default_period_id())
    file = fields.Binary('Файл')

    @api.model
    def _default_bank_id(self):
        bank_names = ['Төрийн банк']
        return self.env['pay.bank'].search([('name', 'ilike', '|'.join(bank_names))], limit=1)

    @api.model
    def _default_period_id(self):
        # Search for the most recent period by ordering by year and month descending
        last_period = self.env['pay.period'].search([], order='year DESC, month DESC', limit=1)

        # Return the ID of the most recent period, or False if none is found
        return last_period.id if last_period else False

    def prepare_data(self):
        query = f"""
            select address.code as address_code, account.name as account_name, bank.name as bank_name, account.id as account_id,
            last_payment_line.reconciled_date as payment_date,
            concat(invoice.year,'-',invoice.month) as invoiced_date,
            sum(invoice.amount_total) as amount_total,
            invoice.year as invoice_year,
            invoice.month as invoice_month
            from pay_receipt_address_invoice invoice
            inner join (
                select max(payment.id) payment_line_id, payment.invoice_id as invoice_id from pay_address_payment_line payment
                where payment.reconciled_date::DATE <= '{str(self.end_date)}' and payment.reconciled_date::DATE >= '{str(self.start_date)}'
                group by payment.invoice_id
            ) last_paid_line_id on last_paid_line_id.invoice_id = invoice.id
            inner join pay_address_payment_line last_payment_line on last_payment_line.id = last_paid_line_id.payment_line_id and last_payment_line.period_id = {self.period_id.id}
            inner join pay_address_payment payment on payment.id = last_payment_line.payment_id            
            inner join pay_bank_account account on payment.account_id = account.id
            inner join pay_bank bank on bank.id = account.bank_id 
            inner join ref_address address on address.id = invoice.address_id 
            inner join ref_apartment apartment on apartment.id = address.apartment_id 
            where invoice.payment_state = 'paid' and account.company_id = {self.company_id.id} and bank.id != {self.bank_id.id}
            group by apartment.id,address.id,account.id,payment.id,bank.id,invoice.year,invoice.month,last_payment_line.reconciled_date
            order by apartment.code asc, address.float_address asc
        """
        self.env.cr.execute(query)
        return self.env.cr.dictfetchall()

    def import_xls(self):
        xls_content = io.BytesIO()
        workbook_wt = xlsxwriter.Workbook(xls_content)
        sheet_wt = workbook_wt.add_worksheet()
        sheet_wt.write(0, 0, ' Хэрэглэгчийн код')
        sheet_wt.write(0, 1, 'Бүртгэсэн огноо')
        sheet_wt.write(0, 2, 'Банк')
        sheet_wt.write(0, 3, 'Данс')
        sheet_wt.write(0, 4, ' Нийт төлсөн дүн')
        sheet_wt.write(0, 5, 'Нэхэмжилсэн жил')
        sheet_wt.write(0, 5, 'Нэхэмжилсэн сар')
        report_datas = self.prepare_data()
        row_i = 1
        for data in report_datas:
            sheet_wt.write(row_i, 0, data.get('address_code'))
            sheet_wt.write(row_i, 1, str(data.get('payment_date')))
            sheet_wt.write(row_i, 2, data.get('bank_name'))
            sheet_wt.write(row_i, 3, data.get('account_name'))
            sheet_wt.write(row_i, 4, data.get('amount_total'))
            sheet_wt.write(row_i, 5, data.get('invoice_year'))
            sheet_wt.write(row_i, 6, data.get('invoice_month'))
            row_i += 1
        workbook_wt.close()
        xls_content.seek(0)
        xlsx_data = base64.b64encode(xls_content.read())
        self.write({'file': xlsx_data})
        name = f'{self.bank_id.name}_хасалт_.xlsx'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model={self._name}&id={self.id}&field=file&filename_field={name}&download=true&filename={name}',
            'target': 'self',
        }
