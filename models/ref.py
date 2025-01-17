from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.exceptions import ValidationError, UserError
import requests
from itertools import groupby
from odoo import tools
import logging

from odoo.release import FINAL
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT

import xlrd
from datetime import datetime

_logger = logging.getLogger('TUVSHUU:')
ADDRESS_TYPE = [
    ('OS', 'Орон сууц'),
    ('AAN', 'Аж ахуй нэгж')
]


# class Hut(models.Model):
#     _name = "ref.hut"
#     _description = "ХҮТ"
#     # _rec_name = "zogsool"
#
#     code = fields.Char("Код", required=True)
#     name = fields.Char("Нэр", required=True)
#     phone = fields.Char("Албан утас", required=True)
#     description = fields.Char("Тайлбар", required=True)
#     active = fields.Boolean(string="Active", default=True, tracking=True)


# OS, AAN
# class AddressType(models.Model):
#     _name = "ref.address.type"
#     _description = "Тоотын төрөл"
#
#     name = fields.Char("Төрөл", required=True)
#
#     active = fields.Boolean(string="Active", default=True, tracking=True)


class Import(models.TransientModel):
    _inherit = 'base_import.import'

    def _read_xls_book(self, book, sheet_name):
        sheet = book.sheet_by_name(sheet_name)
        # emulate Sheet.get_rows for pre-0.9.4
        for rowx, row in enumerate(map(sheet.row, range(sheet.nrows)), 1):
            values = []
            for colx, cell in enumerate(row, 1):
                if cell.ctype is xlrd.XL_CELL_NUMBER:
                    is_float = cell.value % 1 != 0.0
                    values.append(
                        str(cell.value)
                        if is_float
                        else str(int(cell.value))
                    )
                elif cell.ctype is xlrd.XL_CELL_DATE:
                    is_datetime = cell.value % 1 != 0.0
                    # emulate xldate_as_datetime for pre-0.9.3
                    dt = datetime(*xlrd.xldate.xldate_as_tuple(cell.value, book.datemode))
                    values.append(
                        dt.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                        if is_datetime
                        else dt.strftime(DEFAULT_SERVER_DATE_FORMAT)
                    )
                elif cell.ctype is xlrd.XL_CELL_BOOLEAN:
                    values.append(u'True' if cell.value else u'False')
                elif cell.ctype is xlrd.XL_CELL_ERROR:
                    raise ValueError(
                        _("Invalid cell value at row %(row)s, column %(col)s: %(cell_value)s") % {
                            'row': rowx,
                            'col': colx,
                            'cell_value': xlrd.error_text_from_code.get(cell.value,
                                                                        _("unknown error code %s", cell.value))
                        }
                    )
                else:
                    values.append(str(cell.value).strip())
            if any(x for x in values if x.strip()):
                yield values


class Organization(models.Model):
    _name = "ref.organization"
    _description = "Байгууллага"
    _rec_name = "name"

    name = fields.Char("Нэр", required=True, tracking=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)


SERVICE_CATEGORY = [
    ('counter', 'Усны тоолуур'),
    ('thermal_counter', 'Дулааны тоолуур'),
    ('each_counter', 'Бүх тоолуур'),
    ('has_no_counter', 'Тоолуургүй'),
    ('additional_service', 'Нэмэлт үйлчилгээ'),
    ('user_service', 'Хэрэглэгчийн үйлчилгээ'),
    ('service_payment', 'Төлбөрт үйлчилгээ'),
    ('service_timed_condition', 'Хугацаат үйлчилгээ')
]


class ServiceType(models.Model):
    _name = "ref.service.type"
    _description = "Үйлчилгээний төрөл"
    _rec_name = "name"

    org_id = fields.Many2one(
        "ref.organization", "Байгууллага", required=True, tracking=True
    )
    name = fields.Char("Нэр", required=True, tracking=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)
    tr_type = fields.Char('TR type', required=True)
    category = fields.Selection(SERVICE_CATEGORY, "Ангилал", required=False, tracking=True)

    def name_get(self):
        result = []
        for obj in self:
            name = f"{obj.name} /{obj.org_id.name}/"
            result.append((obj.id, name))
        return result


class PriceList(models.Model):
    _name = "ref.pricelist"
    _description = "Тариф"
    _rec_name = "name"

    org_id = fields.Many2one(
        "ref.organization", "Байгууллага", required=True, tracking=True
    )
    service_type_id = fields.Many2one(
        "ref.service.type", "Үйлчилгээний төрөл", required=True, tracking=True
    )
    address_type = fields.Selection(ADDRESS_TYPE, "Тоотын төрөл", tracking=True)
    code = fields.Char('Код')
    category = fields.Selection(SERVICE_CATEGORY, "Тариф ангилал", required=True, tracking=True)
    type_id = fields.Many2one('ref.pricelist.type', 'Төрөл')
    name = fields.Char("Тариф", tracking=True, store=True, readonly=True, compute='_compute_name')
    price = fields.Float(string="Үнэ", default=0, tracking=True)
    noat_price = fields.Float(string="НӨАТ-ийн 10%", compute='_compute_noat_price', tracking=True)
    total_price = fields.Float(string="Нийт үнэ", compute='_compute_total_price', tracking=True)
    uom_id = fields.Many2one('uom.uom', 'Хэмжих нэгж', required=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)
    account_income_ids = fields.Many2many(
        'account.account',
        string='Орлогын данс',
        domain=lambda self: [
            ('deprecated', '=', False),
            ('internal_type', '=', 'other'),
            ('company_id', '=', self.env.company.id),
            ('is_off_balance', '=', False)
        ]
    )
    days = fields.Integer('Хоног', default=30)
    tax_product_code = fields.Integer('Татварын харгалзах 3 оронтой тоон код', default="111")
    classification_code = fields.Integer('Бүтээгдэхүүн, үйлчилгээний ангиллын 7 оронтой код', default="1730000")
    report_type = fields.Selection(
        [('heating', 'Дулаан'), ('pure_water_and_impure_water', 'Цэвэр бохир ус'), ('3', 'хог,радио,даатгал')],
        string='Тайлангын төрөл')

    @api.depends('price')
    def _compute_noat_price(self):
        for obj in self:
            obj.noat_price = obj.price * 0.1 if obj.vat_type == 'VAT_ABLE' else 0

    @api.depends('price')
    def _compute_total_price(self):
        for obj in self:
            obj.total_price = obj.price * 1.1 if obj.vat_type == 'VAT_ABLE' else obj.price

    # @api.depends('price', 'uom_id.name', 'address_type', 'category')
    # def _compute_name(self):
    #     for obj in self:
    #         # Use address_type and category for additional formatting if needed
    #         address_type = dict(ADDRESS_TYPE).get(obj.address_type, '')
    #         category = dict(SERVICE_CATEGORY).get(obj.category, '')
    #         obj.name = f"{obj.code} {obj.uom_id.name} /{address_type}/{category}/"
    #
    # def name_get(self):
    #     result = []
    #     for obj in self:
    #         address_type = dict(ADDRESS_TYPE).get(obj.address_type, '')
    #         category = dict(SERVICE_CATEGORY).get(obj.category, '')
    #         formatted_name = f"{obj.code} {obj.uom_id.name} /{address_type}/{category}/"
    #         result.append((obj.id, formatted_name))
    #     return result

    @api.depends('price', 'uom_id.name', 'address_type')
    def _compute_name(self):
        for obj in self:
            obj.name = f"{obj.price} - {obj.uom_id.name or ''}"

    def name_get(self):
        service_categ_dict = dict(SERVICE_CATEGORY)
        address_type_dict = dict(ADDRESS_TYPE)
        result = []
        for obj in self:
            name = f"{obj.name or ''} /{address_type_dict.get(obj.address_type, '')}/{service_categ_dict.get(obj.category, '')}/"
            result.append((obj.id, name))
        return result

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        if operator == '=':
            args += [('id', operator, name)]
        elif operator == 'ilike':
            args += [(self._rec_name, operator, name)]
        records = self.search(args, limit=limit)
        return records.name_get()

    def write(self, vals):
        if 'price' in vals:
            for record in self:
                if record.id and record.price != vals['price']:
                    raise UserError('Үнэ нь нэгэнт тогтоогдсон бол өөрчлөх боломжгүй!')
                if vals['price'] < 0:
                    raise UserError('Үнэ нь 0-ээс их байх ёстой!')
        return super(PriceList, self).write(vals)


class PricelistType(models.Model):
    _name = 'ref.pricelist.type'
    name = fields.Char('Нэр')
    active = fields.Boolean('Active')


class Aimag(models.Model):
    _name = "ref.aimag"
    _description = "Аймаг"
    _rec_name = "name"

    name = fields.Char("Нэр", required=True, tracking=True)
    code = fields.Char('AimagName (bank)', required=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)


class Duureg(models.Model):
    _name = "ref.duureg"
    _description = "Дүүрэг"
    _rec_name = "name"

    aimag_id = fields.Many2one("ref.aimag", "Аймаг", required=True, tracking=True)
    name = fields.Char("Нэр", required=True, tracking=True)
    code = fields.Char('SymName (bank)', required=True)
    short_name = fields.Char('Товч нэр', required=True)
    full_name = fields.Char('Бүтэн нэр', compute="", store=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)

    @api.depends('aimag_id.name', "name")
    def compute_full_name(self):
        for obj in self:
            obj.full_name = f"{obj.aimag_id.name}, {obj.name}"


class Horoo(models.Model):
    _name = "ref.horoo"
    _description = "Хороо"
    _rec_name = "full_name"

    duureg_id = fields.Many2one("ref.duureg", "Дүүрэг", required=True, tracking=True)
    name = fields.Char("Нэр", required=True, tracking=True)
    code = fields.Char('HorooName (bank)', required=True)
    full_name = fields.Char('Бүтэн нэр', compute="compute_full_name", store=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)

    @api.depends("duureg_id.name", 'duureg_id.aimag_id.name', "name")
    def compute_full_name(self):
        for obj in self:
            obj.full_name = f"{obj.duureg_id.aimag_id.name}, {obj.duureg_id.short_name}, {obj.name}"


class MainApartment(models.Model):
    _name = "ref.apartment.main"
    _description = "Үндсэн байр"
    _rec_name = "full_name"
    _sql_constraints = [
        ('apartment_uniq', 'unique (apartment, company_id)', 'Байр давхардсан байна!'),
    ]
    # hut_id = fields.Many2one("ref.hut", "ХҮТ", tracking=True)
    company_id = fields.Many2one('res.company', "ХҮТ", tracking=True, required=True,
                                 default=lambda self: self.env.company.id)

    aimag_id = fields.Many2one('ref.aimag', 'Хот/Аймаг', readonly=True, related="duureg_id.aimag_id")
    duureg_id = fields.Many2one("ref.duureg", "Дүүрэг", tracking=True, related="horoo_id.duureg_id",
                                domain="[('aimag_id', '=', aimag_id)]", readonly=True)
    horoo_id = fields.Many2one("ref.horoo", "Хороо", tracking=True, readonly=False, required=True)
    town = fields.Char("Хотхон", tracking=True, required=False)
    apartment = fields.Char("Байр", required=True, tracking=True)
    full_name = fields.Char('Бүтэн нэр', compute="compute_full_name", required=False, store=True)
    location = fields.Text("Байршил", required=True, tracking=True)
    description = fields.Text("Тайлбар", required=True, tracking=True)
    has_apartment = fields.Boolean('Байр үүссэн эсэх', compute="_compute_has_apartment", store=False)

    @api.depends('aimag_id.name', 'duureg_id.short_name', 'horoo_id', 'town', 'apartment')
    def compute_full_name(self):
        for obj in self:
            obj.full_name = f"{obj.duureg_id.aimag_id.name}, {obj.duureg_id.short_name}, {obj.horoo_id.name}, {obj.town}, {obj.apartment}"

    def _compute_has_apartment(self):
        for obj in self:
            obj.has_apartment = True if self.env['ref.apartment'].search_count(
                [('main_apartment_id', '=', obj.id)]) > 0 else False

    active = fields.Boolean(string="Active", default=True, tracking=True)

    def create_apartment(self):
        for obj in self:
            return {
                'name': _('Үндсэн байрнаас байр үүсгэх'),
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'ref.apartment',
                'target': 'new',
                'context': {
                    'default_main_apartment_id': obj.id,
                    'default_town': obj.town,
                    'default_company_id': obj.company_id.id,
                    'default_horoo_id': obj.horoo_id.id,
                    'default_name': obj.location
                },
            }


class Apartment(models.Model):
    _name = "ref.apartment"
    _description = "Байр"
    _rec_name = "full_name"
    _order = "code asc"
    _sql_constraints = [
        # ('main_apartment_id_uniq', 'unique (main_apartment_id)', 'Харгалзах үндсэн байрыг өөр байрнд холбосон байна!'),
        ('code_uniq', 'unique (code, corps, company_id)', 'Корпс болон код, компани давхардсан байна!'),
    ]
    company_id = fields.Many2one("res.company", "ХҮТ", tracking=True, readonly=False,
                                 default=lambda self: self.env.company.id)
    # hut phone
    aimag_id = fields.Many2one("ref.aimag", "Аймаг", tracking=True, related="duureg_id.aimag_id", readonly=True,
                               store=True)
    duureg_id = fields.Many2one("ref.duureg", "Дүүрэг", tracking=True, domain="[('aimag_id', '=', aimag_id)]",
                                related="horoo_id.duureg_id", readonly=True, store=True)
    horoo_id = fields.Many2one("ref.horoo", "Хороо", tracking=True, readonly=False, required=True)
    # inspector_id = fields.Many2one('hr.employee', 'Байцаагч', required=False, domain=lambda self: [('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)])
    full_name = fields.Char(compute="compute_full_name", store=True, string='Бүтэн нэр')
    main_apartment_id = fields.Many2one("ref.apartment.main", "Үндсэн байр", tracking=True)
    # address - Many2one

    town = fields.Char("Хотхон", tracking=True)
    code = fields.Char("Байрны код", required=True)  # huuchin ner
    name = fields.Char("Нэршил", required=False)
    kontor = fields.Char("Контор", required=False)
    corps = fields.Char("Корпус", required=False)
    active = fields.Boolean(string="Active", default=True, tracking=True)
    total_address_count = fields.Integer('Нийт тоотуудын тоо', compute="_compute_total_address_count", store=False)
    address_ids = fields.One2many('ref.address', 'apartment_id', string='Тоотууд')

    def _compute_total_address_count(self):
        for obj in self:
            obj.total_address_count = self.env['ref.address'].search_count(
                [('active', '=', True), ('apartment_id', '=', obj.id)])

    @api.depends('code', 'aimag_id.name', 'duureg_id.short_name', 'horoo_id.name', 'horoo_id', 'duureg_id', 'aimag_id')
    def compute_full_name(self):
        for obj in self:
            # if obj.main_apartment_id:
            #     obj.full_name = f"{obj.main_apartment_id.full_name} ({obj.code})"
            # else:
            obj.full_name = f"{obj.aimag_id.name}, {obj.duureg_id.short_name}, {obj.horoo_id.name}, {obj.code}"

    def show_address_list(self):
        for obj in self:
            return {
                'name': _('Тоот'),
                'type': 'ir.actions.act_window',
                'view_mode': 'tree',
                'target': 'current',
                'res_model': 'ref.address',
                'domain': [('apartment_id', '=', obj.id)]
            }
    # def change_inspector_id(self):
    #     return {
    #         'name': _('Байцаагч өөрчлөх'),
    #         'type': 'ir.actions.act_window',
    #         'view_mode': 'form',
    #         'target': 'new',
    #         'res_model': 'ref.apartment.change.inspector.wizard'
    #     }

    # def write(self, vals):
    #     result = super()


class AddressCategory(models.Model):
    _name = 'ref.address.category'
    _description = 'Тоотын ангилал'
    name = fields.Char('Нэр', required=True)
    active = fields.Boolean('Active')


class AddressActivityType(models.Model):
    _name = 'ref.address.activity.type'
    name = fields.Char('Нэр', required=True)
    active = fields.Boolean('Active')


class AddressCode(models.Model):
    _name = 'ref.address.code'
    code = fields.Char('Код', index=True, tracking=True)


class Address(models.Model):
    _name = "ref.address"
    _description = "Тоот"
    _rec_name = "full_address"
    _order = "address asc"
    _sql_constraints = [
        ('code_uniq', 'unique (code)', 'Хэрэглэгчийн код давхцаж байна!'),
    ]
    company_id = fields.Many2one("res.company", "ХҮТ", tracking=True, index=True, readonly=True,
                                 compute="_compute_company_id", store=True)

    @api.depends('apartment_id.company_id', 'apartment_id')
    def _compute_company_id(self):
        for obj in self:
            obj.company_id = obj.apartment_id.company_id.id

    code = fields.Char("Хэрэглэгчийн код", required=False)
    # type_id = fields.Many2one("ref.address.type", "Тоотын төрөл", tracking=True)
    type = fields.Selection(ADDRESS_TYPE, string="Тоотын төрөл", tracking=True, required=True, index=True)
    # duureg
    # horoo
    # hayag - Many2one
    horoo_id = fields.Many2one('ref.horoo', 'Хороо', store=True, tracking=True, related="apartment_id.horoo_id")
    duureg_id = fields.Many2one('ref.duureg', 'Дүүрэг', store=True, tracking=True, related="apartment_id.duureg_id")

    apartment_id = fields.Many2one("ref.apartment", "Байр", index=True, tracking=True, ondelete="cascade")
    apartment_code = fields.Char('Байрны код', related="apartment_id.code")
    address = fields.Char("Тоот", required=True)
    full_address = fields.Char('Тоотын бүтэн нэр', compute="compute_full_address", store=True)

    @api.depends('apartment_id', 'apartment_id.code', 'address', 'code', 'apartment_id.duureg_id.name',
                 'apartment_id.duureg_id', 'apartment_id.horoo_id', 'apartment_id.horoo_id.name')
    def compute_full_address(self):
        for obj in self:
            # obj.full_address = f"{obj.apartment_id.duureg_id.name}/{obj.apartment_id.horoo_id.name}/{obj.apartment_id.code}/{obj.address} - {obj.code}"
            obj.full_address = f"{obj.code} - {obj.address}/{obj.apartment_id.code}/{obj.apartment_id.horoo_id.name}/{obj.apartment_id.duureg_id.name}"
            if (obj.partner_id):
                obj.partner_id.name = obj.full_address

    # apartmentnii huuchin toot
    surname = fields.Char("Овог", tracking=True)
    # ssnid = fields.Char('Регистерийн дугаар')
    name = fields.Char("Нэр", required=True, tracking=True)
    # anglilal - Many2one
    category_id = fields.Many2one('ref.address.category', 'Ангилал', required=True)
    # chiglel  - Many2one
    activity_type_id = fields.Many2one('ref.address.activity.type', 'Үйл ажиллагааны төрөл', required=True)

    phone = fields.Char("Утас", required=False)
    sms = fields.Char("Мессеж", required=False)
    family = fields.Integer(string="Ам бүл", default=1, tracking=True)

    pure_water = fields.Boolean(string="Цэвэр ус", default=True, tracking=True)
    impure_water = fields.Boolean(string="Бохир ус", default=True, tracking=True)
    heating = fields.Boolean(string="Халаалт", default=True, tracking=True)
    proof = fields.Boolean(string="Баримт", default=True, tracking=True)
    heating_water_fee = fields.Boolean(string="УХХ", default=True, tracking=True)
    mineral_water = fields.Boolean(string='Ус рашаан ашигласны татвар', default=False, tracking=True)
    # tsever_us = fields.Boolean(string="Цэвэр ус", default=True, tracking=True)
    # buhir_us = fields.Boolean(string="Бохир ус", default=True, tracking=True)
    # uxx = fields.Boolean(string="УХХ", default=True, tracking=True)
    # halaalt = fields.Boolean(string="Халаалт", default=True, tracking=True)
    # barimt = fields.Boolean(string="Баримт", default=True, tracking=True)

    uzeli = fields.Char("Узель", tracking=True)

    # baitsaagch - Many2one
    # inspector_id = fields.Many2one('hr.employee', 'Байцаагч', required=False, compute="compute_inspector_id", store=True)

    inspector_id = fields.Many2one('hr.employee', 'Байцаагч', index=True, required=True, readonly=False,
                                   domain=lambda self: [
                                       ('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)])
    # avlaga - Many2one
    description = fields.Char("Тайлбар", tracking=True)
    extra = fields.Char("Нэмэлт", tracking=True)
    active = fields.Boolean(string="Идэвхитэй", default=True, tracking=True)
    #
    # owner_id = fields.Many2one('auth.user', 'Эзэмшигч', required=False)
    # renter_id = fields.Many2one('auth.user', 'Түрээслэгч')
    # Django user id
    owner_id = fields.Integer('Эзэмшигч')
    # Django user id
    renter_id = fields.Integer('Түрээслэгч')

    org_account = fields.Char('Аж ахуй нэгжийн данс', )
    user_history_ids = fields.One2many('ref.address.user.history', 'address_id', string='Байр эзэмшигчийн түүх')
    contract_ids = fields.One2many('ref.address.contract', 'address_id', string="Гэрээний мэдээлэл")
    square_ids = fields.One2many('ref.address.square', 'address_id', string='Тайлбайн хэмжээ түүх')
    family_ids = fields.One2many('ref.address.family', 'address_id', string='Байран дахь ам бүлийн тоо /Түүх/')

    water_counter_ids = fields.One2many('counter.counter', 'address_id', string='Усны тоолуур',
                                        domain=[('category', '=', 'counter')])
    thermal_counter_ids = fields.One2many('counter.counter', 'address_id', string='Дулааны тоолуур',
                                          domain=[('category', '=', 'thermal_counter')])
    user_service_ids = fields.One2many('service.address', 'address_id', 'Бусад үйлчилгээ',
                                       domain=[('type', '=', 'user_service')])
    # usnii tooluur tab
    # dulaanii tooluur tab
    # busad uilchilgee tab
    old_address = fields.Char('Хуучин байрны тоот ')
    fext = fields.Char('Fext', tracking=True)
    receivable_uid = fields.Many2one('res.users', 'Авлага')
    partner_id = fields.Many2one('res.partner', 'partner', ondelete="cascade", readonly=True)
    invoice_residual = fields.Float('Нэхэмжлэлийн үлдэгдэл', store=False, compute="_compute_residual_amount")
    payment_residual = fields.Float('Төлөлтийн үлдэгдэл', store=False, compute="_compute_residual_amount")
    parent_id = fields.Many2one('ref.address', 'Эцэг')
    float_address = fields.Float('Float address', compute="_compute_float_address", store=True)

    @api.depends('address')
    def _compute_float_address(self):
        ids = self.ids
        if not ids:
            return
        query = f"""
            SELECT ra.id as id, CAST(REGEXP_REPLACE(ra.address , '[^0-9\.]', '', 'g') AS FLOAT) as address
            FROM ref_address ra
            WHERE ra.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
            ORDER BY ra.address::float desc;
        """
        self.env.cr.execute(query)
        datas = self.env.cr.dictfetchall()

        datas = groupby(datas, key=lambda x: x['id'])
        datas = {key: list(group) for key, group in datas}
        for obj in self:
            id = obj.id
            obj.float_address = datas.get(id)[0].get('address') if datas.get(id) else False

    def _compute_residual_amount(self):
        ids = self.ids
        if (len(ids) < 1):
            return True
        query = f"""
            select payment.address_id as address_id,sum(payment.residual_amount) as residual_amount
            from pay_address_payment payment where payment.address_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and payment.state in ('processing', 'confirmed')
            group by payment.address_id"""
        self.env.cr.execute(query)
        payment_data_list = self.env.cr.dictfetchall()
        payment_data_list = groupby(payment_data_list, key=lambda x: x['address_id'])
        payment_data_list = {key: list(group) for key, group in payment_data_list}
        query = f"""
            select invoice.address_id as address_id, sum(invoice.amount_residual) as residual_amount
            from pay_receipt_address_invoice invoice 
            where invoice.address_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"} and invoice.state = 'posted' and invoice.payment_state != 'paid'
            group by invoice.address_id 
        """
        self.env.cr.execute(query)
        invoice_data_list = self.env.cr.dictfetchall()
        invoice_data_list = groupby(invoice_data_list, key=lambda x: x['address_id'])
        invoice_data_list = {key: list(group) for key, group in invoice_data_list}
        for obj in self:
            id = obj.id
            obj.payment_residual = payment_data_list.get(id)[0].get('residual_amount') if payment_data_list.get(
                id) else 0.0
            obj.invoice_residual = invoice_data_list.get(id)[0].get('residual_amount') if invoice_data_list.get(
                id) else 0.0

    def show_payment(self):
        for obj in self:
            return {
                'name': _('Төлбөрүүд'),
                'type': 'ir.actions.act_window',
                'view_mode': 'tree,form',
                # 'view_id': self.env.ref('account.view_move_tree').id,
                'res_model': 'pay.address.payment',
                'domain': [('address_id', '=', obj.id)]
            }

    def show_invoice(self):
        for obj in self:
            return {
                'name': _('Нэхэмжлэлүүд'),
                'type': 'ir.actions.act_window',
                'view_mode': 'tree,form',
                # 'view_id': self.env.ref('account.view_move_tree').id,
                'res_model': 'pay.receipt.address.invoice',
                'domain': [('address_id', '=', obj.id)]
            }

    def change_inspector_id(self):
        return {
            'name': _('Байцаагч өөрчлөх'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'target': 'new',
            'res_model': 'ref.apartment.change.inspector.wizard'
        }

    # has_counter = fields.Boolean('Тоолууртай эсэх', compute="_compute_has_count", store=True)

    # def create_partner(self):
    #     for address in self:
    #         if not address.partner_id:
    #             partner_id = self.env['res.partner'].create({
    #                 "name": address.full_address,
    #                 "phone": address.phone,
    #                 'customer_rank': 1
    #             })
    #             address.write({
    #                 'partner_id': partner_id.id
    #             })

    # @api.depends('apartment_id.inspector_id','apartment_id')
    # def compute_inspector_id(self):
    #     for obj in self:
    #         obj.inspector_id = obj.apartment_id.inspector_id.id

    def unlink(self):
        for obj in self:
            obj.partner_id.write({
                "active": False
            })
        return super(Address, self).unlink()

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        if (operator == '='):
            args += [('code', operator, name)]
        elif (operator == 'ilike'):
            args += [(self._rec_name, operator, name)]
        splited_name = name.split('/')
        if (len(splited_name) == 2):
            args = [('apartment_code', '=', splited_name[0]), ('address', '=', splited_name[1])]
        if self.env.context.get('sudo'):
            args += [('active', '=', True), ('company_id', '=', self.env.companies.ids)]
            records = self.sudo().search(args, limit=limit)

        else:
            records = self.search(args, limit=limit)
        print(self.env.context)
        return records.name_get()

    def change_services(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Хэрэглэгчийн үйлчилгээ өөрчлөх'),
            'res_model': 'ref.address.change.services.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    @api.onchange('user_history_ids')
    def onchange_user_history(self):
        for obj in self:
            for line in obj.user_history_ids:
                if (line.state == 'now'):
                    obj.name = line.name
                    obj.surname = line.surname

    @api.onchange('family_ids')
    def onchange_family_ids(self):
        for obj in self:
            for line in obj.family_ids:
                if (line.state == 'active'):
                    obj.family = line.family

    def action_change_type(self):
        return {
            'name': _('Тоотын төрөл өөрчлөх'),
            'type': 'ir.actions.act_window',
            'target': 'new',
            'view_mode': 'form',
            'res_model': 'ref.address.change.type',
        }

    @api.model
    def create(self, vals):
        company_name: str = self.env.company.name
        address_type = self.env.user.access_type
        address_type = 1 if address_type == 'OS' else 0
        branch_code = company_name.split('-')
        branch_code: str = branch_code[1] if len(branch_code) > 1 else '00'
        branch_code = str(int(branch_code)).zfill(2)
        branch_code = branch_code.zfill(2)
        query = f"""
            SELECT ra.id as id, ra.code as code
            FROM ref_address_code ra
            WHERE cast(substring(ra.code, 3, 1) as integer) % 2 = {address_type} and substring(ra.code, 1, 2) = '{branch_code}'
            limit 1;
        """
        self.env.cr.execute(query)
        code = self.env.cr.dictfetchall()
        if code:
            vals['code'] = code[0].get('code')
        else:
            raise UserError('Боломжит хэрэглэгчийн код дууссан.! \nАдминтай холбогдно уу! ')
        result = super(Address, self).create(vals)
        self.env.cr.execute(f"""
            DELETE FROM ref_address_code where code = '{code[0].get('code')}';
        """)
        # self.env.cr.commit()
        return result


class AddressUserHistory(models.Model):
    _name = "ref.address.user.history"
    _description = "Эзэмшигчийн түүх"
    _rec_name = "name"

    address_id = fields.Many2one("ref.address", "ХҮТ", required=True, tracking=True, ondelete="cascade")
    surname = fields.Char("Овог", tracking=True)
    name = fields.Char("Нэр", required=True, tracking=True)
    phone = fields.Char("Утас", required=True)
    register = fields.Char("Регистр", tracking=True)
    email = fields.Char("Имэйл", tracking=True)
    ttd = fields.Char('TTD', tracking=True)
    ndug = fields.Char('NDug', tracking=True)
    state = fields.Selection(
        [
            ("now", "Одоогийн"),
            ("before", "Өмнөх"),
        ],
        default="now",
        string="Төлөв",
        tracking=True,
    )


class AddressContract(models.Model):
    _name = "ref.address.contract"
    _description = "Гэрээний мэдээлэл"
    _rec_name = "number"

    address_id = fields.Many2one("ref.address", "ХҮТ", required=True, tracking=True, ondelete="cascade")
    number = fields.Char("Гэрээний №", required=False, tracking=True)
    # os_type_id = fields.Many2one(
    #     "ref.address.osturul", "О.С төрөл", required=True, tracking=True
    # )
    resident_type = fields.Selection([
        ('owner', 'Байнгын'),
        ('renter', 'Түр'),
    ], string='Оршин суух төрөл')
    type = fields.Selection([
        ('', ''),
        ('', 'Хугацаат үйлчилгээний')
    ])
    attachment_id = fields.Many2one('ir.attachment', 'Хавсралт')
    start_date = fields.Date(string="Эхлэх огноо")
    end_date = fields.Date(string="Дуусах огноо")
    # hangagch tuluulj - baitsaagch
    user_name = fields.Char("Хэрэглэгч төлөөлж")
    state = fields.Selection(
        [
            ("active", "Идэвхитэй"),
            ("deactive", "Идэвхигүй"),
        ],
        default="active",
        string="Төлөв",
        tracking=True,
    )
    supervisor_id = fields.Many2one('res.users', 'Хянагч төлөөлж')


class AddressSquare(models.Model):
    _name = "ref.address.square"
    _description = "Талбайн хэмжээ"
    _rec_name = "square"

    address_id = fields.Many2one("ref.address", "ХҮТ", required=True, tracking=True, ondelete="cascade")

    square = fields.Float("Талбай", default=0, required=True)
    square_coef = fields.Float("Талбайн коэф", default=100)
    capacity = fields.Float("Эзэлхүүн", default=0, required=True)
    capacity_coef = fields.Float("Эзэлхүүн коэф", default=100)
    gradge_square = fields.Float("Граж талбай", default=0)
    public_ownership_square = fields.Float("Нийтийн эзэмшлийн талбай", default=0)
    description = fields.Text("Тайлбар")
    state = fields.Selection(
        [
            ("active", "Идэвхитэй"),
            ("deactive", "Идэвхигүй"),
        ],
        default="active",
        string="Төлөв",
        tracking=True,
    )


class AddressFamily(models.Model):
    _name = "ref.address.family"
    _description = "Ам бүлийн тоо"
    _rec_name = "family"

    address_id = fields.Many2one("ref.address", "Тоот", required=True, tracking=True, ondelete="cascade")

    family = fields.Integer("Ам бүлийн тоо", required=True)
    description = fields.Text("Тайлбар")
    state = fields.Selection(
        [
            ("active", "Идэвхитэй"),
            ("deactive", "Идэвхигүй"),
        ],
        default="active",
        string="Төлөв",
        tracking=True,
    )


class Logging(models.Model):
    _inherit = 'ir.logging'
    request = fields.Text('Response')


class ApiLog(models.Model):
    _name = 'nc.api.log'
    payment_reference = fields.Char("Дотоот нэхэмжлэх дугаар", max_length=50)
    user_id = fields.Integer('Auth user id') # django uid
    pay_receipt_address_invoice_id = fields.Many2one(
        'pay.receipt.address.invoice', string="Нэхэмжлэх", ondelete="cascade"
    )
    system_log_ids = fields.Many2many('ir.logging', string='Log id')
    STATUS_CHOICES = [
        ("success", "Success"),
        ("failure", "Failure"),
        ("pending", "Pending"),
        ("timeout", "Timeout"),
    ]
    status = fields.Selection(STATUS_CHOICES, 'Төлөв', default="pending")
    STATE_CHOICES = [
        ("new", "Шинэ"),
        ("complete", "Баталгаажсан"),
        ("return", "Буцаагдсан"),
    ]
    state = fields.Selection(
        STATE_CHOICES, default="new", string="Төлөв"
    )
    status_code = fields.Integer('Status code')
    message = fields.Text('Message')
    is_paid = fields.Boolean("Төлөгдсөн эсэх", default=False)


class SmtpConfirmation(models.Model):
    _name = "nc.smtpconfirmation"
    _description = "SMTP Confirmation"

    email = fields.Char(string="Имэйл хаяг", required=True)
    code = fields.Integer(string="Баталгаажуулах код", default=0)
    is_used = fields.Boolean(string="Ашигласан", default=False)
    phone = fields.Char('Phone')


class CentralHeatingStation(models.Model):
    _name = 'ref.central.heating.station'
    _description = 'ЦТП'

    name = fields.Char('Нэр', required=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True, default=lambda self: self.env.user.company_id.id)
    line_ids = fields.One2many('ref.central.heating.station.line', 'station_id', 'Мөр')

    def show_details(self):
        for obj in self:
            return {
                'name': _('ЦТП мөр'),
                'type': 'ir.actions.act_window',
                'target': 'current',
                'view_mode': 'tree',
                'res_model': 'ref.central.heating.station.line',
                'domain': [('station_id', '=', obj.id)]
            }
CENTRAL_HEATING_STATION_LINE_TYPES = [
        ('all', 'Бүгд'),
        ('pure_water', 'Цэвэр ус'),
        ('impure_water', 'Бохир ус'),
        ('hot_water', 'Халуун ус'),
        ('heating', 'Халаалт'),
]
class CentralHeatingStationLine(models.Model):
    _name = 'ref.central.heating.station.line'
    _description = 'ЦТП мөр'

    type = fields.Selection(CENTRAL_HEATING_STATION_LINE_TYPES, string="Төрөл", required=True)
    address_id = fields.Many2one('ref.address', 'Хаяг', required=True)
    apartment_id = fields.Many2one('ref.apartment', 'Байр', related="address_id.apartment_id", store=True)

    address_address = fields.Char('Тоот', related="address_id.address")
    apartment_code = fields.Char('Байрны код', related="apartment_id.code")

    address_type = fields.Selection(ADDRESS_TYPE, string='Тоотын төрөл', related="address_id.type")
    station_id  = fields.Many2one('ref.central.heating.station', 'ЦТП', required=True)
