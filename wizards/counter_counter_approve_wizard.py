from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from ..models.ref import ADDRESS_TYPE
import base64
import xlrd
import xlsxwriter
import io
from datetime import datetime, timedelta
from dateutil import parser

class CounterCounterApproveWizard(models.TransientModel):
    _name = 'counter.counter.approve.wizard'
    file = fields.Binary('Excel файл')
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True, default=lambda self: self.env.user.company_id.id)
    address_type = fields.Selection(ADDRESS_TYPE, string='Төрөл', default=lambda self: self.env.user.access_type)
    counter_group_id = fields.Many2one('counter.counter.line.group', string='Идэвхитэй тоолуурын заалт', default=lambda self: self._compute_last_counter_line_group())

    def _compute_last_counter_line_group(self):
        counter_line_group_id = self.env['counter.counter.line.group'].search([('address_type', '=', self.env.user.access_type)], order="year desc, month desc", limit=1)
        if counter_line_group_id.state == 'draft':
            return counter_line_group_id.id
        else:
            return []

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

    def convert_error_list_to_xls(self, error_list=[]):
        xls_content = io.BytesIO()
        workbook_wt = xlsxwriter.Workbook(xls_content)
        sheet_wt = workbook_wt.add_worksheet()
        sheet_wt.write(0, 0, 'Байр')
        sheet_wt.write(0, 1, 'Тоот')
        sheet_wt.write(0, 2, 'Дулааны тоолуур мөн эсэх')
        sheet_wt.write(0, 3, 'Тоолуурын нэр')
        sheet_wt.write(0, 4, 'Хэмжих нэгж')
        sheet_wt.write(0, 5, 'Тоолуурын дугаар')
        sheet_wt.write(0, 6, 'Эхний')
        sheet_wt.write(0, 7, 'Эцийн')
        sheet_wt.write(0, 8, 'Марк')
        sheet_wt.write(0, 9, '1-р лацны дугаар')
        sheet_wt.write(0, 10, '2-р лацны дугаар')
        sheet_wt.write(0, 11, 'Гэрчилгээний дугаар')
        sheet_wt.write(0, 12, 'Баталгаажсан огноо')
        sheet_wt.write(0, 13, 'Тайлбар')
        sheet_wt.write(0, 14, 'Алдааны мэссэж')
        irow = 1
        for error in error_list:
            sheet_wt.write(irow, 0, error.get('apartment_code'))
            sheet_wt.write(irow, 1, error.get('address_address'))
            sheet_wt.write(irow, 2, error.get('counter_category'))
            sheet_wt.write(irow, 3, error.get('counter_name'))
            sheet_wt.write(irow, 4, error.get('measure'))
            sheet_wt.write(irow, 5, error.get('counter_number'))
            sheet_wt.write(irow, 6, error.get('first_counter_line'))
            sheet_wt.write(irow, 7, error.get('last_counter_line'))
            sheet_wt.write(irow, 8, error.get('mark'))
            sheet_wt.write(irow, 9, error.get('seal1'))
            sheet_wt.write(irow, 10, error.get('seal2'))
            sheet_wt.write(irow, 11, error.get('certificate'))
            sheet_wt.write(irow, 12, error.get('approved_date'))
            sheet_wt.write(irow, 13, error.get('description'))
            sheet_wt.write(irow, 14, error.get('error_msg'))
            irow+=1
        workbook_wt.close()
        xls_content.seek(0)
        xlsx_data = base64.b64encode(xls_content.read())
        self.write({'file': xlsx_data})
        name = 'алдааны_мэдэээ.xlsx'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=counter.counter.approve.wizard&id={self.id}&field=file&filename_field={name}&download=true&filename={name}',
            'target': 'self',
            # 'name': name
        }

    def import_file(self):
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data)
        sheet = book.sheet_by_index(0)
        nrows = sheet.nrows
        rowi = 0
        start_import = False
        row_wt = 1
        has_error = False
        error_messages = []
        counter_line_list = []
        while rowi < nrows:
            row = sheet.row(rowi)
            if 'байр' in str(row[0].value).lower():
                start_import = True
                rowi+=1
                row = sheet.row(rowi)
            if start_import:
                apartment_code = self.format_string_data(row[0].value)
                address_address = self.format_string_data(row[1].value)
                is_thermal_counter = bool(row[2].value)
                counter_category = 'thermal_counter' if is_thermal_counter else 'counter'
                counter_name = str(row[3].value).strip()
                measure = row[4].value
                counter_number = self.format_string_data(row[5].value)
                first_counter_line = float(row[6].value or 0.0)
                last_counter_line = float(row[7].value or 0.0)
                mark = row[8].value
                seal1 = row[9].value
                seal2 = row[10].value
                certificate = self.format_string_data(row[11].value)
                approved_date = row[12].value
                description = row[13].value
                if(not approved_date):
                    error_messages.append({
                        'apartment_code': apartment_code,
                        'address_address': address_address,
                        'counter_category': is_thermal_counter,
                        'counter_name': counter_name,
                        'measure': measure,
                        'counter_number': counter_number,
                        'first_counter_line': first_counter_line,
                        'last_counter_line': last_counter_line,
                        'mark': mark,
                        'seal1': seal1,
                        'seal2': seal2,
                        'certificate': certificate,
                        'approved_date': approved_date,
                        'description': description,
                        'error_msg': 'Баталгаажуулсан огноо ороогүй байна'
                    })
                    rowi +=1
                    continue
                if type(approved_date) != str:
                    # approved_date = datetime.fromtimestamp(approved_date).date()
                    approved_date = self.serial_date_to_date(approved_date)
                else:
                    approved_date = parser.parse(approved_date).date()
                address_id = self.env['ref.address'].search([('address', '=', address_address),('apartment_id.code', '=', apartment_code), ('active', '=', True)])
                if not address_id:
                    error_messages.append({
                        'apartment_code': apartment_code,
                        'address_address': address_address,
                        'counter_category': is_thermal_counter,
                        'counter_name': counter_name,
                        'measure': measure,
                        'counter_number': counter_number,
                        'first_counter_line': first_counter_line,
                        'last_counter_line': last_counter_line,
                        'mark': mark,
                        'seal1': seal1,
                        'seal2': seal2,
                        'certificate': certificate,
                        'approved_date': approved_date,
                        'description': description,
                        'error_msg': 'тоот олдсонгүй'
                    })
                    rowi += 1
                    continue
                counter_name_id = self.env['counter.name'].search([('name', 'ilike', counter_name)])
                counter_name_id = sorted(counter_name_id, key=lambda r: len(r.name or ''))
                if not counter_name_id:
                    error_messages.append({
                        'apartment_code': apartment_code,
                        'address_address': address_address,
                        'counter_category': is_thermal_counter,
                        'counter_name': counter_name,
                        'measure': measure,
                        'counter_number': counter_number,
                        'first_counter_line': first_counter_line,
                        'last_counter_line': last_counter_line,
                        'mark': mark,
                        'seal1': seal1,
                        'seal2': seal2,
                        'certificate': certificate,
                        'approved_date': approved_date,
                        'description': description,
                        'error_msg': 'Тоолуурын нэр олдсонгүй'
                    })
                    rowi += 1
                    continue
                else:
                    counter_name_id = counter_name_id[0]
                measure_id =  self.env['uom.uom'].search([('name', 'ilike', measure)], limit=1, order='id desc')
                if not measure_id:
                    error_messages.append({
                        'apartment_code': apartment_code,
                        'address_address': address_address,
                        'counter_category': is_thermal_counter,
                        'counter_name': counter_name,
                        'measure': measure,
                        'counter_number': counter_number,
                        'first_counter_line': first_counter_line,
                        'last_counter_line': last_counter_line,
                        'mark': mark,
                        'seal1': seal1,
                        'seal2': seal2,
                        'certificate': certificate,
                        'approved_date': approved_date,
                        'description': description,
                        'error_msg': 'Хэмжих нэгж олдсонгүй'
                    })
                    rowi += 1
                    continue
                counter_id = None
                # if not counter_number:
                #     counter_id = self.env['counter.counter'].search([('number', '=', counter_number), ('name_id.name', 'ilike', counter_name), ('address_id', '=', address_id.id), ('category', '=', counter_category)])
                # else:
                counter_id = self.env['counter.counter'].search([('name_id.name', '=', counter_name_id.name), ('address_id', '=', address_id.id), ('category', '=', counter_category)])
                if len(counter_id.ids) > 1:
                    error_messages.append({
                        'apartment_code': apartment_code,
                        'address_address': address_address,
                        'counter_category': is_thermal_counter,
                        'counter_name': counter_name,
                        'measure': measure,
                        'counter_number': counter_number,
                        'first_counter_line': first_counter_line,
                        'last_counter_line': last_counter_line,
                        'mark': mark,
                        'seal1': seal1,
                        'seal2': seal2,
                        'certificate': certificate,
                        'approved_date': approved_date,
                        'description': description,
                        'error_msg': f'Ижил нэртэй {len(counter_id.ids)} тоолуур байгаа учир хүлээн авч чадсангүй'
                    })
                    rowi += 1
                    continue
                if(counter_id):
                    counter_id.write({
                        'mark': mark,
                        'seal1': seal1,
                        'seal2': seal2,
                        'certificate': certificate,
                        'approved_date': approved_date,
                        'description': description,
                        'number': counter_number,
                        'registered_date': datetime.now().date(),
                        'end_date': datetime.now().date() + timedelta(days=2190)
                    })
                    counter_line_list+=[{
                        'counter_id': counter_id.id,
                        'first_counter_line': first_counter_line,
                        'last_counter_line': last_counter_line
                    }]
                    print(f"===========================================================================")
                    print(f"updated counter: {counter_id.id}")
                    print(f"name of counter: {counter_name}")
                    print(f"selected counter name: {counter_name_id.name}")
                    print(f"===========================================================================")
                else:
                    error_messages.append({
                        'apartment_code': apartment_code,
                        'address_address': address_address,
                        'counter_category': is_thermal_counter,
                        'counter_name': counter_name,
                        'measure': measure,
                        'counter_number': counter_number,
                        'first_counter_line': first_counter_line,
                        'last_counter_line': last_counter_line,
                        'mark': mark,
                        'seal1': seal1,
                        'seal2': seal2,
                        'certificate': certificate,
                        'approved_date': approved_date,
                        'description': description,
                        'error_msg': 'Тоолуур олдсонгүй'
                    })
                    rowi += 1
                    continue
                    # new_counter = self.env['counter.counter'].create({
                    #     'address_id': address_id.id,
                    #     'name_id': counter_name_id.id,
                    #     'uom_id': measure_id.id,
                    #     'category': counter_category,
                    #     'mark': mark,
                    #     'seal1': seal1,
                    #     'seal2': seal2,
                    #     'certificate': certificate,
                    #     'approved_date': approved_date,
                    #     'description': description,
                    #     'registered_date': datetime.now().date()
                    # })
                    # print(f"===========================================================================")
                    # print(f"created counter: {new_counter.id}")
                    # print(f"name of counter: {counter_name}")
                    # print(f"selected counter name: {counter_name_id.name}")
                    # print(f"===========================================================================")
                    # counter_line_list += [{
                    #     'counter_id': new_counter.id,
                    #     'first_counter_line': first_counter_line,
                    #     'last_counter_line': last_counter_line
                    # }]
            rowi += 1
        self.counter_group_id.create_details()
        group_id = self.counter_group_id.id
        for line in counter_line_list:
            self.env['counter.counter.line'].search([('counter_id', '=', line.get('counter_id')), ('group_id', '=', group_id)]).write({
                'now_counter':line.get('first_counter_line'),
                'last_counter':line.get('last_counter_line'),
                'difference': line.get('last_counter_line', 0.0) - line.get('first_counter_line',0.0)
            })
        if error_messages:
            return self.convert_error_list_to_xls(error_messages)
        else:
            return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Усны тоолуурын баталгаажуулалт амжилттай хийгдлээ',
                'message': f'',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                }
            }
        }

