from odoo import api, fields, models, _
from odoo.tools import flatten
from ..models.ref import ADDRESS_TYPE
import base64
import xlrd
import xlsxwriter
import io
class RefAddressAdjustmentXlsReader(models.TransientModel):
    _name = 'ref.address.adjustment.xls.reader'
    file = fields.Binary('Файл')
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True, default=lambda self: self.env.user.company_id.id)
    address_type = fields.Selection(ADDRESS_TYPE, 'Тоотын төрөл', required=True, default=lambda self: self.env.user.access_type)

    def import_file(self):
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data)
        try:
            sheet = book.sheet_by_index(0)
        except:
            raise ValueError(u'Алдаа', u'Sheet -ны дугаар буруу байна.')
        nrows = sheet.nrows
        start_import = False
        rowi = 0
        company_id = self.company_id.id
        address_type = self.address_type
        inspector_ids =  self.env.ref('ub_kontor.group_kontor_inspector').users.ids
        error_list = []
        while rowi < nrows:
            row = sheet.row(rowi)
            if row[0].value  == 'Байцаагч':
                start_import = True
                rowi += 1
                row = sheet.row(rowi)
            if start_import:
                inspector_name:str = str(row[0].value).strip()
                address:str = str(row[1].value).strip()
                user_name:str = str(row[2].value or '').strip()
                family:int = int(row[3].value or 0)
                square:float = float(row[4].value or 0.0)
                register:str = str(row[5].value or '').strip()
                phone:str = str(row[6].value or '').strip()
                public_ownership_square:float = float(row[7].value or 0.0)
                gradge_square:float = float(row[8].value or 0.0)
                inspector = self.env['hr.employee'].search([('company_id', '=', company_id), ('name', 'ilike', inspector_name), ('user_id', 'in', inspector_ids), ('active', '=', True)])
                if len(inspector) > 1 and inspector_name:
                    error_list.append({
                        'inspector_name': inspector_name,
                        'address': address,
                        'user_name': user_name,
                        'family': family,
                        'square': square,
                        'register': register,
                        'phone': phone,
                        'public_ownership_square': public_ownership_square,
                        'gradge_square': gradge_square,
                        'msg': 'Оруулсан өгөгдөлтэй ижил нэртэй байцаагч олон байна!',
                    })
                    rowi+=1
                    continue
                if not inspector and inspector_name:
                    error_list.append({
                        'inspector_name': inspector_name,
                        'address': address,
                        'user_name': user_name,
                        'family': family,
                        'square': square,
                        'register': register,
                        'phone': phone,
                        'public_ownership_square': public_ownership_square,
                        'gradge_square': gradge_square,
                        'msg': 'Оруулсан өгөгдөлтэй адил байцаагч олдсонгүй!',
                    })
                    rowi+=1
                    continue
                address_address = address.split('/')[1]
                apartment_code = address.split('/')[0]
                address_id = self.env['ref.address'].search([('address','=', address_address), ('apartment_code', '=', apartment_code), ('active', '=', True)])
                if not address_id:
                    error_list.append({
                        'inspector_name': inspector_name,
                        'address': address,
                        'user_name': user_name,
                        'family': family,
                        'square': square,
                        'register': register,
                        'phone': phone,
                        'public_ownership_square': public_ownership_square,
                        'gradge_square': gradge_square,
                        'msg': 'Тоот олдсонгүй олдсонгүй!',
                    })
                    rowi += 1
                    continue
                if len(address_id) > 1:
                    error_list.append({
                        'inspector_name': inspector_name,
                        'address': address,
                        'user_name': user_name,
                        'family': family,
                        'square': square,
                        'register': register,
                        'phone': phone,
                        'public_ownership_square': public_ownership_square,
                        'gradge_square': gradge_square,
                        'msg': 'Оруулсан өгөгдөлтэй ижил тоот олон байна!',
                    })
                    rowi += 1
                    continue
                if square > 0.0 or public_ownership_square > 0.0 or gradge_square > 0.0:
                    self.env['ref.address.square'].search([('address_id', '=', address_id.id)]).write({
                        'state': 'deactive'
                    })
                    self.env['ref.address.square'].create({
                        'address_id': address_id.id,
                        'square': square,
                        'public_ownership_square': public_ownership_square,
                        'gradge_square': gradge_square,
                        'state': 'active'
                    })
                if user_name or family or register or phone:
                    self.env['ref.address.user.history'].search([('address_id', '=', address_id.id)]).write({
                        'state': 'before'
                    })
                    self.env['ref.address.user.history'].create({
                        'address_id': address_id.id,
                        'state': 'now',
                        'name': user_name,
                        'phone': phone,
                        'register': register
                    })
                    self.env['ref.address.family'].search([('address_id', '=', address_id.id)]).write({
                        'state': 'deactive'
                    })
                    self.env['ref.address.family'].create({
                        'state': 'active',
                        'family': family,
                        'description': user_name,
                        'address_id': address_id.id
                    })
                    address_id.write({
                        'name': user_name,
                        'phone': phone,
                        'sms': phone,
                        'family': family
                    })
            rowi += 1
        if error_list:
            return self.convert_error_list_to_xls(error_list)
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Тоотын өөрчлөлт амжилттай хийгдлээ',
                    'message': f'',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }
    def convert_error_list_to_xls(self, error_list):
        xls_content = io.BytesIO()
        workbook_wt = xlsxwriter.Workbook(xls_content)
        sheet_wt = workbook_wt.add_worksheet()
        sheet_wt.write(0, 0, 'Байцаагч')
        sheet_wt.write(0, 1, 'Байр/Тоот')
        sheet_wt.write(0, 2, 'Нэр')
        sheet_wt.write(0, 3, 'Ам Бүл')
        sheet_wt.write(0, 4, 'Талбай хэмжээ')
        sheet_wt.write(0, 5, 'Регистэр дугаар')
        sheet_wt.write(0, 6, 'Утас')
        sheet_wt.write(0, 7, 'Нийтийн эзэмшил')
        sheet_wt.write(0, 8, 'Граж талбай')
        sheet_wt.write(0, 9, 'Алдааны мэдээ')
        rowi = 1
        for error in error_list:
            sheet_wt.write(rowi, 0, error.get('inspector_name'))
            sheet_wt.write(rowi, 1, error.get('address'))
            sheet_wt.write(rowi, 2, error.get('user_name'))
            sheet_wt.write(rowi, 3, error.get('family'))
            sheet_wt.write(rowi, 4, error.get('square'))
            sheet_wt.write(rowi, 5, error.get('register'))
            sheet_wt.write(rowi, 6, error.get('phone'))
            sheet_wt.write(rowi, 7, error.get('public_ownership_square'))
            sheet_wt.write(rowi, 8, error.get('gradge_square'))
            sheet_wt.write(rowi, 9, error.get('msg'))
            rowi += 1
        workbook_wt.close()
        xls_content.seek(0)
        xlsx_data = base64.b64encode(xls_content.read())
        self.write({'file': xlsx_data})
        name = 'алдааны_мэдэээ.xlsx'
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model={self._name}&id={self.id}&field=file&filename_field={name}&download=true&filename={name}',
            'target': 'self',
            # 'name': name
        }

