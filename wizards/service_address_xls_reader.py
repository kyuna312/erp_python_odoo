from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime
import base64
import xlsxwriter
import xlrd
import io


class ServiceAddressXlsReader(models.TransientModel):
    _name = 'service.address.xls.reader'
    file = fields.Binary('Файл')
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True)

    def format_string_data(self, data):
        if type(data) != str:
            data = float(data)
            if (data.is_integer()):
                data = str(int(data))
            else:
                data = str(data)
        return data

    def import_file(self):
        if (not self.file):
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
        sheet_wt.write(0, 1, 'Байр')
        sheet_wt.write(0, 2, 'Тоот')
        sheet_wt.write(0, 3, 'Он')
        sheet_wt.write(0, 4, 'Сар')
        sheet_wt.write(0, 5, 'Байгууллага')
        sheet_wt.write(0, 6, 'Үйлчилгээ')
        sheet_wt.write(0, 7, 'Утга')
        sheet_wt.write(0, 8, 'Үнэ')
        sheet_wt.write(0, 9, 'Өдөр')
        sheet_wt.write(0, 10, 'НӨАТ тооцох')
        sheet_wt.write(0, 11, 'Тайлбар')
        sheet_wt.write(0, 13, 'Алдааны мэдээлэл')
        error_message = []
        result = []
        while rowi < nrows:
            try:
                row = sheet.row(rowi)
                if row[0].value in ('Д/д', 'д/д', 'Д/Д', 'д/Д'):
                    start_import = True
                    rowi += 1
                    row = sheet.row(rowi)
                if (start_import):
                    number = str(row[0].value)
                    if not number:
                        continue
                    apartment_code = self.format_string_data(row[1].value)
                    address_address = self.format_string_data(row[2].value)
                    year = str(int(row[3].value))
                    month = int(row[4].value)
                    org_name = str(row[5].value)
                    service_name = str(row[6].value)
                    value = float(row[7].value)
                    price = float(row[8].value)
                    days = row[9].value
                    noat = row[10].value
                    description = row[11].value
                    apartment_id = self.env['ref.apartment'].search([('code', '=', apartment_code), ('active', '=', True)], limit=1)
                    if(apartment_id):
                        apartment_id = apartment_id.id
                    else:
                        error_message += [{
                            'number': row[0].value,
                            'apartment_code': apartment_code,
                            'address_address': address_address,
                            'year': year,
                            'month': month,
                            'org_name': org_name,
                            'service_name': service_name,
                            'value': value,
                            'price': price,
                            'days': days,
                            'noat': noat,
                            'description': description,
                            'error_message': 'Байр олдсонгүй'
                        }]
                        rowi += 1
                        continue
                    address_id = self.env['ref.address'].search([('address', '=', address_address), ('active', '=', True), ('apartment_id.code', '=', apartment_code)], order="id desc",limit=1)
                    if(address_id):
                        address_id = address_id.id
                    else:
                        error_message += [{
                            'number': row[0].value,
                            'apartment_code': apartment_code,
                            'address_address': address_address,
                            'year': year,
                            'month': month,
                            'org_name': org_name,
                            'service_name': service_name,
                            'value': value,
                            'price': price,
                            'days': days,
                            'noat': noat,
                            'description': description,
                            'error_message': 'Тоот олдсонгүй'
                        }]
                        rowi += 1
                        continue
                    org_id = self.env['ref.organization'].search([('name', 'ilike', org_name)], order='id desc',limit=1)
                    if(org_id):
                        org_id = org_id.id
                    else:
                        error_message += [{
                            'number': row[0].value,
                            'apartment_code': apartment_code,
                            'address_address': address_address,
                            'year': year,
                            'month': month,
                            'org_name': org_name,
                            'service_name': service_name,
                            'value': value,
                            'price': price,
                            'days': days,
                            'noat': noat,
                            'description': description,
                            'error_message': 'Байгууллага олдсонгүй'
                        }]
                        rowi += 1
                        continue
                    service_id = self.env['ref.service.type'].search([('name', 'ilike', service_name),('org_id', '=', org_id)], order='id desc',limit=1)
                    if(service_id):
                        service_id = service_id.id
                    else:
                        error_message += [{
                            'number': row[0].value,
                            'apartment_code': apartment_code,
                            'address_address': address_address,
                            'year': year,
                            'month': month,
                            'org_name': org_name,
                            'service_name': service_name,
                            'value': value,
                            'price': price,
                            'days': days,
                            'noat': noat,
                            'description': description,
                            'error_message': 'Үйлчилгээ олдсонгүй'
                        }]
                        rowi += 1
                        continue
                    result += [{
                        'address_id': address_id,
                        'year': year,
                        'month': str(month) if month>9 else f"0{month}",
                        'org_id': org_id,
                        'service_type_id': service_id,
                        'value': value,
                        'price': price,
                        'day': days,
                        'is_noat': noat,
                        'description': description,
                        'type': 'additional_service'
                    }]
                rowi += 1
            except IndexError:
                raise ValueError('Error', 'Excel sheet must be 2 columned : error on row: %s ' % rowi)
        self.env['service.address'].create(result)
        if (error_message):
            for msg in error_message:
                sheet_wt.write(row_wt, 0, msg.get('number'))
                sheet_wt.write(row_wt, 1, msg.get('apartment_code'))
                sheet_wt.write(row_wt, 2, msg.get('address_address'))
                sheet_wt.write(row_wt, 3, msg.get('year'))
                sheet_wt.write(row_wt, 4, msg.get('month'))
                sheet_wt.write(row_wt, 5, msg.get('org_name'))
                sheet_wt.write(row_wt, 6, msg.get('service_name'))
                sheet_wt.write(row_wt, 7, msg.get('value'))
                sheet_wt.write(row_wt, 8, msg.get('price'))
                sheet_wt.write(row_wt, 9, msg.get('days'))
                sheet_wt.write(row_wt, 10, msg.get('noat'))
                sheet_wt.write(row_wt, 11, msg.get('description'))
                sheet_wt.write(row_wt, 12, msg.get('error_message'))
                row_wt += 1
            workbook_wt.close()
            xls_content.seek(0)
            xlsx_data = base64.b64encode(xls_content.read())
            self.write({'file': xlsx_data})
            name = 'алдааны_мэдэээ.xlsx'
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/?model=service.address.xls.reader&id={self.id}&field=file&filename_field={name}&download=true&filename={name}',
                'target': 'self',
                # 'name': name
            }
