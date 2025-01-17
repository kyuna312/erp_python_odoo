from odoo import api, fields, models, _
from datetime import datetime, timedelta
from odoo import tools
from odoo.exceptions import ValidationError, UserError
import json
import base64
from itertools import groupby
from operator import itemgetter, index
import logging
from typing import List
import xlrd
import io
import pytz
from .ref import ADDRESS_TYPE
from dateutil import parser
import psycopg2
_logger = logging.getLogger('AAA:')


class FloatConverter(models.AbstractModel):
    _inherit = 'ir.qweb.field.float'

    @api.model
    def value_to_html(self, value, options):
        result = super(FloatConverter, self).value_to_html(value, options)
        if (type(result) == str):
            result = result.replace("'", ",")
        return result


def get_years():
    year_list = []
    curr_year = int(datetime.now().strftime('%Y'))
    for i in range(curr_year, 2013, -1):
        year_list.append((str(i), str(i)))
    return year_list


def change_timezone_to_utc(timezone, date_time):
    local_timezone = pytz.timezone(timezone)
    local_datetime = local_timezone.localize(date_time)
    return local_datetime.astimezone(pytz.utc).replace(tzinfo=None)


def convert_utc_to_timezone(utc_dt, target_timezone):
    if utc_dt.tzinfo is None:
        utc_dt = pytz.utc.localize(utc_dt)
    target_tz = pytz.timezone(target_timezone)
    converted_dt = utc_dt.astimezone(target_tz)
    return converted_dt


class PayBank(models.Model):
    _name = 'pay.bank'
    _description = 'Банк'
    _order = 'id desc'
    name = fields.Char('Нэр', required=True)
    code = fields.Char('Код', required=True)


class PayAccount(models.Model):
    _name = 'pay.bank.account'
    _description = 'Данс'
    name = fields.Char('Нэр', required=True)
    number = fields.Char('Дансны дугаар', required=True)
    MATCH_LABEL = [
        ('contains', 'Агуулсан'),
        ('not_contains', 'Агуулаагүй'),
        ('match_regex', 'Regex')
    ]
    match_label = fields.Selection(MATCH_LABEL, string='Label')
    match_label_param = fields.Char('Label param')
    short_code = fields.Char('Богино код', required=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True)
    bank_id = fields.Many2one('pay.bank', string='Банк', required=True)
    # reconcile = fields.Boolean('Тулагалт хийх эсэх', default=True) # unnecessary
    match_reconcile = fields.Boolean('Тулагалт хийх эсэх', default=True)
    """
        incoming (Орлого) - Тулгалт хийж нэхэмжлэл хаах боломжтой төлбөр.
        outgoing (Зарлага) - Тулгалт хийх нэхэмжлэл бүртгэх боломжгүй төлбөр.
        social_in (Онлайн төлбөрийн хэрэгслээс орж ирсэн төлбөр) - Тулгалт хийх боломжгүй данс. 
                                                                   Энэ данс нь Банкны хуулга дээр орж ирж байгаа онлайн гүйлгээг түгжихэд хэрэглэж байгаа 
                                                                   (Онлайн хэлбэрээр төлбөр төлөх үед төлөлт /Тулгалт/ хийж байгаа).
        loss_in (Алданги) - Тулгалт хийх боломжгүй данс. 
                            Энэ данс нь алдангид төлөгдсөн төлбөрүүдийг бүртгэж түгжих байдлаар ашиглагдаж байгаа.
    """
    type = fields.Selection([('incoming', 'Орлого'), ('outgoing', 'Зарлага'),
                             ('social_in', 'Цахимаар бүртгэгдсэн орлого (Банкны хуулганд ашиглах)'),
                             ('loss_in', 'Алданги')], string='Төрөл', default='incoming',
                            required=True)
    active = fields.Boolean('Идэвхтэй', default=True)

    @api.model
    def create(self, vals_list):
        result = super(PayAccount, self).create(vals_list)
        return result

    def name_get(self):
        result = []
        for obj in self:
            name = f"{obj.name} {obj.number}"
            result.append((obj.id, name))
        return result


BANK_STATEMENT_STATE = [('draft', 'Ноорог'), ('confirmed', 'Батлагдсан'), ('done', 'Дууссан')]


class PayBankStatement(models.Model):
    _name = 'pay.bank.statement'
    _description = 'Банкны хуулга'
    name = fields.Char('Нэр', store=True, readonly=False, compute="_compute_name")
    account_id = fields.Many2one('pay.bank.account', 'Данс', required=True)
    date = fields.Date('Огноо', default=fields.Date.today)
    line_ids = fields.One2many('pay.bank.statement.line', 'statement_id', 'Бүх мөр')
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True, default=lambda self: self.env.user.company_id.id)
    state = fields.Selection(BANK_STATEMENT_STATE, string="Төлөв", default='draft')
    FILE_TYPE_CHOICES = [
        ('statement_bank_json', 'Төрийн банк JSON'),
        ('khaan_bank_xls', 'Хаан банкны xls'),
        ('golomt_bank_xls', 'Голомт банкны xls'),
        ('capitron_bank_xls', 'Капитрон банкны xls'),
        ('statement_bank_xls', 'Төрийн банкны xls')
    ]
    statement_file_type = fields.Selection(FILE_TYPE_CHOICES, string='Файл төрөл', required=True)

    file = fields.Binary('Файл', required=True)
    process = fields.Float('Processing', compute="_compute_process", store=False)
    line_ids_by_address_type = fields.One2many('pay.bank.statement.line', 'statement_id', 'мөр',
                                               domain=lambda self: ['|', ('address_id', '=', None), (
                                                   'address_id.type', '=', self.env.user.access_type)])
    payment_created_count = fields.Integer('Төлбөр үүссэн', store=False, compute="_compute_process")
    payment_uncreated_count = fields.Integer('Төлбөр үүсээгүй', store=False, compute="_compute_process")

    total_income_amount = fields.Float('Нийт орлого', compute="compute_total_amount")
    total_outgoing_amount = fields.Float('Нийт зарлага', compute="compute_total_amount")

    user_access_type = fields.Selection(ADDRESS_TYPE, string='Хэрэглэгчийн хандах төрөл', compute="compute_user_access")
    created_payment_sum = fields.Float('Үүссэн төлбөр', compute='compute_created_payment_sum')

    def reconcile(self):
        for obj in self:
            return {
                'name': _('Reconcile'),
                'type': 'ir.actions.act_window',
                'target': 'current',
                'view_mode': 'form',
                'res_model': 'pay.bank.statement.reconciliation.wizard',
                'context': {
                    'default_statement_id': obj.id
                }
            }

    def compute_user_access(self):
        user_type = self.env.user.access_type
        for obj in self:
            obj.user_access_type = user_type

    def compute_created_payment_sum(self):
        user_type = self.env.user.access_type

        for obj in self:
            query = f"""
                   select statement_line.statement_id as id, sum(payment.amount) as sum_amount  from pay_address_payment payment
                   inner join ref_address address on address.id = payment.address_id and address.type = '{user_type}'
                   inner join pay_bank_statement_line statement_line on statement_line.id = payment.statement_line_id and statement_line.statement_id = {obj.id}
                   group by statement_line.statement_id
               """
            self.env.cr.execute(query)
            data = self.env.cr.dictfetchall()
            obj.created_payment_sum = data[0].get('sum_amount') if data else 0.0

    def compute_total_amount(self):
        ids = self.ids
        query = f"""
            SELECT line.statement_id as statement_id,  sum(line.amount) as amount FROM pay_bank_statement_line line 
            where line.amount > 0.0 and line.statement_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
            group by line.statement_id
        """
        self.env.cr.execute(query)
        income_datas = self.env.cr.dictfetchall()
        income_datas = groupby(income_datas, key=lambda x: x['statement_id'])
        income_datas = {key: list(group) for key, group in income_datas}
        query = f"""
            SELECT line.statement_id as statement_id,  sum(line.amount) as total_amount FROM pay_bank_statement_line line 
            where line.amount < 0.0 and line.statement_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} 
            group by line.statement_id
        """
        self.env.cr.execute(query)
        out_going_datas = self.env.cr.dictfetchall()
        out_going_datas = groupby(out_going_datas, key=lambda x: x['statement_id'])
        out_going_datas = {key: list(group) for key, group in out_going_datas}
        for obj in self:
            id = obj.id
            obj.total_income_amount = income_datas.get(id)[0].get('amount') if income_datas.get(id) else 0.0
            obj.total_outgoing_amount = out_going_datas.get(id)[0].get('amount') if out_going_datas.get(id) else 0.0

    @api.depends('date', 'account_id')
    def _compute_name(self):
        for obj in self:
            obj.name = f"{obj.date}-{obj.account_id.short_code}-{obj.account_id.number}"

    def _compute_process(self):
        ids = self.ids
        query = f"""
           select b_statement.id as id, count(st_line.id) as created_payment_count  
            from pay_bank_statement b_statement
            left join pay_bank_statement_line st_line on st_line.statement_id = b_statement.id
            left join pay_address_payment payment on payment.statement_line_id = st_line.id
            where b_statement.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} 
            group by b_statement.id
        """

        self.env.cr.execute(query)
        payment_count_list = self.env.cr.dictfetchall()
        payment_count_list = groupby(payment_count_list, key=lambda x: x['id'])
        payment_count_list = {key: list(group) for key, group in payment_count_list}

        query = f"""
            select statement_line.statement_id as id, count( case when payment.id is null then 1 end ) as uncreated_count from pay_bank_statement_line statement_line
            left join pay_address_payment payment on payment.statement_line_id = statement_line.id
            where statement_line.statement_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} 
            group by statement_line.statement_id 
        """
        self.env.cr.execute(query)
        payment_uncreated_count = self.env.cr.dictfetchall()
        payment_uncreated_count = groupby(payment_uncreated_count, key=lambda x: x['id'])
        payment_uncreated_count = {key: list(group) for key, group in payment_uncreated_count}

        for obj in self:
            try:
                id = obj.id
                total_line_count = len(obj.line_ids.ids)
                obj.payment_uncreated_count = payment_uncreated_count.get(id)[0].get('uncreated_count')
                created_count = total_line_count - obj.payment_uncreated_count
                obj.payment_created_count = created_count
                result: float = created_count * 100 / total_line_count
                obj.process = int(str(result).split(".")[0])
            except Exception as ex:
                obj.process = 0.0
                obj.payment_created_count = 0.0
                obj.payment_uncreated_count = 0.0

    def get_partner_by_code(self, code):
        address = self.env['ref.address'].search([('code', '=', code), ('active', '=', True)], order="id desc", limit=1)
        return address.id if address else None

    def import_statement_bank_json(self):
        self.line_ids.unlink()
        try:
            json_data_list = json.loads(base64.b64decode(self.file))
        except Exception as ex:
            raise UserError('Файл нь json файл эсэхыг шалгаарай')

        self.line_ids = [(0, 0, {
            # "datetime": change_timezone_to_utc('Asia/Ulaanbaatar',datetime.strptime(data.get('TDATE'), '%Y/%m/%d %H:%M:%S')),
            "datetime": change_timezone_to_utc('Asia/Ulaanbaatar', parser.parse(data.get('TDATE'))),
            "payment_ref": data.get('TRDESCR'),
            "ref": f"{data.get('FACT')}/{data.get('BANKCODE')}",
            "address_id": self.get_partner_by_code(data.get('CCODE')),
            "amount": float(data.get('INCOME')),
            "ccode": data.get('CCODE')
        }) for data in json_data_list]

    def import_khaan_bank_xls(self):
        self.line_ids.unlink()
        # self.file
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data)
        sheet = book.sheet_by_index(0)
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        vals = []
        while rowi < nrows:
            row = sheet.row(rowi)
            if row[0].value in ('Гүйлгээний огноо'):
                start_import = True
                rowi += 1
                row = sheet.row(rowi)
            if start_import:
                # serviced_date = datetime.strptime(row[0].value, '%Y/%m/%d %H:%M')
                serviced_date = parser.parse(row[0].value)
                local_timezone = pytz.timezone("Asia/Ulaanbaatar")
                local_datetime = local_timezone.localize(serviced_date)
                serviced_date = local_datetime.astimezone(pytz.utc).replace(tzinfo=None)
                branch = row[1].value
                primary_residual = row[2].value
                debit = float(str(row[3].value).replace(',', '')) if row[3].value else 0.0
                credit = float(str(row[4].value).replace(',', '')) if row[4].value else 0.0
                residual = float(str(row[5].value).replace(',', '')) if row[5].value else 0.0
                payment_ref = row[6].value
                counterpart_account = row[7].value
                vals += [{
                    "datetime": serviced_date,
                    "payment_ref": payment_ref,
                    "ref": payment_ref,
                    # "address_id": '',
                    "amount": credit if credit > 0 else debit,
                    'statement_id': self.id
                }]
            rowi += 1
        self.env['pay.bank.statement.line'].create(vals)

    def import_capitron_bank_xls(self):
        self.line_ids.unlink()
        # self.file
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data)
        sheet = book.sheet_by_index(0)
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        vals = []
        while rowi < nrows:
            row = sheet.row(rowi)
            if row[0].value in ('Гүйлгээний огноо'):
                start_import = True
                rowi += 1
                row = sheet.row(rowi)
            if start_import:
                try:

                    # serviced_date = datetime.strptime(row[0].value, '%m/%d/%Y %I:%M:%S %p')
                    serviced_date = parser.parse(row[0].value)
                    local_timezone = pytz.timezone("Asia/Ulaanbaatar")
                    local_datetime = local_timezone.localize(serviced_date)
                    serviced_date = local_datetime.astimezone(pytz.utc).replace(tzinfo=None)
                except Exception as ex:
                    start_import = False
                    continue
                teller = row[1].value
                # primary_residual = row[2].value
                debit = float(str(row[2].value).replace(',', '')) if row[2].value else 0.0
                credit = (-1) * float(str(row[3].value).replace(',', '')) if row[3].value else 0.0
                residual = float(str(row[4].value).replace(',', '')) if row[4].value else 0.0
                counterpart_account = row[5].value
                payment_ref = row[7].value
                vals += [{
                    "datetime": serviced_date,
                    "payment_ref": payment_ref,
                    "ref": payment_ref,
                    # "address_id": '',
                    "amount": debit or credit,
                    'statement_id': self.id
                }]
            rowi += 1
        self.env['pay.bank.statement.line'].create(vals)

    def import_golomt_bank_xls(self):
        self.line_ids.unlink()
        # self.file
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data)
        sheet = book.sheet_by_index(0)
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        vals = []
        while rowi < nrows:
            row = sheet.row(rowi)
            if row[0].value in ('Гүйлгээний огноо',):
                start_import = True
                rowi += 1
                row = sheet.row(rowi)
            if start_import:
                # serviced_date = datetime.strptime(row[0].value, '%Y-%m-%dT%H:%M:%S')
                serviced_date = parser.parse(row[0].value)
                local_timezone = pytz.timezone('Asia/Ulaanbaatar')
                serviced_date = local_timezone.localize(serviced_date)
                serviced_date = serviced_date.astimezone(pytz.utc)
                serviced_date = serviced_date.strftime('%Y-%m-%d %H:%M:%S')

                # branch = row[1].value
                primary_residual = row[1].value
                debit = float(str(row[3].value).replace(',', '')) if row[3].value else 0.0
                credit = (-1) * float(str(row[2].value).replace(',', '')) if row[2].value else 0.0
                residual = float(str(row[4].value).replace(',', '')) if row[4].value else 0.0
                payment_ref = row[5].value
                counterpart_account = row[6].value

                vals += [{
                    "datetime": serviced_date,
                    "payment_ref": payment_ref,
                    "ref": payment_ref,
                    # "address_id": '',
                    "amount": debit or credit,
                    'statement_id': self.id
                }]
            rowi += 1
        self.env['pay.bank.statement.line'].create(vals)

    def import_statement_bank_xls(self):
        self.line_ids.unlink()
        # self.file
        decoded_data = base64.b64decode(self.file)
        book = xlrd.open_workbook(file_contents=decoded_data)
        sheet = book.sheet_by_index(0)
        rowi = 0
        nrows = sheet.nrows
        start_import = False
        vals = []
        id = self.id
        while rowi < nrows:
            row = sheet.row(rowi)
            if 'огноо' in row[0].value:
                start_import = True
                rowi += 1
                row = sheet.row(rowi)
            if start_import and not row[0].value:
                break
            if start_import:
                serviced_date = f"{row[0].value} {row[1].value}:00"
                # serviced_date = datetime.strptime(serviced_date, '%Y-%m-%d %H:%M:%S')
                serviced_date = parser.parse(serviced_date)
                local_timezone = pytz.timezone('Asia/Ulaanbaatar')
                serviced_date = local_timezone.localize(serviced_date)
                serviced_date = serviced_date.astimezone(pytz.utc)
                serviced_date = serviced_date.strftime('%Y-%m-%d %H:%M:%S')

                payment_ref = row[4].value
                ref = f"{row[2].value}/{row[8].value}"
                debit = row[5].value
                credit = -1 * (row[6].value)

                vals += [{
                    "datetime": serviced_date,
                    "payment_ref": payment_ref,
                    "ref": ref,
                    # "address_id": '',
                    "amount": debit or credit,
                    'statement_id': id
                }]
            rowi += 1
        self.env['pay.bank.statement.line'].create(vals)
        return True

    def show_payment_list(self):
        for obj in self:
            query = f"""
                select payment.id as payment_id from pay_bank_statement b_statement
                inner join pay_bank_statement_line st_line on st_line.statement_id = b_statement.id
                inner join pay_address_payment payment on payment.statement_line_id = st_line.id
                where b_statement.id = {obj.id}
                group by payment.id
            """
            self.env.cr.execute(query)
            payment_list = self.env.cr.dictfetchall()
            payment_ids = [payment.get('payment_id') for payment in payment_list]
            return {
                'name': _('Төлбөрүүд'),
                'type': 'ir.actions.act_window',
                'target': 'current',
                'view_mode': 'tree,form',
                'res_model': 'pay.address.payment',
                'domain': [('id', 'in', payment_ids)]
            }

    def import_file(self):
        for obj in self:
            if (obj.statement_file_type == 'statement_bank_json'):
                obj.import_statement_bank_json()
                obj.find_address()
            if (obj.statement_file_type == 'khaan_bank_xls'):
                obj.import_khaan_bank_xls()
            if (obj.statement_file_type == 'golomt_bank_xls'):
                obj.import_golomt_bank_xls()
            if (obj.statement_file_type == 'capitron_bank_xls'):
                obj.import_capitron_bank_xls()
            if (obj.statement_file_type == 'statement_bank_xls'):
                obj.import_statement_bank_xls()
                obj.find_address()

    def write(self, vals):
        result = super(PayBankStatement, self).write(vals)
        return result

    def done(self):
        for obj in self:
            query = f"""
                 SELECT pbsl.id as id, pbsl.statement_id as statement_id, pbsl.payment_ref as payment_ref, 
                       pbsl.datetime::DATE as datetime, pbsl.address_id as address_id, pbsl.amount as amount, pbsl.state as state, 
                    pbsl.ccode as ccode, pbs.account_id as account_id
                FROM pay_bank_statement_line pbsl
                INNER JOIN pay_bank_statement pbs on pbs.id = pbsl.statement_id and pbs.id = {obj.id}
                left join 
                (select pap.statement_line_id as statement_line_id, count(pap.id) as count from pay_address_payment pap group by pap.statement_line_id) pap on pap.statement_line_id = pbsl.id 
                WHERE coalesce(pap.count,0) = 0 and pbsl.amount > 0.0
                group by pbsl.id, pbs.id
            """
            self.env.cr.execute(query)
            lines_create = self.env.cr.dictfetchall()
            if (not lines_create):
                obj.state = 'done'

    def create_payment(self):
        for obj in self:
            obj.line_ids.create_payment()
            obj.done()

    def finish(self):
        for obj in self:
            obj.state = 'done'

    def confirm(self):
        for obj in self:
            query = f"""
                 SELECT pbsl.id as id, pbsl.statement_id as statement_id, pbsl.payment_ref as payment_ref, 
                       pbsl.datetime::DATE as datetime, pbsl.address_id as address_id, pbsl.amount as amount, pbsl.state as state, 
                    pbsl.ccode as ccode, pbs.account_id as account_id
                FROM pay_bank_statement_line pbsl
                INNER JOIN pay_bank_statement pbs on pbs.id = pbsl.statement_id and pbs.id = {obj.id}
                left join 
                (select pap.statement_line_id as statement_line_id, count(pap.id) as count from pay_address_payment pap group by pap.statement_line_id) pap on pap.statement_line_id = pbsl.id 
                WHERE coalesce(pap.count,0) = 0
                group by pbsl.id, pbs.id
            """
            self.env.cr.execute(query)
            lines_create = self.env.cr.dictfetchall()
            obj.reconcile_all_payments()
            if (lines_create):
                obj.state = 'confirmed'
            else:
                raise UserError('Бүх мөрд төлбөр үүссэн байна')

    def find_address(self):
        for obj in self:
            if (obj.statement_file_type == 'statement_bank_json'):
                obj.line_ids.find_address(company_id=obj.company_id.id)
            elif (obj.statement_file_type == 'statement_bank_xls'):
                obj.line_ids.find_address(company_id=obj.company_id.id, method='payment_ref')
        return True

    def reconcile_all_payments(self):
        for obj in self:
            query = f"""
                select payment.id as payment_id from pay_bank_statement b_statement
                inner join pay_bank_statement_line st_line on st_line.statement_id = b_statement.id
                inner join pay_address_payment payment on payment.statement_line_id = st_line.id
                inner join ref_address address on address.id = payment.address_id and address.type = '{self.env.user.access_type}'
                where b_statement.id = {obj.id}
                group by payment.id
            """
            self.env.cr.execute(query)
            payment_list = self.env.cr.dictfetchall()
            payment_ids = [payment.get('payment_id') for payment in payment_list]
            self.env['pay.address.payment'].browse(payment_ids).register_invoices()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Тулгалт хийгдсэн',
                    'message': f'',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }

    def unlink(self):
        for obj in self:
            obj.line_ids.unlink()
        return super(PayBankStatement, self).unlink()

    @api.onchange('statement_file_type')
    def _onchange_statement_file_type(self):
        for obj in self:
            obj.account_id = None
            domain_name = ''
            if obj.statement_file_type in ('statement_bank_json', 'statement_bank_xls'):
                domain_name = 'Төр'
            if obj.statement_file_type == 'khaan_bank_xls':
                domain_name = 'Хаан'
            if obj.statement_file_type == 'golomt_bank_xls':
                domain_name = 'Голомт'
            if obj.statement_file_type == 'capitron_bank_xls':
                domain_name = 'Капитрон'
            return {
                'domain': {
                    'account_id': [('bank_id.name', 'ilike', domain_name), ('type', '=', 'incoming')]
                }
            }


class PayBankStatementLine(models.Model):
    _name = 'pay.bank.statement.line'
    _description = 'Банкны хуулгын мөр'
    _sql_constraints = [
        ('bank_statement_line_uniq', 'unique(payment_ref, amount, datetime)', 'Банкны хуулга давхардаж байна'),
    ]
    statement_id = fields.Many2one('pay.bank.statement', 'Банкны хуулга', required=True, ondelete="cascade")
    payment_ref = fields.Char('Гүйлгээний утга', required=True)
    ref = fields.Char('Лавлах', required=True)
    datetime = fields.Datetime('Огноо')
    address_id = fields.Many2one('ref.address', 'Хаяг')
    amount = fields.Float('Дүн', readonly=True)
    # used_amount = fields.Float('Хэрэглэсэн дүн', default=0.0)
    state = fields.Selection([('draft', 'Ноорог'), ('confirmed', 'Батлагдсан'), ], string="Төлөв",
                             related="statement_id.state", store=True)
    payment_id = fields.Many2one('pay.address.payment', 'Төлбөр', store=False, compute="_compute_payment_id")
    ccode = fields.Char('ccode')
    address_type = fields.Selection(ADDRESS_TYPE, string="Тоотын төрөл", related="address_id.type", store=True)
    duplicated = fields.Boolean('Давхарсан эсэх', store=False, compute="compute_duplicated")

    @api.onchange('address_id')
    def onchange_address_id(self):
        for obj in self:
            payment_list = self.env['pay.address.payment'].sudo().search([('statement_line_id', 'in', obj.ids)])
            for payment in payment_list:
                if payment.state in ('draft', 'confirmed'):
                    payment.write({
                        'address_id': obj.address_id.id
                    })
                else:
                    raise UserError('Холбоотой төлбөрт тулгалт хийгдсэн байна')

    def compute_duplicated(self):
        ids = self.ids
        query = f"""
             SELECT st_line.id as id, count( case when duplicated_line.id > 0 then 1 end) as count  FROM pay_bank_statement_line st_line
            LEFT JOIN pay_bank_statement_line duplicated_line on duplicated_line.id != st_line.id and st_line.payment_ref = duplicated_line.payment_ref and st_line.amount = duplicated_line.amount and st_line.datetime = duplicated_line.datetime 
            WHERE st_line.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
            GROUP BY st_line.id 
        """
        self.env.cr.execute(query)
        data_list = self.env.cr.dictfetchall()
        data_list = groupby(data_list, key=lambda x: x['id'])
        data_list = {key: list(group) for key, group in data_list}
        for obj in self:
            res = data_list.get(obj.id)[0].get('count') if data_list.get(obj.id) else 0
            obj.duplicated = True if res > 0 else False

    def find_address(self, company_id=None, method='ccode'):
        ids = self.ids
        if method == 'ccode':
            self.env.cr.execute(f"""
                SELECT pbsl.id as id, max(ra.id) as address_id FROM pay_bank_statement_line pbsl 
                left join ref_address ra on ra.code = pbsl.ccode and ra.active = true and ra.company_id = {company_id if company_id else self.env.user.company_id.id}
                where pbsl.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and pbsl.address_id is null
                group by pbsl.id
            """)
            address_data = self.env.cr.dictfetchall()
            address_data = groupby(address_data, key=lambda x: x['id'])
            address_data = {key: list(group) for key, group in address_data}
            for obj in self:
                id = obj.id
                if address_data.get(id) and address_data.get(id)[0].get('address_id'):
                    obj.address_id = address_data.get(id)[0].get('address_id')
        elif method == 'payment_ref':
            self.env.cr.execute(f"""
                select statement_line.id as id, max(address.id) as address_id from pay_bank_statement_line  statement_line
                inner join ref_address address on statement_line.payment_ref ilike concat(address.code, '_%') and address.company_id = {company_id if company_id else self.env.user.company_id.id} and address.active = true
                group by statement_line.id
            """)
            address_data = self.env.cr.dictfetchall()
            address_data = groupby(address_data, key=lambda x: x['id'])
            address_data = {key: list(group) for key, group in address_data}
            for obj in self:
                id = obj.id
                if address_data.get(id) and address_data.get(id)[0].get('address_id'):
                    obj.address_id = address_data.get(id)[0].get('address_id')

    def _compute_payment_id(self):
        ids = self.ids
        self.env.cr.execute(f"""SELECT id as id, statement_line_id as statement_line_id 
                FROM pay_address_payment WHERE statement_line_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}""")
        datas = self.env.cr.dictfetchall()
        grouped_data = groupby(datas, key=lambda x: x['statement_line_id'])
        datas = {key: list(group) for key, group in grouped_data}
        for obj in self:
            obj.payment_id = datas.get(obj.id)[0].get('id') if datas.get(obj.id) else None

    def create_payment(self):
        ids = self.ids
        if (ids):
            confirmed_ids = []
            # query = f"""
            #     SELECT pbsl.id as id, pbsl.statement_id as statement_id, pbsl.payment_ref as payment_ref,
            #            pbsl.datetime as datetime, pbsl.address_id as address_id, pbsl.amount as amount, pbsl.state as state,
            #         pbsl.ccode as ccode, pbs.account_id as account_id
            #     FROM pay_bank_statement_line pbsl
            #     INNER JOIN pay_bank_statement pbs on pbs.id = pbsl.statement_id
            #     INNER JOIN ref_address address on address.id = pbsl.address_id and address.type = '{self.env.user.access_type}'
            #     left join
            #     (select pap.statement_line_id as statement_line_id, count(pap.id) as count from pay_address_payment pap group by pap.statement_line_id) pap on pap.statement_line_id = pbsl.id
            #     WHERE pbsl.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and pbsl.state = 'confirmed' and pbsl.address_id is not null and coalesce(pap.count,0) = 0
            #     group by pbsl.id, pbs.id
            # """
            query = f"""
                (
                    SELECT pbsl.id as id, pbsl.statement_id as statement_id, pbsl.payment_ref as payment_ref, 
                           pbsl.datetime as datetime, pbsl.address_id as address_id, pbsl.amount as amount, pbsl.state as state, 
                        pbsl.ccode as ccode, pbs.account_id as account_id
                    FROM pay_bank_statement_line pbsl
                    INNER JOIN pay_bank_statement pbs on pbs.id = pbsl.statement_id
                    INNER JOIN ref_address address on address.id = pbsl.address_id and address.type = '{self.env.user.access_type}'
                    left join 
                    (select pap.statement_line_id as statement_line_id, count(pap.id) as count from pay_address_payment pap group by pap.statement_line_id) pap on pap.statement_line_id = pbsl.id 
                    WHERE pbsl.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and pbsl.state = 'confirmed' and coalesce(pap.count,0) = 0 and pbsl.amount > 0.0
                    group by pbsl.id, pbs.id
                )
                UNION 
                (
                      SELECT pbsl.id as id, pbsl.statement_id as statement_id, pbsl.payment_ref as payment_ref, 
                             pbsl.datetime as datetime, pbsl.address_id as address_id, pbsl.amount as amount, pbsl.state as state, 
                          pbsl.ccode as ccode, pbs.account_id as account_id
                      FROM pay_bank_statement_line pbsl
                      INNER JOIN pay_bank_statement pbs on pbs.id = pbsl.statement_id
                      left join (select pap.statement_line_id as statement_line_id, count(pap.id) as count from pay_address_payment pap group by pap.statement_line_id) pap on pap.statement_line_id = pbsl.id 
                      WHERE pbsl.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and pbsl.state = 'confirmed' and coalesce(pap.count,0) = 0 and pbsl.address_id is null and pbsl.amount > 0.0
                      group by pbsl.id, pbs.id
                )
            """
            self.env.cr.execute(query)
            datas = self.env.cr.dictfetchall()
            payment_list = []
            for data in datas:
                payment_list += [{
                    'amount': round(data.get('amount'), 2),
                    'address_id': data.get('address_id'),
                    'state': 'confirmed',
                    # 'state': 'draft',
                    'ref': data.get('payment_ref'),
                    'date': convert_utc_to_timezone(datetime.strptime(str(data.get('datetime')), '%Y-%m-%d %H:%M:%S'),
                                                    'Asia/Ulaanbaatar').date(),
                    'payment_ref': data.get('payment_ref'),
                    'statement_line_id': data.get('id'),
                    'account_id': data.get('account_id')
                }]
                confirmed_ids = [data.get('id')]
            self.env['pay.address.payment'].create(payment_list)
            # self.browse(confirmed_ids).write({
            #     'state': 'confirmed'
            # })

    # def show_payment(self):
    #     for obj in self:
    #         payment = obj.payment_id
    #         if payment:
    #             return {
    #                 'name': _('И-Баримт үүсгэх'),
    #                 'type': 'ir.actions.act_window',
    #                 'target': 'new',
    #                 'view_mode': 'form',
    #                 'res_model': 'pay.address.payment',
    #                 'res_id': payment.id
    #             }

    def action_create_payment(self):
        for obj in self:
            # if(not obj.address_id):
            #     raise UserError('Харгалзах тоотыг сонгоно уу!')
            payment_id = obj.payment_id
            # if not payment_id:
            #     payment_id = self.env['pay.address.payment'].create({
            #         'statement_line_id': obj.id,
            #         'amount': obj.amount,
            #         'state': 'confirmed',
            #         'ref': obj.ref,
            #         'address_id': obj.address_id.id if obj.address_id else None,
            #         'account_id': obj.statement_id.account_id.id,
            #         'date': convert_utc_to_timezone(datetime.strptime(str(obj.datetime),'%Y-%m-%d %H:%M:%S'),'Asia/Ulaanbaatar').date()
            #     })
            return {
                'name': _('И-Баримт үүсгэх'),
                'type': 'ir.actions.act_window',
                'target': 'new',
                'view_mode': 'form',
                'res_model': 'pay.address.payment',
                'res_id': payment_id.id if payment_id else None,
                'context': {
                    'default_statement_line_id': obj.id,
                    'default_amount': obj.amount,
                    'default_state': 'confirmed',
                    'default_ref': obj.ref,
                    'default_address_id': obj.address_id.id if obj.address_id else None,
                    'default_account_id': obj.statement_id.account_id.id,
                    'default_date': convert_utc_to_timezone(datetime.strptime(str(obj.datetime), '%Y-%m-%d %H:%M:%S'),
                                                            'Asia/Ulaanbaatar').date(),
                    'reload': True
                }
            }

    def unlink(self):
        ids = self.ids
        if ids:
            self.env.cr.execute(f"""
                SELECT * FROM pay_address_payment payment where payment.statement_line_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} limit 1
            """)
            has_payment = self.env.cr.dictfetchall()
            if has_payment:
                raise UserError('Төлбөр үүссэн тул банкны хуулгыг устгах боломжгүй!')
        return super(PayBankStatementLine, self).unlink()

    @api.model
    def create(self, vals):
        try:
            return super(PayBankStatementLine, self).create(vals)
        except psycopg2.IntegrityError as e:
            if 'bank_statement_line_uniq' in str(e):
                payment_ref = vals.get('payment_ref', 'Unknown')
                raise ValidationError(
                    _('Duplicate bank statement detected for Payment Reference: %s.') % payment_ref
                )
            else:
                raise

    def write(self, vals):
        try:
            return super(PayBankStatementLine, self).write(vals)
        except psycopg2.IntegrityError as e:
            if 'bank_statement_line_uniq' in str(e):
                payment_ref = vals.get('payment_ref', 'Unknown')
                raise ValidationError(
                    _('Duplicate bank statement detected for Payment Reference: %s.') % payment_ref
                )
            else:
                raise

class PayReceiptInvoice(models.Model):
    _name = 'pay.receipt.address.invoice'
    _description = 'Нэхэмжлэл'
    name = fields.Char('Нэр', compute="_compute_name", store=True)
    payment_reference = fields.Char('Лавлах')
    amount_residual = fields.Float('Үлдэгдэл', compute="compute_residual_amount", store=True)
    amount_total = fields.Float('Нийт дүн')
    amount_tax = fields.Float('Татварын дүн')
    amount_untaxed = fields.Float('Татваргүй дүн')
    company_id = fields.Many2one('res.company', 'ХҮТ')
    PAYMENT_STATES = [
        ('partial', 'Хэсэгчилсэн төлөлт'),
        ('not_paid', 'Төлөгдөөгүй'),
        ('paid', 'Төлөгдсөн')
    ]
    payment_state = fields.Selection(PAYMENT_STATES, 'Төлбөрийн төлөв')
    receipt_address_id = fields.Many2one('pay.receipt.address', 'Төлбөрийн баримт')
    address_address = fields.Char('Тоот', related="address_id.address")
    apartment_code = fields.Char('Байр', related="address_id.apartment_id.code")
    address_id = fields.Many2one('ref.address', 'Тоот')
    inspector_id = fields.Many2one('hr.employee', 'Байцаагч', related="address_id.inspector_id")
    line_ids = fields.Many2many('pay.receipt.address.line', string='Төлбөрийн задаргаа', compute="_compute_line_ids",
                                store=False)
    owner_name = fields.Char('Эзэмшигчийн нэр', related="address_id.name")
    STATE = [
        ('draft', 'Ноорог'),
        ('posted', 'Нийтэлсэн'),
        ('cancel', 'Цуцлагдсан')
    ]
    state = fields.Selection(STATE, string='Төлөв', default='draft')
    # processing = fields.Boolean('processnig', default=False)
    year = fields.Selection(get_years(), 'Он', tacking=True, index=True)
    month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Сар', tacking=True, index=True)
    day = fields.Date('Огноо', tacking=True, index=True)
    ebarimt_id = fields.Integer('Ebarimt ID')
    payment_line_ids = fields.One2many('pay.address.payment.line', 'invoice_id', string="Төлбөр")
    counter_line_ids = fields.Many2many('counter.counter.line', string='Тоолуурын заалтын мөр',
                                        compute="_compute_counter_line_ids", store=False)
    paid_date = fields.Date('Төлөгдсөн огноо', tracking=True, index=True, readonly=True)
    first_balance = fields.Float('Эхний үлдэгдэл', compute="_compute_balance", store=False)
    last_balance = fields.Float('Эцсийн үлдэгдэл', compute="_compute_balance", store=False)
    undue_loss_amount = fields.Float("Алданги дүн")
    compute_loss = fields.Boolean('Алданги бодох', default=True)
    def _compute_balance(self):
        for obj in self:
            address_id = obj.address_id.id
            month = obj.month
            year = obj.year
            first_balance_query = f"""
                SELECT * FROM pay_receipt_address_invoice invoice WHERE invoice.address_id = {address_id} and invoice.payment_state!='paid' and CONCAT(invoice.year, '-', invoice.month, '-01')::date < '{year}-{month}-01'::date
            """
            self.env.cr.execute(first_balance_query)
            prev_invoice_list = self.env.cr.dictfetchall()
            first_balance = round(sum([invoice.get('amount_residual') for invoice in prev_invoice_list]), 2)
            obj.first_balance = first_balance
            obj.last_balance = round(first_balance + obj.amount_residual, 2)

    def _compute_counter_line_ids(self):
        ids = self.ids
        query = f"""
            select invoice.address_id as address_id, counter_line.id as counter_line_id from pay_receipt_address_invoice invoice
            inner join counter_counter_line_group counter_line_group on counter_line_group.company_id = invoice.company_id and 
            invoice.year = counter_line_group.year and invoice.month = counter_line_group.month
            inner join counter_counter_line counter_line on counter_line_group.id = counter_line.group_id and invoice.address_id = counter_line.address_id 						
            where invoice.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
            group by invoice.address_id,counter_line.id
        """
        self.env.cr.execute(query)
        counter_line_datas = self.env.cr.dictfetchall()
        counter_line_datas = groupby(counter_line_datas, key=lambda x: x['address_id'])
        counter_line_datas = {key: list(group) for key, group in counter_line_datas}
        for obj in self:
            address_id = obj.address_id.id
            if counter_line_datas.get(address_id):
                obj.counter_line_ids = [
                    (6, 0, [data.get('counter_line_id') for data in counter_line_datas.get(address_id)])]
            else:
                obj.counter_line_ids = [(6, 0, [])]

    def post(self):
        ids = self.ids
        self.browse(ids).write({
            'state': 'posted'
        })

    @api.depends('receipt_address_id', 'receipt_address_id.line_ids')
    def _compute_line_ids(self):
        for obj in self:
            receipt_address = obj.receipt_address_id
            obj.line_ids = [(6, 0, receipt_address.line_ids.ids)]

    @api.depends('address_id', 'address_id.code', 'year', 'month')
    def _compute_name(self):
        ids = self.ids
        if (not ids):
            return
        self.env.cr.execute(f"""
             SELECT prai.id as id, concat('INV','/', ra.code,'/',prai.year, '/', prai.month) as name FROM pay_receipt_address_invoice prai 
             inner join ref_address ra on ra.id = prai.address_id
             WHERE prai.id in {tuple(ids) if (len(ids) > 1) else f"({ids[0]})"}
        """)
        name_data_list = self.env.cr.dictfetchall()
        name_data_list = groupby(name_data_list, key=lambda x: x['id'])
        name_data_list = {key: list(group) for key, group in name_data_list}
        for obj in self:
            id = obj.id
            obj.name = name_data_list.get(id)[0].get('name') if name_data_list.get(id) else None

    @api.depends('payment_reference')
    def compute_residual_amount(self):
        ids = self.ids
        now_date = datetime.now().date()
        if ids:
            self.env.cr.execute(f"""
                SELECT invoice.id AS id, SUM(payment_line.amount) AS amount_paid, invoice.amount_total AS amount_total 
                FROM pay_receipt_address_invoice invoice
                INNER JOIN pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id
                WHERE invoice.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
                GROUP BY invoice.id
            """)
            data_list = self.env.cr.dictfetchall()
            data_list = groupby(data_list, key=lambda x: x['id'])
            data_list = {key: list(group) for key, group in data_list}
        else:
            data_list = {}
        for obj in self:
            id = obj.id
            if (data_list.get(id)):
                result = round(data_list.get(id)[0].get('amount_total') - data_list.get(id)[0].get('amount_paid'), 2)
                obj.amount_residual = result
                if (result > 0):
                    obj.payment_state = 'partial'
                else:
                    obj.payment_state = 'paid'
                    obj.paid_date = now_date
            else:
                obj.amount_residual = obj.amount_total
                obj.payment_state = 'not_paid'

    @api.model_create_single
    def create(self, vals):
        return super(PayReceiptInvoice, self).create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        result = super(PayReceiptInvoice, self).create(vals_list)
        receipt_address_ids = [i.get('receipt_address_id') for i in vals_list if i.get('receipt_address_id')]
        if receipt_address_ids:
            self.env.cr.execute(f"""
            UPDATE pay_receipt_address SET state = 'invoice_created' where id in {tuple(receipt_address_ids) if len(receipt_address_ids) > 1 else f"({receipt_address_ids[0]})"}
                        """)
        return result

    def create_ebarimt(self):
        active_ids = self.env.context.get('active_ids') or self.ids
        ids = self.search([('id', 'in', active_ids), ('payment_state', '=', 'paid'), ('ebarimt_id', '=', False)]).ids
        if (not ids):
            raise UserError('Таны Ebarimt үүсгэхээр сонгосон нэхэмжлэлүүд шинээр ebarimt үүсгэх боломжгүй байна!')
        return {
            'name': _('И-Баримт үүсгэх'),
            'type': 'ir.actions.act_window',
            'target': 'new',
            'view_mode': 'form',
            'res_model': 'nc.ebarimt.register.wizard',
            'context': {
                'default_invoice_ids': ids
            }
        }

    def register_payment(self):
        ids = self.env.context.get('active_ids') or self.ids
        active_model = self.env.context.get('active_model') or 'pay.receipt.address.invoice'
        vals = {}
        if (active_model == 'pay.receipt.address.invoice'):
            vals['default_invoice_ids'] = ids
        self.env.cr.execute(f"""
            SELECT address.id as address_id, address.code as code ,SUM(invoice.amount_residual) as amount_residual 
            FROM pay_receipt_address_invoice invoice 
            INNER JOIN ref_address address ON invoice.address_id = address.id
            where invoice.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and invoice.payment_state != 'paid'
            GROUP BY address.id;
        """)
        invoice_total_amount = self.env.cr.dictfetchall()
        if (len(invoice_total_amount) != 1):
            raise UserError('Зөвхөн нэг тоот-д харгалзах нэхэмжлэлийг сонгоно уу!')

        unpaid_invoices = self.search([('id', 'in', ids), ('payment_state', '!=', 'paid')])
        vals['default_invoice_ids'] = unpaid_invoices.ids
        vals['default_amount'] = invoice_total_amount[0]['amount_residual']
        vals['default_communication'] = invoice_total_amount[0]['code']
        vals['default_payment_ref'] = invoice_total_amount[0]['code']
        vals['default_address_id'] = invoice_total_amount[0]['address_id']
        return {
            'name': _('Төлбөр бүртгэх'),
            'type': 'ir.actions.act_window',
            'target': 'new',
            'view_mode': 'form',
            'res_model': 'pay.payment.register',
            'context': vals
        }

    def unlink(self):
        for obj in self:
            obj.payment_line_ids.unlink()
        return super(PayReceiptInvoice, self).unlink()


class PayAddressChildPaymentWizard(models.Model):
    _name = 'pay.address.child.payment.view'
    _description = "Шилжүүлэг хийгдэж орж ирсэн төлбөрийн sql view"
    _auto = False
    id = fields.Integer('ID', tracking=True)
    payment_id = fields.Many2one('pay.address.payment', 'Төлбөр')
    amount = fields.Float('Шилжүүлсэн дүн', related='payment_id.amount', related_sudo=True)
    residual_amount = fields.Float('Тулгагдаагүй үлдсэн дүн', related='payment_id.residual_amount', related_sudo=True)
    address_id = fields.Many2one('ref.address', related_sudo=True, related='payment_id.address_id', string='Хаяг')
    address_type = fields.Selection(ADDRESS_TYPE, 'Тоотын төрөл', related_sudo=True,
                                    related='payment_id.address_id.type')
    apartment_code = fields.Char('Байрны код', related_sudo=True, related='payment_id.address_id.apartment_id.code')
    address_address = fields.Char('Тоот', related_sudo=True, related='payment_id.address_id.address')
    parent_payment_id = fields.Many2one('pay.address.payment', 'Эцэг')

    def action_join_with_parent(self):
        self.sudo().join_with_parent()

    def join_with_parent(self):
        for obj in self:
            obj.payment_id.join_with_parent()

    @api.model
    def init(self):
        tools.drop_view_if_exists(self._cr, 'pay_address_child_payment_view')
        self._cr.execute("""
            CREATE OR REPLACE VIEW pay_address_child_payment_view as (
                SELECT payment.id as id ,payment.id AS payment_id, 
                       payment.parent_id AS parent_payment_id
                FROM pay_address_payment payment WHERE parent_id is not null
            )
        """)


class PayAddressPayment(models.Model):
    _name = "pay.address.payment"
    _description = 'Төлбөр'
    _order = 'id desc'
    """
        required fields: account_id, address_id
    """
    name = fields.Char('Нэр', compute="_compute_name", store=True)
    account_id = fields.Many2one('pay.bank.account', 'Данс', required=True)
    line_ids = fields.One2many('pay.address.payment.line', 'payment_id')
    amount = fields.Float('Дүн')
    address_id = fields.Many2one('ref.address', 'Тоот', index=True)
    address_type = fields.Selection(ADDRESS_TYPE, 'Тоотын төрөл', related="address_id.type", store=True)
    # address_type = fields.Selection(ADDRESS_TYPE, 'Тоотын төрөл', store=True)
    STATE = [
        ('draft', 'Ноорог'),
        ('confirmed', 'Тулгагдаагүй'),
        ('processing', 'Зөрүү'),
        ('done', 'Тулгагдсан')
    ]
    address_address = fields.Char('Тоот', related="address_id.address")
    address_code = fields.Char('Хэрэглэгчийн код', related="address_id.code")
    apartment_code = fields.Char('Байр', related="address_id.apartment_id.code")
    state = fields.Selection(STATE, 'Төлөв', default='draft')
    payment_ref = fields.Text('Төлбөрийн утга')
    ref = fields.Char('Лавлах')
    date = fields.Date('Огноо', default=fields.Date.today, tracking=True, index=True)
    statement_line_id = fields.Many2one('pay.bank.statement.line', 'Банкны хуулга')
    statement_line_amount = fields.Float('Дүн', related="statement_line_id.amount")
    residual_amount = fields.Float('Үлдэгдэл', compute="compute_residual_amount", store=True)
    parent_id = fields.Many2one('pay.address.payment', 'Эцэг', )
    year = fields.Selection(get_years(), 'Жил', required=True)
    month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Сар', required=True)
    child_ids = fields.One2many('pay.address.child.payment.view', 'parent_payment_id', string='Холбоотой төлбөрүүд')
    loss_in_invoice_ids = fields.Many2many('pay.receipt.address.invoice', 'loss_in_invoice_rel', 'payment_id',
                                           'invoice_id', string="Алданга тооцсон нэхэмжлэлүүд")

    @api.model_create_multi
    def create(self, vals_list):
        condition = {
            'contains': 'ilike',
            'not_contains': 'not ilike',
            'match_regex': '~'
        }
        result = super(PayAddressPayment, self).create(vals_list)
        ids = result.ids
        account_list = self.env['pay.bank.account'].search([('type', '=', 'social_in')])
        for account in account_list:
            match_label = account.match_label  # account.get('match_label')
            match_label_param = account.match_label_param  # account.get('match_label_param')
            match_label_pattern = f"{condition.get(match_label)} {match_label_param}"
            query = f"""
                select payment.id as payment_id
                from pay_address_payment payment
                where payment.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and payment.payment_ref {match_label_pattern} and payment.statement_line_id is not null
            """
            self.env.cr.execute(query)
            datas = self.env.cr.dictfetchall()
            self.env['pay.address.payment'].browse([d.get('payment_id') for d in datas]).write({
                'account_id': account.id
            })
        return result

    @api.depends('line_ids', 'amount')
    def compute_residual_amount(self):
        ids = self.ids
        if ids:
            self.env.cr.execute(f"""
                select payment_list.payment_id as id, ROUND(CAST((payment_list.amount - payment_list.paid_amount) AS numeric), 2) as residual from (
                    SELECT pap.id as payment_id, SUM(papl.amount) as paid_amount, pap.amount as amount
                    FROM pay_address_payment_line papl
                    inner join pay_address_payment pap on pap.id = papl.payment_id
                    WHERE papl.payment_id in {tuple(ids) if (len(ids) > 1) else f"({ids[0]})"}
                    GROUP BY pap.id
                    ORDER BY pap.id asc
                ) payment_list
            """)
            residual_amount = self.env.cr.dictfetchall()
            residual_amount = groupby(residual_amount, key=lambda x: x['id'])
            residual_amount = {key: list(group) for key, group in residual_amount}
        else:
            residual_amount = {}
        for obj in self:
            id = obj.id
            has_line = True if residual_amount.get(id) else False
            if (has_line):
                result = residual_amount.get(id)[0].get('residual')
            else:
                result = obj.amount
            obj.residual_amount = result
            if (obj.amount != result and float(result) < 0.0):
                raise UserError(f'{obj.name} төлбөрийн үлдэгдэл хасах дүнтэй байж болохгүй.')
            if (result <= 0.0):
                obj.state = 'done'
            else:
                obj.state = 'processing' if has_line else 'confirmed'

    # def compute_address_invoices(self):
    #     for obj in self:
    #         id = obj.id
    #         invoice_ids = self.env['pay.receipt.address.invoice'].search(
    #             [('address_id', '=', obj.address_id.id), ('payment_state', '!=', 'paid'), ('state', '=', 'posted')]).ids
    #         obj.address_invoice_ids = [(0, 0, {'invoice_id': invoice_id, 'payment_id': id}) for invoice_id in
    #                                    invoice_ids]
    @api.onchange('address_id')
    def onchange_address_id(self):
        for obj in self:
            statement_line = obj.statement_line_id
            if statement_line:
                statement_line.write({
                    'address_id': obj.address_id.id
                })
            line_ids = obj.line_ids.ids
            if line_ids:
                obj.line_ids = [(3, line_id) for line_id in line_ids]

    def register_invoices(self, invoice_ids: List[int] = []):
        ids = self.ids
        if (len(ids) == 1):
            if not self.account_id.match_reconcile or invoice_ids:
                payment_datas = self.prepare_line_by_invoice(invoice_ids)
                if (payment_datas):
                    self.env['pay.address.payment.line'].create(payment_datas)
                    return True
                else:
                    return False
            else:
                payment_line_data = self.prepare_line_data()
                payment_line_ids = self.env['pay.address.payment.line'].create(payment_line_data)
                return True

        if (len(ids) < 1):
            return True
        self.env.cr.execute(f"""
            select payment.account_id as account_id from pay_address_payment payment
            where payment.id in {tuple(ids) if len(ids) > 1 else f"({ids})"}
            group by payment.account_id
        """)
        account_ids = self.env.cr.dictfetchall()
        if len(account_ids) > 1:
            raise UserError('Олон банкны данстай холбоотой төлбөрүүдийг нэг дор тулгалт хийж болохгүй')
        payment_line_data = []
        query_find_unreconcile_payment_ids = f"""
            select payment.id as id from pay_address_payment payment
            inner join pay_bank_account account on account.id = payment.account_id and account.match_reconcile = false and account.type='incoming'
            where payment.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
        """
        self.env.cr.execute(query_find_unreconcile_payment_ids)
        unreconciled_payment_ids = self.env.cr.dictfetchall()
        unreconciled_payment_ids = [int(data.get('id')) for data in unreconciled_payment_ids]
        if unreconciled_payment_ids:
            datas = self.browse(unreconciled_payment_ids).prepare_line_by_invoice()
            if datas:
                payment_line_data += datas

        query_find_reconcile_payment_ids = f"""
                    select payment.id as id from pay_address_payment payment
                    inner join pay_bank_account account on account.id = payment.account_id and account.match_reconcile = true and account.type='incoming'
                    where payment.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
                """
        self.env.cr.execute(query_find_reconcile_payment_ids)
        reconcile_payment_ids = self.env.cr.dictfetchall()
        reconcile_payment_ids = [data.get('id') for data in reconcile_payment_ids]
        if (reconcile_payment_ids):
            datas = self.browse(reconcile_payment_ids).prepare_line_data()
            if datas:
                payment_line_data += datas
        payment_line_ids = self.env['pay.address.payment.line'].create(payment_line_data)
        return {
            'name': _('Тулгалт хийгдсэн жагсаалт'),
            'type': 'ir.actions.act_window',
            'view_mode': 'tree',
            'target': 'current',
            'domain': [('id', 'in', payment_line_ids.ids)],
            'res_model': 'pay.address.payment.line',
            'view_id': self.env.ref('ub_kontor.view_pay_address_payment_line_tree').id,
        }

    def join_with_parent(self):
        for obj in self:
            obj.line_ids.unlink()
            parent = obj.parent_id
            if parent:
                msg = f"{obj.name} төлбөр {parent.name}-д нэгтгэгдлээ."
                amount = parent.amount + obj.amount
                residual_amount = parent.residual_amount + obj.amount
                state = 'processing'
                self.env.cr.execute(f"""
                    UPDATE pay_address_payment SET state = '{state}', amount = {amount}, residual_amount = {residual_amount} where id = {parent.id}
                """)
                obj.unlink()
                parent.compute_residual_amount()
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': msg,
                        'message': f'',
                        'type': 'success',
                        'sticky': False,
                        'next': {
                            'type': 'ir.actions.act_window_close',
                        }
                    }
                }

    @api.depends('account_id', 'date', 'address_id')
    def _compute_name(self):
        ids = self.ids
        self.env.cr.execute(f"""
            select payment.id as id, concat(bank_account.short_code,'/',ra.code,'/', TO_CHAR(payment.date, 'YYYY'), '/',TO_CHAR(payment.date, 'MM')) as name
             from pay_address_payment payment
            inner join pay_bank_account bank_account on payment.account_id = bank_account.id
            inner join ref_address ra ON ra.id = payment.address_id
            where payment.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
        """)
        name_data_list = self.env.cr.dictfetchall()
        name_data_list = groupby(name_data_list, key=lambda x: x['id'])
        name_data_list = {key: list(group) for key, group in name_data_list}
        for obj in self:
            id = obj.id
            obj.name = name_data_list.get(id)[0].get('name') if name_data_list.get(id) else None

    @api.depends('address_id', 'account_id')
    def compute_name(self):
        self._compute_name()

    def confirm(self):
        for obj in self:
            obj.state = 'confirmed'

    def prepare_line_by_invoice(self, invoice_ids: List[int] = []):
        ids = self.ids
        if (not ids):
            return False
        company_id = self.browse(ids[0]).account_id.company_id.id
        period_id = self.get_active_period(company_id=company_id)
        if not period_id:
            raise UserError('Идэвхитэй санхүүгийн мөрчлөг олдсонгүй')
        period_year = period_id.year
        period_month = period_id.month
        period_id = period_id.id
        self.env.cr.execute(f"""
            SELECT payment.address_id as address_id 
            FROM pay_address_payment payment 
            INNER JOIN pay_bank_account account ON account.id = payment.account_id and account.type='incoming'
            WHERE payment.id in {tuple(ids) if (len(ids) > 1) else f"({ids[0]})"} and payment.address_id is not null 
            GROUP BY payment.address_id
        """)
        address_ids = self.env.cr.dictfetchall()
        address_ids = [address_id.get('address_id') for address_id in address_ids if address_id.get('address_id')]
        if (not address_ids):
            return False
        if not invoice_ids:
            self.env.cr.execute(f"""
            SELECT * FROM pay_receipt_address_invoice invoice
            WHERE invoice.state = 'posted' and invoice.payment_state != 'paid' and invoice.address_id in {tuple(address_ids) if len(address_ids) > 1 else f"({address_ids[0]})"} and CONCAT(invoice.year,'-',invoice.month, '-01')::DATE <= '{period_year}-{period_month}-01'::DATE
            ORDER BY invoice.address_id asc, concat(invoice.year,'-',invoice.month,'-','1')::date asc;
        """)
        else:
            self.env.cr.execute(f"""
                SELECT * FROM pay_receipt_address_invoice invoice
                WHERE invoice.state = 'posted' and invoice.payment_state != 'paid' and invoice.id in {tuple(invoice_ids) if len(invoice_ids) > 1 else f"({invoice_ids[0]})"}
                ORDER BY invoice.address_id asc, concat(invoice.year,'-',invoice.month,'-','1')::date asc;
            """)
        invoice_data_list = self.env.cr.dictfetchall()
        if (not invoice_data_list):
            return
        invoice_ids = [invoice.get('id') for invoice in invoice_data_list]
        invoice_data_list = groupby(invoice_data_list, key=lambda x: x['address_id'])
        invoice_data_list = {key: list(group) for key, group in invoice_data_list}
        payment_line_data = []
        for obj in self:
            payment_residual = obj.residual_amount
            # if(payment_residual)
            payment_state = obj.state
            if (payment_state == 'done' or payment_residual <= 0):
                continue
            address_id = obj.address_id.id
            payment_id = obj.id
            invoice_list = invoice_data_list.get(address_id)
            if not invoice_list:
                continue
            for invoice in invoice_list:
                invoice_id = invoice.get('id')
                invoice_amount_residual = invoice.get('amount_residual')
                temp = payment_residual - invoice_amount_residual
                if (invoice_amount_residual <= 0):
                    continue
                if (temp < 0):
                    payment_line_data += [{
                        'payment_id': payment_id,
                        'invoice_id': invoice_id,
                        'amount': payment_residual,
                        'period_id': period_id
                    }]
                    invoice['amount_residual'] = invoice_amount_residual - payment_residual
                    break
                else:
                    payment_residual = payment_residual - invoice_amount_residual
                    payment_line_data += [{
                        'payment_id': payment_id,
                        'invoice_id': invoice_id,
                        'amount': invoice_amount_residual,
                        'period_id': period_id
                    }]
                    invoice['amount_residual'] = 0
                    if (payment_residual == 0):
                        break
        return payment_line_data

    def change_account(self):
        return {
            'name': _('Данс өөрчлөх форм'),
            'type': 'ir.actions.act_window',
            'target': 'new',
            'view_mode': 'form',
            'res_model': 'pay.payment.change.account',
        }

    def get_active_period(self, company_id):
        return self.env['pay.period'].search(
            [('state', '=', 'opened'), ('company_id', '=', company_id),
             ('address_type', '=', self.env.user.access_type)],
            order='id desc', limit=1)

    def prepare_line_data(self):
        ids = self.ids
        result = []
        self.env.cr.execute(f"""
            SELECT account.id as account_id, account.match_label match_label, account.match_label_param as match_label_param
            FROM pay_address_payment pap
            inner join pay_bank_account account on account.id = pap.account_id and account.match_reconcile = True and account.type='incoming'
            where pap.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and pap.address_id is not null
            group by account.id
        """)
        account_datas = self.env.cr.dictfetchall()

        condition = {
            'contains': 'ilike',
            'not_contains': 'not ilike',
            'match_regex': '~'
        }
        company_id = self.browse(ids[0]).account_id.company_id.id
        period_id = self.get_active_period(company_id=company_id)
        period_year = period_id.year
        period_month = period_id.month
        if not period_id:
            raise UserError('Идэвхитэй санхүүгийн мөрчлөг олдсонгүй')
        period_id = period_id.id
        using_invoice_list = {}
        using_payment_list = {}
        for account in account_datas:
            match_label = account.get('match_label')
            match_label_param = account.get('match_label_param')
            match_label_pattern = f"{condition.get(match_label)} {match_label_param}"
            query = f"""
               select reconciled.invoice_id as invoice_id, invoice.amount_residual as invoice_amount_total ,reconciled.payment_amount as payment_amount, reconciled.payment_id as payment_id  from 
                (
                        select max(invoice.id) as invoice_id, pap.residual_amount payment_amount, pap.id as payment_id 
                        from pay_address_payment pap 
                        inner join pay_receipt_address_invoice invoice on invoice.payment_state not in ('paid') and invoice.state in ('posted') and pap.payment_ref {match_label_pattern} and invoice.address_id = pap.address_id
                        inner join pay_bank_account account on account.id = pap.account_id and account.type='incoming'
                        where pap.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} 
                        group by pap.id
                ) reconciled
                inner join pay_receipt_address_invoice invoice on invoice.id = reconciled.invoice_id and CONCAT(invoice.year, '-', invoice.month, '-01')::DATE <= '{period_year}-{period_month}-01'::DATE
            """
            self.env.cr.execute(query)
            datas = self.env.cr.dictfetchall()
            for data in datas:
                if (not using_payment_list.get(data.get('payment_id'))):
                    using_payment_list[data.get('payment_id')] = {
                        'residual': data.get('payment_amount')
                    }
                if (not using_invoice_list.get(data.get('invoice_id'))):
                    using_invoice_list[data.get('invoice_id')] = {
                        'residual': data.get('invoice_amount_total')
                    }
                payment_amount = using_payment_list.get(data.get('payment_id')).get('residual')
                invoice_amount = using_invoice_list.get(data.get('invoice_id')).get('residual')
                r = 0.0
                if (payment_amount <= 0.0 or invoice_amount <= 0.0):
                    continue
                if (payment_amount - invoice_amount >= 0.0):
                    r = invoice_amount
                    using_invoice_list[data.get('invoice_id')]['residual'] = 0.0
                    using_payment_list[data.get('payment_id')]['residual'] = payment_amount - r
                else:
                    r = payment_amount
                    using_invoice_list[data.get('invoice_id')]['residual'] = invoice_amount - r
                    using_payment_list[data.get('payment_id')]['residual'] = 0.0

                result += [{
                    'payment_id': data.get('payment_id'),
                    'invoice_id': data.get('invoice_id'),
                    'amount': r,
                    'period_id': period_id
                }]
        return result

    def unreconcile(self):
        ids = self.ids
        self.env['pay.address.payment.line'].sudo().search([('payment_id', 'in', ids)]).unlink()

    def unlink(self):
        ids = self.ids
        if (ids):
            self.env.cr.execute(f"""
                SELECT * FROM pay_address_payment WHERE id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"};
            """)
            payment_list = self.env.cr.dictfetchall()
            related_statement_line_ids = [payment.get('statement_line_id') for payment in payment_list]
            related_statement_line_ids = list(set(related_statement_line_ids))
            self.env['pay.bank.statement.line'].search([('id', 'in', related_statement_line_ids)]).write({
                'address_id': None
            })

            self.env['pay.address.payment.line'].search([('payment_id', 'in', ids)]).unlink()

            self.env['pay.address.payment'].sudo().search([('parent_id', 'in', ids)]).unlink()
        # for obj in self:
        #     if (obj.statement_line_id):
        #         obj.statement_line_id.write({
        #             'address_id': None
        #         })
        #     obj.line_ids.unlink()
        #     self.env['pay.address.payment'].sudo().search([('parent_id', '=', obj.id)]).unlink()
        result = super(PayAddressPayment, self).unlink()

        return result

    def transfer_amount(self):
        for obj in self:
            return {
                "type": "ir.actions.act_window",
                "res_model": "pay.address.payment.transfer",
                "view_mode": "form",
                'target': 'new',
                'context': {
                    'default_payment_id': obj.id
                }
            }


class PayReceiptPaymentLine(models.Model):
    _name = "pay.address.payment.line"
    _description = 'Төлбөрийн мөр ~ Тулгалт'
    payment_id = fields.Many2one('pay.address.payment', 'Төлбөр', required=True, )
    payment_ref = fields.Text('Гүйлгээний утга', related="payment_id.payment_ref")
    address_id = fields.Many2one('ref.address', 'Тоот', related="payment_id.address_id")
    apartment_code = fields.Char('Байр', related="address_id.apartment_id.code")
    address_address = fields.Char('Тоот', related="address_id.address")
    invoice_id = fields.Many2one('pay.receipt.address.invoice', 'Нэхэмжлэл', required=True)
    amount = fields.Float('Дүн')
    invoice_total_amount = fields.Float('Нэхэмжилсэн дүн', related="invoice_id.amount_total")
    payment_amount = fields.Float('Төлбөрийн дүн', related="payment_id.amount")
    reconciled_date = fields.Date('Тулгалт хийгдсэн огноо', default=fields.Date.context_today, required=True,
                                  index=True, tracking=True)
    payment_date = fields.Datetime('Төлбөрийн огноо', related="payment_id.statement_line_id.datetime")
    period_id = fields.Many2one('pay.period', 'Мөчлөг', tracking=True, index=True, required=True)

    invoiced_year = fields.Selection(get_years(), 'Нэхэмжилсэн жил', related='invoice_id.year')
    invoiced_month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Нэхэмжилсэн сар', related='invoice_id.month')
    account_id = fields.Many2one('pay.bank.account', related="payment_id.account_id", string='Данс')

    @api.onchange('invoice_id')
    def onchange_invoice(self):
        for obj in self:
            invoiced_amount = obj.invoice_id.amount_residual
            payment_residual = obj.payment_id.residual_amount
            if (payment_residual >= invoiced_amount):
                obj.amount = invoiced_amount
            else:
                obj.amount = payment_residual

    @api.model_create_multi
    def create(self, vals_list):
        # Use super() to call the original create method
        result = super(PayReceiptPaymentLine, self).create(vals_list)

        # Collect unique invoice and payment IDs from the vals_list
        invoice_ids = [vals.get('invoice_id') for vals in vals_list if vals.get('invoice_id')]
        payment_ids = [vals.get('payment_id') for vals in vals_list if vals.get('payment_id')]

        # Update residual amounts for the relevant invoices and payments
        if invoice_ids:
            self.env['pay.receipt.address.invoice'].browse(invoice_ids).compute_residual_amount()
        if payment_ids:
            self.env['pay.address.payment'].browse(payment_ids).compute_residual_amount()

        return result

    def write(self, vals):
        invoice_ids = self.mapped('invoice_id.id')
        payment_ids = self.mapped('payment_id.id')
        new_invoice_ids = vals.get('invoice_id')
        new_payment_ids = vals.get('payment_id')

        result = super(PayReceiptPaymentLine, self).write(vals)

        if invoice_ids:
            self.env['pay.receipt.address.invoice'].browse(invoice_ids).compute_residual_amount()
        if payment_ids:
            self.env['pay.address.payment'].browse(payment_ids).compute_residual_amount()
        if new_invoice_ids:
            self.env['pay.receipt.address.invoice'].browse(new_invoice_ids).compute_residual_amount()
        if new_payment_ids:
            self.env['pay.address.payment'].browse(new_payment_ids).compute_residual_amount()

        return result

    def action_remove(self):
        for obj in self:
            payment_id = obj.payment_id.id
            obj.unlink()
            if (self.env.context.get('reload')):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Төлбөрийн мөр устгагдлаа',
                        'message': f'',
                        'type': 'success',
                        'sticky': True,
                        'next': {
                            'type': 'ir.actions.act_window',
                            'view_mode': 'form',  # Form view mode
                            'view_type': 'form',
                            'res_model': 'pay.address.payment',
                            'view_id': self.env.ref('ub_kontor.view_pay_address_payment_form').id,
                            'target': 'new',
                            'res_id': payment_id
                        }
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Төлбөрийн мөр устгагдлаа',
                        'message': f'',
                        'type': 'success',
                        'sticky': False,
                        'next': {
                            'type': 'ir.actions.act_window_close',
                        }
                    }
                }

    def unlink(self):
        ids = self.ids
        invoice_ids = []
        payment_ids = []
        if ids:
            self.env.cr.execute(f"""
                select payment_line.id as id from pay_address_payment_line payment_line
                inner join pay_period period on period.id = payment_line.period_id and period.state = 'closed'
                where payment_line.id in {tuple(ids) if (len(ids) > 1) else f"({ids[0]})"}
                limit 1;
            """)
            has_closed_period = self.env.cr.dictfetchall()
            if has_closed_period:
                raise UserError('Санхүүгийн мөчлөг хаагдсан учир тулгалтыг салгах боломжгүй.!')
            self.env.cr.execute(f"""
                SELECT invoice_id as invoice_id, payment_id as payment_id FROM pay_address_payment_line WHERE id in {tuple(ids) if (len(ids) > 1) else f"({ids[0]})"}
            """)
            datas = self.env.cr.dictfetchall()
            invoice_ids = [data.get('invoice_id') for data in datas]
            payment_ids = [data.get('payment_id') for data in datas]
        res = super(PayReceiptPaymentLine, self).unlink()

        self.env['pay.receipt.address.invoice'].browse(invoice_ids).compute_residual_amount()
        self.env['pay.address.payment'].browse(payment_ids).compute_residual_amount()
        return res

    @api.model
    def get_sums(self):
        lines = self.search([])
        total_amount = sum(line.amount for line in lines)
        total_invoice_amount = sum(line.invoice_total_amount for line in lines)
        total_payment_amount = sum(line.payment_amount for line in lines)
        return {
            'total_amount': total_amount,
            'total_invoice_amount': total_invoice_amount,
            'total_payment_amount': total_payment_amount,
        }


class PaymentAddressLineView(models.Model):
    _name = 'pay.address.payment.line.view'
    _auto = False
    _description = 'Төлбөрийн мөр (Тулгалт)-г харуулах sql view'
    payment_id = fields.Many2one('pay.address.payment', 'Төлбөр', required=True)
    payment_ref = fields.Text('Гүйлгээний утга', related="payment_id.payment_ref")
    address_id = fields.Many2one('ref.address', 'Тоот')
    apartment_id = fields.Many2one('ref.apartment', 'Байр')
    inspector_id = fields.Many2one('hr.employee', 'Байцаагч')
    apartment_code = fields.Char('Байр', related="address_id.apartment_id.code")
    address_address = fields.Char('Тоот', related="address_id.address")
    invoice_id = fields.Many2one('pay.receipt.address.invoice', 'Нэхэмжлэл', required=True)
    amount = fields.Float('Дүн')
    invoice_total_amount = fields.Float('Нэхэмжилсэн дүн', related="invoice_id.amount_total")
    payment_amount = fields.Float('Төлбөрийн дүн', related="payment_id.amount")
    reconciled_date = fields.Date('Тулгалт хийгдсэн огноо', required=True)
    payment_date = fields.Date('Төлбөрийн огноо', related="payment_id.date")

    account_id = fields.Many2one('pay.bank.account', 'Данс')
    bank_id = fields.Many2one('pay.bank', 'Банк')
    statement_line_id = fields.Many2one('pay.bank.statement.line', 'Банкны хуулгын мөр')
    reconciled_uid = fields.Many2one('res.users', 'Тулгасан хүн')
    period_id = fields.Many2one('pay.period', 'Мөчлөг')

    @api.model
    def init(self):
        tools.drop_view_if_exists(self._cr, 'pay_address_payment_line_view')
        self._cr.execute("""
            CREATE OR REPLACE VIEW pay_address_payment_line_view as (
                select 
                payment_line.id as id,
                payment_line.payment_id as payment_id,
                payment.address_id as address_id,
                payment_line.invoice_id as invoice_id,
                payment_line.amount as amount,
                payment_line.reconciled_date as reconciled_date,
                payment_line.period_id as period_id,
                payment.account_id as account_id,
                account.bank_id as bank_id,
                address.apartment_id as apartment_id,
                address.inspector_id as inspector_id,
                payment.statement_line_id as statement_line_id,
                payment_line.create_uid as reconciled_uid
                    from pay_address_payment_line payment_line
                inner join pay_address_payment payment on payment.id = payment_line.payment_id 
                inner join pay_receipt_address_invoice invoice on invoice.id = payment_line.invoice_id 
                inner join pay_bank_account account on account.id = payment.account_id
                left join ref_address address on payment.address_id = address.id
                order by payment_line.id desc
            )
        """)


class PayPeriod(models.Model):
    _name = 'pay.period'
    _description = 'Санхүүгийн мөчлөг'
    _sql_constraints = [
        ('account_period_unique', 'unique (year,month,company_id,address_type)',
         'Санхүүгийн мөчлөг давхцаж байна!'),
    ]
    name = fields.Char('Нэр', compute='_compute_name', store=True)
    year = fields.Selection(get_years(), 'Жил', required=True)
    month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Сар', required=True)
    state = fields.Selection([('draft', 'Ноорог'), ('opened', 'Нээсэн'), ('closed', 'Хаасан')], string='Төлөв',
                             default='draft', required=True, readonly=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True, default=lambda self: self.env.user.company_id.id)
    opened_date = fields.Date('Нээсэн огноо', readonly=True)
    opened_uid = fields.Many2one('res.users', 'Нээсэн хэрэглэгч', readonly=False)
    closed_date = fields.Date('Хаасан огноо', readonly=True)
    closed_uid = fields.Many2one('res.users', 'Хаасан хэрэглэгч', readonly=False)
    address_type = fields.Selection(ADDRESS_TYPE, string='Тоотын төрөл', default='OS', required=True)
    active = fields.Boolean('Active', default=True)

    @api.depends('year', 'month', 'company_id')
    def _compute_name(self):
        for obj in self:
            obj.name = f"{obj.company_id.name} - {obj.year}/{obj.month}"

    def open(self):
        self.state = 'opened'
        if not self.opened_date:
            self.opened_date = datetime.now().date()
        self.opened_uid = self.env.uid

    def get_next_month(self):
        current_date = datetime.strptime(self.year + '-' + self.month, '%Y-%m')
        if current_date.month == 12:
            next_month_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            next_month_date = current_date.replace(month=current_date.month + 1)

        next_year_str = str(next_month_date.year)
        next_month_str = next_month_date.strftime('%m')
        return next_year_str, next_month_str

    def close(self):
        self.state = 'closed'
        if not self.closed_date:
            self.closed_date = datetime.now().date()
        self.register_current_current_report()
        self.closed_uid = self.env.uid

        # next_year_str, next_month_str = self.get_next_month()
        #
        # print("Searching for pay.period with year:", str(next_year_str), "and month:", next_month_str)
        #
        # existing_period = self.env['pay.period'].with_context(active_test=False).search([
        #     ('year', '=', next_year_str),
        #     ('month', '=', next_month_str),
        #     ('company_id', '=', self.env.company.id),
        # ])
        # print(self.env.company.id)
        #
        # if existing_period:
        #
        #     print("++++++++++++++=")
        #     if not existing_period.active:
        #         existing_period.write({
        #             'active': True,
        #             'state': 'opened',
        #         })
        #         return existing_period
        #     else:
        #         existing_period.write({
        #             'state': 'opened',
        #         })
        #         return existing_period
        # else:
        #     print("No existing period found, creating new record.")
        #
        # new_record = self.create({
        #     'year': next_year_str,
        #     'month': next_month_str,
        #     'company_id': self.company_id.id,
        #     'address_type': self.address_type,
        # })
        # new_record.open()
    def action_archive(self):
        result = super(PayPeriod, self).action_archive()
        self.write({
            'state': 'closed'
        })
        return result

    def action_unarchive(self):
        result = super(PayPeriod, self).action_unarchive()
        self.write({
            'state': 'draft'
        })
        return result

    def is_new_period(self)->bool:
        for obj in self:
            self.env.cr.execute(f"""
                SELECT * FROM pay_period period WHERE period.company_id = {obj.company_id.id} and period.address_type = '{obj.address_type}' and concat(period.year, '-', period.month,'-01')::date > '{obj.year}-{obj.month}-01'::date and period.active = True
            """)
            has_data =  self.env.cr.dictfetchall()
            if has_data:
                return False
            else:
                return True

    def register_current_current_report(self):
        company_id = self.company_id.id
        id = self.id
        period_month = self.month
        period_year = self.year
        address_type = self.address_type
        query = ""
        if self.is_new_period():
            query = f"""
            select address.id as address_id, 
            first_balance.residual AS first_balance_amount,
            invoice.amount_total as invoiced_amount, 
            last_balance.residual as last_balance_amount, 
            last_balance.invoice_names as unpaid_invoices,
            address.inspector_id as inspector_id, 
            receipt_address.total_amount as receipt_amount,
            total_paid.amount as total_paid_amount,
            {id} as period_id
            from ref_address address
            left join (
                select last_balance.address_id as address_id, round(cast(sum(last_balance.residual) as numeric),2) as residual
                from (
                    SELECT 
                        invoice.address_id as address_id,
                        round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual
                    FROM 
                        pay_receipt_address_invoice invoice
                    INNER JOIN 
                        ref_address address 
                        ON address.id = invoice.address_id and invoice.company_id = {company_id}
                        AND address.type = '{address_type}'
                        AND concat(invoice.year, '-', invoice.month, '-01')::date < '{period_year}-{period_month}-01'::date 
                    LEFT JOIN 
                        pay_address_payment_line payment 
                        ON payment.invoice_id = invoice.id 
                        AND payment.period_id IN (
                            SELECT pp.id    
                            FROM pay_period pp 
                            WHERE pp.company_id = {company_id} 
                            AND pp.address_type = '{address_type}' 
                            AND concat(pp.year, '-', pp.month, '-01')::date < '{period_year}-{period_month}-01'::date 
                        )
                    GROUP BY  invoice.id
                ) last_balance
                where last_balance.residual > 0.0
                group by last_balance.address_id
            ) first_balance on first_balance.address_id = address.id
            left join (
                select last_balance.address_id as address_id, round(cast(sum(last_balance.residual) as numeric),2) as residual, string_agg(last_balance.invoice_name, ', ') as invoice_names
                from (
                    SELECT 
                        invoice.address_id as address_id,
                        round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual,
                        concat(invoice.year, '-', invoice.month) as invoice_name
                    FROM 
                        pay_receipt_address_invoice invoice
                    INNER JOIN 
                        ref_address address 
                        ON address.id = invoice.address_id and invoice.company_id = {company_id}
                        AND address.type = '{address_type}'
                        AND concat(invoice.year, '-', invoice.month, '-01')::date <= '{period_year}-{period_month}-01'::date 
                    LEFT JOIN 
                        pay_address_payment_line payment 
                        ON payment.invoice_id = invoice.id 
                        AND payment.period_id IN (
                            SELECT pp.id 
                            FROM pay_period pp 
                            WHERE pp.company_id = {company_id} 
                            AND pp.address_type = '{address_type}' 
                            AND concat(pp.year, '-', pp.month, '-01')::date <= '{period_year}-{period_month}-01'::date 
                        )
                    GROUP BY  invoice.id
                ) last_balance
                where last_balance.residual > 0.0
                group by last_balance.address_id
            ) last_balance on last_balance.address_id = address.id
            left join pay_receipt_address_invoice invoice on invoice.address_id = address.id and invoice.company_id = {company_id} and invoice.year = '{period_year}' and invoice.month = '{period_month}' 
            left join pay_receipt_address receipt_address on receipt_address.id = invoice.receipt_address_id
            left join (
                select invoice.address_id as address_id, round(cast(sum(payment_line.amount) as numeric),2) as amount from pay_address_payment_line payment_line 
                inner join pay_receipt_address_invoice invoice on invoice.id = payment_line.invoice_id and invoice.company_id = {company_id}
                where payment_line.period_id = {id}
                group by invoice.address_id 
            ) total_paid on total_paid.address_id = address.id
            WHERE address.company_id = {company_id} and address.type = '{address_type}'
        """
        else:
            query = f"""
                select address.id as address_id, 
                first_balance.residual AS first_balance_amount,
                invoice.amount_total as invoiced_amount, 
                last_balance.residual as last_balance_amount, 
                last_balance.invoice_names as unpaid_invoices,
                old_report.inspector_id as inspector_id, 
                receipt_address.total_amount as receipt_amount,
                total_paid.amount as total_paid_amount,
                {id} as period_id
                from ref_address address
                inner join pay_period_report old_report on old_report.period_id = {id} and old_report.address_id = address.id
                left join (
                    select last_balance.address_id as address_id, round(cast(sum(last_balance.residual) as numeric),2) as residual
                    from (
                        SELECT 
                            invoice.address_id as address_id,
                            round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual
                        FROM 
                            pay_receipt_address_invoice invoice
                        INNER JOIN 
                            ref_address address 
                            ON address.id = invoice.address_id and invoice.company_id = {company_id}
                            AND address.type = '{address_type}'
                            AND concat(invoice.year, '-', invoice.month, '-01')::date < '{period_year}-{period_month}-01'::date 
                        LEFT JOIN 
                            pay_address_payment_line payment 
                            ON payment.invoice_id = invoice.id 
                            AND payment.period_id IN (
                                SELECT pp.id    
                                FROM pay_period pp 
                                WHERE pp.company_id = {company_id} 
                                AND pp.address_type = '{address_type}' 
                                AND concat(pp.year, '-', pp.month, '-01')::date < '{period_year}-{period_month}-01'::date 
                            )
                        GROUP BY  invoice.id
                    ) last_balance
                    where last_balance.residual > 0.0
                    group by last_balance.address_id
                ) first_balance on first_balance.address_id = address.id
                left join (
                    select last_balance.address_id as address_id, round(cast(sum(last_balance.residual) as numeric),2) as residual, string_agg(last_balance.invoice_name, ', ') as invoice_names
                    from (
                        SELECT 
                            invoice.address_id as address_id,
                            round(cast(invoice.amount_total as numeric),2) - round(cast(COALESCE(SUM(payment.amount), 0) as numeric), 2) AS residual,
                            concat(invoice.year, '-', invoice.month) as invoice_name
                        FROM 
                            pay_receipt_address_invoice invoice
                        INNER JOIN 
                            ref_address address 
                            ON address.id = invoice.address_id and invoice.company_id = {company_id}
                            AND address.type = '{address_type}'
                            AND concat(invoice.year, '-', invoice.month, '-01')::date <= '{period_year}-{period_month}-01'::date 
                        LEFT JOIN 
                            pay_address_payment_line payment 
                            ON payment.invoice_id = invoice.id 
                            AND payment.period_id IN (
                                SELECT pp.id 
                                FROM pay_period pp 
                                WHERE pp.company_id = {company_id} 
                                AND pp.address_type = '{address_type}' 
                                AND concat(pp.year, '-', pp.month, '-01')::date <= '{period_year}-{period_month}-01'::date 
                            )
                        GROUP BY  invoice.id
                    ) last_balance
                    where last_balance.residual > 0.0
                    group by last_balance.address_id
                ) last_balance on last_balance.address_id = address.id
                left join pay_receipt_address_invoice invoice on invoice.address_id = address.id and invoice.company_id = {company_id} and invoice.year = '{period_year}' and invoice.month = '{period_month}' 
                left join pay_receipt_address receipt_address on receipt_address.id = invoice.receipt_address_id
                left join (
                    select invoice.address_id as address_id, round(cast(sum(payment_line.amount) as numeric),2) as amount from pay_address_payment_line payment_line 
                    inner join pay_receipt_address_invoice invoice on invoice.id = payment_line.invoice_id and invoice.company_id = {company_id}
                    where payment_line.period_id = {id}
                    group by invoice.address_id 
                ) total_paid on total_paid.address_id = address.id
                WHERE address.company_id = {company_id} and address.type = '{address_type}'
            """
        self.env.cr.execute(query)
        datas = self.env.cr.dictfetchall()
        self.env['pay.period.report'].sudo().search([('period_id', '=', id)]).unlink()
        self.env['pay.period.report'].sudo().create(datas)

    def draft(self):
        self.state = 'draft'

    @api.model
    def create(self, vals):

        existing = self.search([
            ('year', '=', vals.get('year')),
            ('month', '=', vals.get('month')),
            ('company_id', '=', vals.get('company_id')),
            ('address_type', '=', vals.get('address_type'))
        ])

        if existing:
            if not existing.active:

                existing.write({
                    'active': True,
                    'state': 'opened',
                })
                return existing
            else:

                raise ValidationError('Ижил утгатай мөчлөг аль хэдийн үүссэн байна!')


        return super(PayPeriod, self).create(vals)

    def allocate_advanced_payment(self):
        company_id = self.company_id.id
        bank_account_list = self.env['pay.bank.account'].search(
            [('type', '=', 'incoming'), ('company_id', '=', company_id)])
        for account in bank_account_list:
            payment = self.env['pay.address.payment'].search([('account_id', '=', account.id), ('state', '!=', 'done')],
                                                             order="address_id asc")
            payment.register_invoices()
            self.env.cr.commit()

class PayPeriodReport(models.Model):
    _name = 'pay.period.report'
    _description = 'Санхүүгийн мөчлөгийн тайлан'
    address_id = fields.Many2one('ref.address', 'Тоот', index=True, tracking=True, required=True)
    inspector_id = fields.Many2one('hr.employee', 'Байцаагч')
    first_balance_amount = fields.Float('Эхний үлдэгдэл')
    last_balance_amount = fields.Float('Эцсийн үлдэгдэл')
    unpaid_invoices = fields.Text('unpaid_invoices')
    receipt_amount = fields.Float('Төлбөл зохих дүн')
    invoiced_amount = fields.Float('Нэхэмжилсэн дүн')
    total_paid_amount = fields.Float('Төлсөн дүн')
    period_id = fields.Many2one('pay.period', 'Мөчлөг', index=True, tracking=True, required=True)


"""
select address.id as address_id, coalesce(invoiced.amount_residual,0.0) as invoiced_amount_residual, invoiced.invoiced_string_data as invoiced_string_data, invoiced.invoice_count as invoiced_count,
payment.residual_amount as payment_residual_amount, reconciled.amount as reconciled_amount, reconciled.payment_ids as reconciled_payment_ids, 
reconciled.invoice_ids as reconciled_invoice_ids,
reconciled.ids as reconciled_ids,
inspector.id as inspector_id, inspector.name as inspector_name, address.type as address_type,
address.company_id as company_id, 27 as period_id, c1_payment.amount as c1_payment_amount, advance_payment.amount as advance_payment_amount, tz_payment.amount as tz_payment_amount
from ref_address address
inner join hr_employee inspector on inspector.id = address.inspector_id 
left join (
    select invoice.address_id as address_id, sum(invoice.amount_residual) as amount_residual, string_agg(concat(invoice.year, '-', invoice.month) ,',') invoiced_string_data, count(invoice.id) as invoice_count
    from pay_receipt_address_invoice invoice
    inner join ref_address address on address.id = invoice.id and address.type = 'OS'
    where invoice.payment_state != 'paid' and invoice.company_id = 4 and concat(invoice.year, '-', invoice.month, '-01')::date <= '2024-08-01'::date
    group by invoice.address_id
) invoiced on invoiced.address_id = address.id
left join (
    select payment.address_id as address_id, sum(payment.residual_amount) as residual_amount
    from pay_address_payment payment
    inner join ref_address address on address.id = payment.address_id and address.type = 'OS'
    inner join pay_bank_account account on account.id = payment.account_id and account.company_id = 4
    where payment.residual_amount > 0.0 and extract(year from payment.date)::integer = 2024 and extract(month from payment.date)::integer = 9
    group by payment.address_id
) payment on payment.address_id = address.id
left join (
    select invoice.address_id as address_id, sum(payment_line.amount) as amount, string_agg(payment_line.payment_id::text,',') as payment_ids, string_agg(payment_line.invoice_id::text,',') as invoice_ids, string_agg(payment_line.id::text,',') as ids
    from pay_receipt_address_invoice invoice
    inner join pay_address_payment_line payment_line on payment_line.invoice_id = invoice.id and payment_line.period_id = 27
    where invoice.company_id = 4
    group by invoice.address_id
) reconciled on reconciled.address_id = address.id
left join (
	SELECT 
        invoice.address_id AS address_id, 
        SUM(payment_line.amount) AS amount 
    FROM 
        pay_receipt_address_invoice invoice
    INNER JOIN 
        pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id
    INNER JOIN 
        pay_address_payment payment ON payment.id = payment_line.payment_id 
        AND EXTRACT(YEAR FROM payment.date)::integer = 2024::integer 
        AND EXTRACT(MONTH FROM payment.date)::integer = 9::integer
    WHERE 
        invoice.company_id = 4
        AND CONCAT(invoice.year, '-', invoice.month, '-', '01')::date < '2024-08-01'::date
    GROUP BY 
        invoice.address_id
) c1_payment on address.id = c1_payment.address_id
left join (
	SELECT 
	    invoice.address_id AS address_id, 
	    SUM(payment_line.amount) AS amount 
	FROM 
	    pay_receipt_address_invoice invoice
	inner join ref_address address on address.id = invoice.address_id and address.type = 'OS'
	INNER JOIN 
	    pay_address_payment_line payment_line ON payment_line.invoice_id = invoice.id
	INNER JOIN 
	    pay_address_payment payment ON payment.id = payment_line.payment_id and  EXTRACT(YEAR FROM payment.date)::integer = 2024 
	    AND EXTRACT(MONTH FROM payment.date)::integer = 9::integer
	WHERE 
	    invoice.company_id = 4
	    AND invoice.year::integer = 2024::integer 
	    AND invoice.month::integer = 8::integer
	GROUP BY 
	    invoice.address_id
) tz_payment on tz_payment.address_id = address.id
left join (
	    SELECT 
        invoice.address_id AS address_id, 
        SUM(payment_line.amount) AS amount 
    FROM 
        pay_address_payment_line payment_line
    INNER JOIN 
        pay_receipt_address_invoice invoice ON invoice.id = payment_line.invoice_id 
        AND invoice.year::integer = 2024::integer 
        AND invoice.month::integer = 8::integer 
        AND invoice.company_id = 4
    inner join ref_address address on address.id = invoice.id and address.type = 'OS'
    INNER JOIN 
        pay_address_payment payment ON payment.id = payment_line.payment_id 
        AND payment.date < '2024-09-01'::date
    GROUP BY 
        invoice.address_id
) advance_payment on advance_payment.address_id = address.id
where address.company_id = 4
"""

# Period
# class PayPeriodOsnagStatus(models.model):
