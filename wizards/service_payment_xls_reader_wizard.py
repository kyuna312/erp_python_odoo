from odoo import api, fields, models, _
from datetime import datetime, timedelta
import base64
import xlrd
import xlsxwriter
import io
from odoo.exceptions import ValidationError, UserError
from dateutil import parser

class ServicePaymentXlsReader(models.TransientModel):
    _name = "service.payment.xls.reader"

    file = fields.Binary('Файл', required=False)

    def serial_date_to_date(self, serial_date, base_date=datetime(1899, 12, 30)):
        actual_date = base_date + timedelta(days=serial_date)
        return actual_date.date()

    def format_string_data(self, data):
        if type(data) != str:
            data = float(data)
            if (data.is_integer()):
                data = str(int(data))
            else:
                data = str(data)
        return data

    def import_file(self):
        if(not self.file):
            raise UserError('Файлаа оруулна уу!')
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data, on_demand=True)
        sheet = book.sheet_by_index(0)
        xls_content = io.BytesIO()
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        row_wt = 1
        workbook_wt = xlsxwriter.Workbook(xls_content)
        sheet_wt = workbook_wt.add_worksheet()
        sheet_wt.write(0, 0, 'Д/д')
        sheet_wt.write(0, 1, 'Төлбөрт үйлчилгээний төрөл')
        # sheet_wt.write(0, 2, 'Хэрэглэгчийн төрөл')
        sheet_wt.write(0, 2, 'Байр')
        sheet_wt.write(0, 3, 'Тоот')
        sheet_wt.write(0, 4, 'Үйлчилгээ үзүүлсэн огноо')
        sheet_wt.write(0, 5, 'Бодолт хийх огноо')
        sheet_wt.write(0, 6, 'ТХ')
        sheet_wt.write(0, 7, 'Хийгдсэн ажил')
        sheet_wt.write(0, 8, 'Засвар хийсэн хүний код')
        sheet_wt.write(0, 9, 'Засвар хийсэн хүний нэр')
        sheet_wt.write(0, 10, 'Материалын нэр')
        sheet_wt.write(0, 11, 'Материалын үнэ')
        sheet_wt.write(0, 12, 'Ус буулгасан')
        sheet_wt.write(0, 13, 'Халаалт буулгасан')
        sheet_wt.write(0, 14, 'Ажлын хөлс')
        sheet_wt.write(0, 15, 'Хуудасны үнэ')
        sheet_wt.write(0, 16, 'Бүгд')
        sheet_wt.write(0, 17, 'Алдааны мэдээлэл')
        error_message = []

        while rowi < nrows:
            try:
                row = sheet.row(rowi)
                if row[0].value in ('Д/д', 'д/д', 'Д/Д', 'д/Д'):
                    start_import = True
                    rowi += 1
                    row = sheet.row(rowi)
                if(start_import):
                    number = str(row[0].value)
                    service_type = self.format_string_data(row[1].value)
                    apartment_code = self.format_string_data(sheet.cell(rowi, 2).value)
                    address_code = self.format_string_data(sheet.cell(rowi, 3).value)

                    date = row[4].value
                    compute_date = row[5].value
                    slip_number = str(row[6].value)
                    work_name = str(row[7].value)
                    employee_code = self.format_string_data(sheet.cell(rowi, 8).value)
                    employee_name = str(row[9].value)
                    material_name = str(row[10].value)
                    material_amount = float(row[11].value or 0.0)
                    water_heating_price = float(row[12].value or 0.0)
                    heating_price = float(row[13].value or 0.0)
                    work_amount = float(row[14].value or 0.0)
                    bill_amount = float(row[15].value or 0.0)
                    total_amount = float(row[16].value or 0.0)
                    apartment = self.env['ref.apartment'].search([('code', '=', apartment_code)], order="id desc", limit=1)
                    if(not apartment):
                        error_message += [{
                            'number': number,
                            'service_type': service_type,
                            'apartment_code': apartment_code,
                            'address_code': address_code,
                            'date': date,
                            'compute_date': compute_date,
                            'slip_number': slip_number,
                            'work_name': work_name,
                            'employee_code': employee_code,
                            'employee_name': employee_name,
                            'material_name': material_name,
                            'material_amount': material_amount,
                            'water_heating_price': water_heating_price,
                            'heating_price': heating_price,
                            'work_amount': work_amount,
                            'bill_amount': bill_amount,
                            'total_amount': total_amount,
                            'error_message': 'Байр олдсонгүй дахин шалгаад оруулна уу'
                        }]
                        rowi += 1
                        continue
                    address = self.env['ref.address'].search([('address', '=', address_code), ('apartment_id.code', '=', apartment_code)], order="id desc", limit=1)
                    if(not address):
                        error_message += [{
                            'number': number,
                            'service_type': service_type,
                            'apartment_code': apartment_code,
                            'address_code': address_code,
                            'date': date,
                            'compute_date': compute_date,
                            'slip_number': slip_number,
                            'work_name': work_name,
                            'employee_code': employee_code,
                            'employee_name': employee_name,
                            'material_name': material_name,
                            'material_amount': material_amount,
                            'water_heating_price': water_heating_price,
                            'heating_price': heating_price,
                            'work_amount': work_amount,
                            'bill_amount': bill_amount,
                            'total_amount': total_amount,
                            'error_message': 'Тоот олдсонгүй дахин шалгаад оруулна уу'
                        }]
                        rowi += 1
                        continue
                    try:
                        date = int(date)
                        date = self.serial_date_to_date(date)
                    except Exception as e:
                        # date = datetime.strptime(str(date).replace('.', '-'), '%Y-%m-%d').date()
                        date = parser.parse(date).date()
                    try:
                        compute_date = int(compute_date)
                        compute_date = self.serial_date_to_date(compute_date)
                    except Exception as e:
                        # compute_date = datetime.strptime(str(compute_date).replace('.', '-'), '%Y-%m-%d').date()
                        compute_date = parser.parse(compute_date).date()
                    employee = self.env['hr.employee'].search([('pin', '=', str(employee_code))], limit=1, order="id desc")
                    if(not employee):
                        error_message += [{
                            'number': number,
                            'service_type': service_type,
                            'apartment_code': apartment_code,
                            'address_code': address_code,
                            'date': date,
                            'compute_date': compute_date,
                            'slip_number': slip_number,
                            'work_name': work_name,
                            'employee_code': employee_code,
                            'employee_name': employee_name,
                            'material_name': material_name,
                            'material_amount': material_amount,
                            'water_heating_price': water_heating_price,
                            'heating_price': heating_price,
                            'work_amount': work_amount,
                            'bill_amount': bill_amount,
                            'total_amount': total_amount,
                            'error_message': 'Ажилтан олдсонгүй ажилтны кодыг дахин шалгаад оруулна уу'
                        }]
                        rowi+=1
                        continue
                    self.env['service.payment'].create({
                        'address_id': address.id,
                        'number': slip_number,
                        'work_amount': work_amount,
                        'material_amount': material_amount,
                        'employee_id': employee.id,
                        'bill_amount': bill_amount,
                        'work_name': work_name,
                        'heating_price': heating_price,
                        'material_name': material_name,
                        'water_heating_price': water_heating_price,
                        'date': str(compute_date),
                        'served_date': str(date),
                        'total_amount': total_amount,
                        'description': None,
                        'service_type': service_type,
                    })
                rowi += 1
            except IndexError:
                raise ValueError('Error', 'Excel sheet must be 2 columned : error on row: %s ' % rowi)
        if(error_message):
            for msg in error_message:
                sheet_wt.write(row_wt, 0, msg.get('number'))
                sheet_wt.write(row_wt, 1, msg.get('service_type'))
                sheet_wt.write(row_wt, 2, msg.get('apartment_code'))
                sheet_wt.write(row_wt, 3, msg.get('address_code'))
                sheet_wt.write(row_wt, 4, msg.get('date'))
                sheet_wt.write(row_wt, 5, msg.get('compute_date'))
                sheet_wt.write(row_wt, 6, msg.get('slip_number'))
                sheet_wt.write(row_wt, 7, msg.get('work_name'))
                sheet_wt.write(row_wt, 8, msg.get('employee_code'))
                sheet_wt.write(row_wt, 9, msg.get('employee_name'))
                sheet_wt.write(row_wt, 10, msg.get('material_name'))
                sheet_wt.write(row_wt, 11, msg.get('material_amount'))
                sheet_wt.write(row_wt, 12, msg.get('water_heating_price'))
                sheet_wt.write(row_wt, 13, msg.get('heating_price'))
                sheet_wt.write(row_wt, 14, msg.get('work_amount'))
                sheet_wt.write(row_wt, 15, msg.get('bill_amount'))
                sheet_wt.write(row_wt, 16, msg.get('total_amount'))
                sheet_wt.write(row_wt, 17, msg.get('error_message'))
                row_wt += 1
            workbook_wt.close()
            xls_content.seek(0)
            xlsx_data = base64.b64encode(xls_content.read())
            self.write({'file': xlsx_data})
            name = 'алдааны_мэдэээ.xlsx'
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/?model=service.payment.xls.reader&id={self.id}&field=file&filename_field={name}&download=true&filename={name}',
                'target': 'self',
                # 'name': name
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Амжилттай!',
                    'message': 'Файл амжилттай орууллаа',
                    'sticky': False,
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }

    def export_template(self):
        return {
                'type': 'ir.actions.act_url',
                'url': f'/ub_kontor/static/xls_template/tulburt_uilchilgee_template.xlsx',
                'target': 'self',
                # 'name': name
            }
