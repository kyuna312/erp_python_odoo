from reportlab.lib.colors import ivory

from odoo import models, fields
from odoo.exceptions import ValidationError, UserError
import xlrd
import io
import base64
import xlsxwriter

class PayImportInvoiceWizard(models.TransientModel):
    _name = 'pay.import.invoice.wizard'
    file = fields.Binary('Файл', required=True)
    company_id = fields.Many2one('res.company','ХҮТ', required=True, default=lambda self: self.env.company)
    method = fields.Selection([('create_invoice', 'Нэхэмжлэл үүсгэх'), ('change_invoice_residual', 'Нэхэмжлэлийн үлдэгдэл өөрчлөх')], string='Method', default='create_invoice', required=True)
    def format_string_data(self, data):
        if type(data) != str:
            data = float(data)
            if (data.is_integer()):
                data = str(int(data))
            else:
                data = str(data)
        return data

    def change_invoice_residual(self):
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data, on_demand=True)
        sheet = book.sheet_by_index(0)
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        result = []
        error_list = []
        company_id = self.company_id.id
        account_id = self.env['pay.bank.account'].search([('company_id', '=',company_id)], limit=1)
        if(account_id):
            account_id = account_id.id
        else:
            raise UserError('Данс үүсээгүй байна')

        while rowi < nrows:
            row = sheet.row(rowi)
            if 'Хэрэглэгчийн код' == row[0].value:
                start_import = True
                rowi += 1
                row = sheet.row(rowi)
            if (start_import):
                address_code = str(self.format_string_data(row[0].value))
                year = str(self.format_string_data(row[1].value))
                month = self.format_string_data(row[2].value)
                month = f'0{month}' if int(month) < 9 else f'{month}'
                untaxed_amount = row[3].value or 0.0
                amount_tax = row[4].value or 0.0
                residual_amount = row[5].value or 0.0
                total_amount = row[6].value or 0.0
                paid_amount = total_amount - residual_amount
                if(paid_amount <= 0.0):
                    continue
                address_id = self.env['ref.address'].search([('code', '=', address_code)], order="id desc", limit=1)
                if address_id:
                    address_id = address_id.id
                    invoice = self.find_address_invoice(month=int(month), year=int(year), address_id=int(address_id))
                    if invoice:
                        invoice = invoice[0]
                    else:
                        error_list += [{
                            'amount_residual': residual_amount,
                            'amount_total': total_amount,
                            'amount_tax': amount_tax,
                            'amount_untaxed': untaxed_amount,
                            'year': year,
                            'month': month,
                            'address_code': address_code,
                            'msg': 'Нэхэмжлэл олдсонгүй'
                        }]
                        continue
                    if (invoice.get('amount_residual') - residual_amount<=0.0):
                        continue
                    payment = self.env['pay.address.payment'].create({
                        'address_id': address_id,
                        'account_id': account_id,
                        'amount': invoice.get('amount_residual') - residual_amount
                    })
                    data = payment.prepare_line_by_invoice(invoice_ids=[invoice.get('invoice_id')])
                    self.env['pay.address.payment.line'].sudo().create(data)
                else:
                    error_list += [{
                        'amount_residual': residual_amount,
                        'amount_total': total_amount,
                        'amount_tax': amount_tax,
                        'amount_untaxed': untaxed_amount,
                        'year': year,
                        'month': month,
                        'address_code': address_code,
                        'msg': 'Тоот олдсонгүй'
                    }]
                rowi += 1
        if error_list:
            return self.prepare_failed_list_by_xls(error_list=error_list)
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Нэхэмжлэлүүд амжилттай үүсгэгдлээ',
                    # 'message': f'Тоолуурын заалтыг групп-үүд}',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }

    def create_invoice(self):
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data, on_demand=True)
        sheet = book.sheet_by_index(0)
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        result = []
        error_list = []
        company_id = self.company_id.id
        while rowi < nrows:
            row = sheet.row(rowi)
            if 'Хэрэглэгчийн код' == row[0].value:
                start_import = True
                rowi += 1
                row = sheet.row(rowi)
            if (start_import):
                address_code = str(self.format_string_data(row[0].value))
                year = str(self.format_string_data(row[1].value))
                month = self.format_string_data(row[2].value)
                month = f'0{month}' if int(month) <= 9 else f'{month}'
                untaxed_amount = row[3].value or 0.0
                amount_tax = row[4].value or 0.0
                total_amount = row[5].value or 0.0
                address_id = self.env['ref.address'].search([('code', '=', address_code)], order="id desc", limit=1)
                if address_id:
                    address_id = address_id.id
                    result += [{
                        'amount_residual': total_amount,
                        'amount_total': total_amount,
                        'amount_tax': amount_tax,
                        'amount_untaxed': untaxed_amount,
                        'year': year,
                        'month': month,
                        'address_id': address_id,
                        'payment_reference': address_code,
                        'company_id': company_id,
                        'state': 'posted'
                    }]
                else:
                    error_list += [{
                        'amount_residual': total_amount,
                        'amount_total': total_amount,
                        'amount_tax': amount_tax,
                        'amount_untaxed': untaxed_amount,
                        'year': year,
                        'month': month,
                        'address_code': address_code,
                        'msg': 'Тоот олдсонгүй'
                    }]
                rowi += 1
        self.env['pay.receipt.address.invoice'].create(result)
        if error_list:
            return self.prepare_failed_list_by_xls(error_list=error_list)
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Нэхэмжлэлүүд амжилттай үүсгэгдлээ',
                    # 'message': f'Тоолуурын заалтыг групп-үүд}',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }

    def import_file(self):
        if (not self.file):
            raise UserError('Файлаа оруулна уу!')
        if(self.method == 'create_invoice'):
            return self.create_invoice()
        elif(self.method == 'change_invoice_residual'):
            return self.change_invoice_residual()


    def prepare_failed_list_by_xls(self, error_list=[]):
        xls_content = io.BytesIO()
        workbook_wt = xlsxwriter.Workbook(xls_content)
        sheet_wt = workbook_wt.add_worksheet()
        method = self.method
        sheet_wt.write(0, 0, 'Хэрэглэгчийн код')
        sheet_wt.write(0, 1, 'Жил')
        sheet_wt.write(0, 2, 'Сар')
        sheet_wt.write(0, 3, 'Татаваргүй дүн')
        sheet_wt.write(0, 4, 'Татварын дүн')
        sheet_wt.write(0, 5, 'Үлдэгдэл')

        if method == 'create_invoice':
            sheet_wt.write(0, 6, 'Алдааны мэдээлэл')
        elif method == 'change_invoice_residual':
            sheet_wt.write(0, 6, 'Нэхэмжилсэн дүн')
            sheet_wt.write(0, 6, 'Алдааны мэдээлэл')
        row_wt = 1
        for error in error_list:
            sheet_wt.write(row_wt, 0, error.get('address_code'))
            sheet_wt.write(row_wt, 1, error.get('year'))
            sheet_wt.write(row_wt, 2, error.get('month'))
            sheet_wt.write(row_wt, 3, error.get('amount_untaxed'))
            sheet_wt.write(row_wt, 4, error.get('amount_tax'))
            sheet_wt.write(row_wt, 5, error.get('amount_residual'))
            # create_invoice
            # change_invoice_residual
            if method == 'create_invoice':
                sheet_wt.write(row_wt, 6, error.get('msg'))

            elif method == 'change_invoice_residual':
                sheet_wt.write(row_wt, 6, error.get('amount_total'))
                sheet_wt.write(row_wt, 7, error.get('msg'))

            row_wt += 1
        workbook_wt.close()
        xls_content.seek(0)
        xlsx_data = base64.b64encode(xls_content.read())
        self.write({'file': xlsx_data})
        name = 'алдааны_мэдэээ.xlsx'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=pay.import.invoice.wizard&id={self.id}&field=file&filename_field={name}&download=true&filename={name}',
            'target': 'self',
        }

    def find_address_invoice(self, month:int, year:int, address_id:int)->[]:
        self.env.cr.execute(f"""
            select invoice.id as invoice_id, invoice.amount_residual as amount_residual 
            from pay_receipt_address_invoice invoice
            where invoice.address_id = {address_id} and invoice.year::INTEGER = {year} and invoice.month::INTEGER = {month}
            order by id desc
            limit 1;
        """)
        return self.env.cr.dictfetchall()

