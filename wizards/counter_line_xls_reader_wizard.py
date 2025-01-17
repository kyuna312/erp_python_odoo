from odoo import api, fields, models, _
import base64
import xlrd
import xlsxwriter
import io
import logging
from itertools import groupby

_logger = logging.getLogger('kontor xls logger:')
class CounterLineXlsReader(models.TransientModel):
    _name = 'counter.line.xls.reader'

    file = fields.Binary('Excel Файл', required=True)

    group_id = fields.Many2one('counter.counter.line.group', 'Group', required=True)


    def upload_file(self):
        _logger.warning("--------------------------------------------------------------------")
        self.env.cr.execute(f"""
            select ccl.id as id, ccl.counter_id as counter_id from counter_counter_line ccl where ccl.group_id = {self.group_id.id}
        """)
        counter_line_datas = self.env.cr.dictfetchall()
        grouped_counter_line_data = groupby(counter_line_datas, key=lambda x: x['counter_id'])
        grouped_counter_line_data = {key: list(group) for key, group in grouped_counter_line_data}
        _logger.warning("------------------------------PREPARED DATA--------------------------------------")

        result_data = []
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data)
        group_id = self.group_id.id
        xls_content = io.BytesIO()
        workbook_wt = xlsxwriter.Workbook(xls_content)
        try:
            sheet = book.sheet_by_index(0)
            sheet_wt = workbook_wt.add_worksheet()
            sheet_wt.write(0,0, 'ID')
            sheet_wt.write(0,1, 'Хэрэглэгчийн код')
            sheet_wt.write(0,2, 'Байрны код')
            sheet_wt.write(0,3, 'Тоот')
            sheet_wt.write(0,4, 'Эзэмшигч код')
            sheet_wt.write(0,5, 'Тоолуурын нэр')
            sheet_wt.write(0,6, 'Тоолуурын дугаар')
            sheet_wt.write(0,7, 'Тоолуурын №')
            sheet_wt.write(0,8, 'Эхний заалт')
            sheet_wt.write(0,9, 'Эцсийн заалт')
            sheet_wt.write(0,10, 'Зөрүү')
            sheet_wt.write(0,11, 'Задгай')
            sheet_wt.write(0,12, 'Алдааны мэссэж')
        except:
            raise ValueError(u'Алдаа', u'Sheet -ны дугаар буруу байна.')
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        row_wt = 1
        has_error = False
        while rowi < nrows:
            try:
                row = sheet.row(rowi)
                if row[0].value in ('External ID', 'Гадаад ID', 'ID'):
                    start_import = True
                    rowi += 1
                    row = sheet.row(rowi)

                if start_import:
                    id = row[0].value
                    address_code = row[1].value
                    apartment_code = row[2].value
                    address_address = row[3].value
                    address_owner = row[4].value
                    counter_name_id = row[5].value
                    counter_number = row[6].value
                    counter_code = row[7].value
                    now_counter = row[8].value
                    last_counter = row[9].value
                    difference = row[10].value
                    fraction = row[11].value
                    line_ids = []
                    if grouped_counter_line_data.get(int(id or 0)):
                        line_ids = [int(l.get('id')) for l in grouped_counter_line_data.get(int(id))]
                    if line_ids:
                        obj = self.env['counter.counter.line'].browse(line_ids)
                        if(obj):
                            obj.write({
                                'last_counter': last_counter,
                                'now_counter': now_counter,
                                'fraction': fraction,
                                'difference': difference,
                            })
                        else:
                            sheet_wt.write(row_wt,0,id)
                            sheet_wt.write(row_wt,1,address_code)
                            sheet_wt.write(row_wt,2,apartment_code)
                            sheet_wt.write(row_wt,3,address_address)
                            sheet_wt.write(row_wt,4,address_owner)
                            sheet_wt.write(row_wt,5,counter_name_id)
                            sheet_wt.write(row_wt,6,counter_number)
                            sheet_wt.write(row_wt,7,counter_code)
                            sheet_wt.write(row_wt,8,now_counter)
                            sheet_wt.write(row_wt,9,last_counter)
                            sheet_wt.write(row_wt,10,difference)
                            sheet_wt.write(row_wt,11,fraction)

                            sheet_wt.write(row_wt, 12,
                                           u'External ID -дахь тоолуурын заалт устсан байна!')
                            row_wt += 1
                    else:
                        sheet_wt.write(row_wt, 0, id)
                        sheet_wt.write(row_wt, 1, address_code)
                        sheet_wt.write(row_wt, 2, apartment_code)
                        sheet_wt.write(row_wt, 3, address_address)
                        sheet_wt.write(row_wt, 4, address_owner)
                        sheet_wt.write(row_wt, 5, counter_name_id)
                        sheet_wt.write(row_wt, 6, counter_number)
                        sheet_wt.write(row_wt, 7, counter_code)
                        sheet_wt.write(row_wt, 8, now_counter)
                        sheet_wt.write(row_wt, 9, last_counter)
                        sheet_wt.write(row_wt, 10, difference)
                        sheet_wt.write(row_wt, 11, fraction)
                        sheet_wt.write(row_wt, 12, u'External ID -дахь бичилт буруу байна. Харгалзах тоолуурын заалтын мэдээгээ дахин татаж авна уу')
                        row_wt += 1
                rowi += 1
            except IndexError:
                raise ValueError('Error', 'Excel sheet must be 2 columned : error on row: %s ' % rowi)
        if(row_wt > 1):
            workbook_wt.close()
            xls_content.seek(0)
            xlsx_data = base64.b64encode(xls_content.read())
            self.write({'file': xlsx_data})
            name = 'алдааны_мэдэээ.xlsx'
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/?model=counter.line.xls.reader&id={self.id}&field=file&filename_field={name}&download=true&filename={name}',
                'target': 'self',
                # 'name': name
            }