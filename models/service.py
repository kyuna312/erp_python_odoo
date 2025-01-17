from calendar import month

from odoo import api, fields, models, _
from odoo.addons.base.models.ir_model import query_insert
from odoo.exceptions import ValidationError, UserError
import requests
from .ref import ADDRESS_TYPE
from itertools import groupby
# class Service(models.Model):
#     _name = 'service.service'
#     _description = 'Үйлчилгээ'
#     org_id = fields.Many2one('ref.organization', 'Байгууллага', required=True)
#     type_id = fields.Many2one('ref.service.type', 'Үйлчилгээний төрөл', required=True)
#
#     # address_type_id = fields.Many2one('ref.address.type', 'Төрөл')
#
#     address_type = fields.Selection(ADDRESS_TYPE, 'Тоотын төрөл', required=True)
#     pricelist_id = fields.Many2one('ref.pricelist', 'Тариф', required=True)
#
#     # oum_id = fields.Many2one('uom.uom', 'Хэмжих нэгж')
#     # tailber = fields.Text('Тайлбар', required=False)
#
#
from datetime import datetime
def get_years():
    year_list = []
    curr_year = int(datetime.now().strftime('%Y'))
    for i in range(curr_year, 2019, -1):
        year_list.append((str(i), str(i)))
    return year_list
class ServiceAddress(models.Model):
    _name = 'service.address'
    _description = 'Хэрэглэгчийн үйлчилгээ'

    _order = 'id desc'
    address_id = fields.Many2one('ref.address', 'Тоот', required=True)
    apartment_id = fields.Many2one('ref.apartment', 'Байр', related="address_id.apartment_id", readonly=True, store=True)
    address_address = fields.Char('Тоот', related="address_id.address")
    apartment_code = fields.Char('Байрны код', related="address_id.apartment_id.code")

    address_code = fields.Char('Хэрэглэгчийн код', related="address_id.code")
    inspector_id = fields.Many2one('hr.employee', 'Байцаагч', related="address_id.inspector_id", store=True)
    # address_apartment = fields.Char('Байр', related="address_id.apartment_id.name")
    # address_address = fields.Char('Тоот', related="address_id.address")
    address_surname = fields.Char('Овог', related="address_id.surname")
    address_name = fields.Char('Нэр', related="address_id.name")

    description = fields.Text('Тайлбар', required=False)
    value = fields.Float('Утга', default=1.0, required=True)
    percent = fields.Float('Хувь', default=100.0, required=True)

    service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээ', required=True, domain="[('org_id', '=', org_id)]")
    # service_type
    org_name = fields.Char('Байгууллага нэр', related="org_id.name")
    org_id = fields.Many2one('ref.organization', 'Байгууллага', required=True)

    is_noat = fields.Boolean('НӨАТ тооцох', default=False)
    pricelist_id = fields.Many2one('ref.pricelist', 'Тариф', domain="[('service_type_id', '=', service_type_id)]")

    day = fields.Integer('Өдөр', default=0)
    price = fields.Float('Үнийн дүн')
    type = fields.Selection([
        ('user_service', 'Хэрэглэгчийн үйлчилгээ'),
        ('additional_service', 'Нэмэлт үйлчилгээ')
    ])
    company_id = fields.Many2one('res.company', 'ХҮТ', related="address_id.company_id", store=True)
    address_code_temp = fields.Char('Хэрэглэгчийн код (tmp)')
    # unnecessary field -> year and month
    year = fields.Selection(get_years(),string="Он", required=False)
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
    ],'Сар', required=False)
    active = fields.Boolean('Идэвхитэй', default=True)
    @api.model
    def create(self, vals):
        if (vals.get('pricelist_id')):
            vals['price'] = self.env['ref.pricelist'].browse(vals.get('pricelist_id')).price
        return super(ServiceAddress, self).create(vals)

    def write(self, vals):
        if(vals.get('pricelist_id')):
            vals['price'] = self.env['ref.pricelist'].browse(vals.get('pricelist_id')).price
        return super(ServiceAddress, self).write(vals)

    def change_days(self):
        return {
            'name': _('Хоног өөрчлөх'),
            'type': 'ir.actions.act_window',
            'target': 'new',
            'view_mode': 'form',
            'res_model': 'service.address.change.day.wizard',
            'view_id': self.env.ref('ub_kontor.view_service_address_change_day_wizard_form').id,
        }

class ServicePayment(models.Model):
    _name = "service.payment"
    _description = 'Төлбөрт үйлчилгээ'
    _order = 'id desc'
    _rec_name = "work_name"
    company_id = fields.Many2one('res.company', 'ХҮТ', related="address_id.company_id",)
    apartment_id = fields.Many2one('ref.apartment', 'Байр', readonly=True, related="address_id.apartment_id", store=False)
    address_id = fields.Many2one('ref.address', 'Тоот', required=True)
    address_code = fields.Char('Тоот', related="address_id.code")
    owner_name = fields.Char('Эзэмшигч', related="address_id.name")
    address_address = fields.Char( 'Тоот', related="address_id.address")
    apartment_code = fields.Char('Байрны код', related='address_id.apartment_id.code')
    inspector_id = fields.Many2one('hr.employee', related="address_id.inspector_id", store=True, string='Байцаагч')
    # user_id = fields.Many2one('auth.user', 'Хэрэглэгч')
    # Django user
    user_id = fields.Integer('Хэрэглэгч')


    service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээний төрөл', required=True,domain=[('category', '=', 'service_payment')], default=lambda self: self.env.get('ref.service.type').search([('category', '=', 'service_payment'),('active', '=', True)],order="id desc", limit=1))
    number = fields.Char('ТҮХ №')
    work_amount = fields.Float('Ажлын хөлс')
    material_amount = fields.Float('Материалын хөлс')
    employee_id = fields.Many2one('hr.employee', 'Ажилтан', required=True)
    bill_amount = fields.Float('ТҮ хуудас үнэ')
    work_name = fields.Char('Хийгдсэн ажил')
    heating_price = fields.Float('Халаалт буулгасан үнэ')
    material_name = fields.Char('Материалын нэр')
    water_heating_price = fields.Float("Ус буулгасан үнэ")
    date = fields.Date("Бодолт хийх огноо")
    served_date = fields.Date('Үйлчилгээ үзүүлсэн')
    total_amount = fields.Float('Нийт дүн')
    description = fields.Text('Тайлбар', required=False)

    SERVICE_TYPES = [('1', 'Усан хангамж'),
                                     ('2', 'Дулаан хангамж'),
                                     ('3', 'Цахилгаан')]
    service_type = fields.Selection(SERVICE_TYPES, string="Үйлгээний төрөл")
    # year = fields.Selection(get_years(),string="Он", compute="compute_month", store=True,required=True)
    # slip_number = fields.Char('Хуудасны дугаар')
    year = fields.Char(string="Он", compute="compute_month", store=True,required=False)
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
    ],'Сар', compute="compute_month", store=True,required=False)

    active = fields.Boolean('Идэвхитэй', default=True)

    @api.depends('date')
    def compute_month(self):
        for obj in self:
            if(obj.date):
                date = datetime.strptime(str(obj.date),'%Y-%m-%d')
                obj.year = f"{date.year}"
                obj.month = f'{date.month}' if int(date.month) > 9 else f'0{date.month}'

class ServiceTimedCondition(models.Model):
    _name = 'service.timed.condition'
    _description = 'Хугацаат үйлчилгээ'
    _order = 'id desc'
    
    company_id = fields.Many2one('res.company', 'ХҮТ', default=lambda self: self.env.company.id, readonly=True)
    description = fields.Text('Тайлбар', required=True)
    start_date = fields.Date('Эхлэх хугацаа',  required=True)
    end_date = fields.Date('Дуусах хугацаа', required=True)
    total_amount = fields.Float('Нийт дүн', required=True)
    active = fields.Boolean('Идэвхитэй', default=True)
    address_id = fields.Many2one('ref.address', 'Тоот', required=True)
    address_address = fields.Char("Тоот", related="address_id.address")
    apartment_code = fields.Char('Байрны код', related="address_id.apartment_id.code")
    org_id = fields.Many2one('ref.organization', 'Байгууллага', related="service_type_id.org_id")
    service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээ', required=True, domain="[('category', '=', 'service_timed_condition')]")
    # service_type_id = fields.Many2one('ref.service.type', 'Үйлгээний төрөл', domain=[('category', '=', 'service_timed_condition')])
    # noat = fields.Boolean('Идэвхитэй', default=True)
    name = fields.Char('Нэр', compute="_compute_name", store=True)

    @api.depends('start_date', 'address_id', 'service_type_id')
    def _compute_name(self):
        ids = self.ids
        query = f"""
            select service.id as id, concat(address.code, '/', concat(extract(year from service.start_date), '-', extract(month from service.start_date)), '/', rst.name) as name
            from service_timed_condition service
            inner join ref_service_type rst ON rst.id = service.service_type_id
            inner join ref_address address on address.id = service.address_id 
            where service.id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
        """
        self.env.cr.execute(query)
        name_datas = self.env.cr.dictfetchall()
        name_datas = groupby(name_datas, key=lambda x: x['id'])
        name_datas = {key: list(group) for key, group in name_datas}
        for obj in self:
            id = obj.id
            if name_datas.get(id):
                obj.name = name_datas.get(id)[0].get('name')
            else:
                obj.name = '-'


class ServiceDeductionGroup(models.Model):
    _name = 'service.deduction.group'
    _order = 'id desc'
    name = fields.Char('Нэр', compute="_compute_name", store=True)
    line_ids = fields.One2many('service.deduction', 'group_id', string="Хасагдах хэрэглээний мөр")
    year = fields.Selection(get_years(),string="Он",required=True)
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
    company_id = fields.Many2one('res.company', 'ХҮТ', default=lambda self: self.env.company.id, readonly=True)
    address_type = fields.Selection(ADDRESS_TYPE, 'Хандах төрөл', default=lambda self: self.env.user.access_type, readonly=True)
    state = fields.Selection([('draft', 'Ноорог'), ('processing', 'Бодолт хийж буй'),('confirmed', 'Баталсан'),], string="Төлөв", default='draft')
    @api.depends('year', 'month', 'address_type')
    def _compute_name(self):
        address_type_dict = dict(ADDRESS_TYPE)
        for obj in self:
            obj.name = f"{obj.year}-{obj.month} /{address_type_dict.get(obj.address_type)}/"

    def update_pay_receipt(self):
        for obj in self:
            query = f"""CALL update_deduction({self.env.uid}, {obj.id}, {obj.company_id.id}, '{obj.address_type}');"""
            self.env.cr.execute(query)
            query = f"""CALL update_pay_receipt({self.env.uid}, '{obj.year}', '{obj.month}', {obj.company_id.id}, '{obj.address_type}');"""
            self.env.cr.execute(query)
            obj.state = 'processing'
            pay_receipt = self.env['pay.receipt'].search([('year', '=', obj.year), ('month', '=', obj.month), ('address_type', '=', obj.address_type), ('company_id', '=', obj.company_id.id)])
            if(pay_receipt.state != 'draft'):
                raise UserError(f'{obj.year}-{obj.month} төлбөл зохихоо ноорог болгоно уу!')
            pay_receipt.clear_invoice_difference()



    def confirm(self):
        for obj in self:
            obj.state = 'confirmed'

    def draft(self):
        for obj in self:
            obj.state = 'draft'

    def copy(self):
        for obj in self:
            result = super(ServiceDeductionGroup, obj).copy()
            result.line_ids = [
                (0,0,{
                    'is_noat_change': line.is_noat_change,
                    'service_type_id': line.service_type_id.id,
                    'pricelist_id': line.pricelist_id.id,
                    'calc_type': line.calc_type,
                    'type': line.type,
                    'description': line.description,
                    'year': line.year,
                    'month': line.month,
                    'address_type': line.address_type,
                    'company_id': line.company_id.id,
                    'active': line.active,
                    'value': line.value,
                    'amount': line.amount,
                    'address_ids': [(6,0, [address.id for address in line.address_ids])]
                }) for line in obj.line_ids]
            return result

class ServiceDeduction(models.Model):
    _name = 'service.deduction'
    _description = 'Хасагдах хэрэглээ'
    _order = 'id desc'
    is_noat_change = fields.Boolean('НӨАТ тооцох', default=True)
    group_id = fields.Many2one('service.deduction.group', 'Group', index=True, required=True)
    service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээ', required=True)
    pricelist_id = fields.Many2one('ref.pricelist', 'Тариф', domain="[('service_type_id', '=', service_type_id)]", required=True)
    calc_type = fields.Selection([('days','Хоног'), ('amount', 'Мөнгөн дүн')], 'Бодох төрөл', required=True)
    type = fields.Selection([('-', '-'),('+', '+')], 'Төрөл', required=True)
    description = fields.Text(string='Тайлбар', required=True)
    address_ids = fields.Many2many('ref.address', string='Тоотууд', required=True)
    year = fields.Selection(get_years(),string="Он", compute="_compute_default_value", store=True)
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
    ], 'Сар', compute="_compute_default_value", store=True)
    address_type = fields.Selection(ADDRESS_TYPE, 'Хандах төрөл', compute="_compute_default_value", store=True, readonly=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', compute="_compute_default_value", store=True,readonly=True)
    active = fields.Boolean('Идэвхитэй', default=True)
    value = fields.Float('Утга')
    amount = fields.Float('Дүн')
    @api.depends('group_id')
    def _compute_default_value(self):
        for obj in self:
            obj.company_id = obj.group_id.company_id.id
            obj.year = obj.group_id.year
            obj.month = obj.group_id.month
            obj.address_type = obj.group_id.address_type
