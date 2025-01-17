from PIL.ImageChops import lighter

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests

from .pay import loggger
from .ref import ADDRESS_TYPE
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger('TOOLUUR:')
# Haluun us, huiten us
# class CounterType(models.Model):
#     _name = "counter.type"
#     _description = "Тоолуурын төрөл"
#
#     name = fields.Char("Төрөл", required=True)
#
#     active = fields.Boolean(string="Active", default=True, tracking=True)

COUNTER_TYPE = [
    ('hot_water', 'Халуун ус'),
    ('cold_water', 'Хүйтэн ус'),
]
# vann haluun us, gal togoo haluun us, butsah haluun us, dulaan
class CounterName(models.Model):
    # _name = "counter.name"
    _name = "counter.name"
    _description = "Тоолуурын нэр"

    name = fields.Char("Нэр", required=True)
    return_type = fields.Selection(
        [
            ("1", "Энгийн тоолуур"),
            ("2", "Буцах буцах тоолуур"),
        ],
        default="1",
        string="Буцах төрөл",
        tracking=True,
    )
    type = fields.Selection(COUNTER_TYPE, 'Төрөл')
    # type_id = fields.Many2one('counter.type', 'Төрөл')
    active = fields.Boolean(string="Active", default=True, tracking=True)


class CounterWarrant(models.Model):
    _name = "counter.warrant"
    _description = "Тоолуур баталгаа"

    name = fields.Char("Нэр", required=True)

    active = fields.Boolean(string="Active", default=True, tracking=True)

COUNTER_CATEGORY = [('counter', 'Усны тоолуур'), ('thermal_counter', 'Дулааны тоолуур')]

COUNTER_METHOD_TYPE = [
    ('1','Зөвхөн дулаан тооцох'),
    ('2', 'Зөвхөн халуун ус тооцох'),
    ('3', 'Дулаан тооцоогүй үед халуун ус тооцох'),
    ('4', 'Дулаан болон халуун ус бүх үед тооцох'),
]
class Counter(models.Model):
    _name = "counter.counter"
    _description = "Тоолуур"
    _rec_name = "number"
    _order = 'id desc'
    # angilal = fields.Selection(CounterType.ANGILAL, related="type_id.angilal")
    _sql_constraints = [
        ('code_company_uniq', 'unique (code,company_id)', 'Тоолуурын №, компанитай бичилт давхцаж байна'),
    ]
    address_id = fields.Many2one("ref.address", "Тоот", tracking=True, required=True, ondelete="cascade")
    apartment_id = fields.Many2one('ref.apartment', 'Байр', related="address_id.apartment_id", store=True)
    inspector_id = fields.Many2one('hr.employee', string='Байцаагч', related="address_id.inspector_id", readonly=True, store=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', related="address_id.company_id", store=True)

    address_code = fields.Char('Тоотын код', related="address_id.code")

    # ААН, ХУВЬ ХҮН
    address_type = fields.Selection(ADDRESS_TYPE,'Тоотын төрөл', related="address_id.type")

    address_owner = fields.Char('Тоот эзэмшигч', related='address_id.name')
    address_apartment = fields.Char('Байрны код', related='address_id.apartment_id.code')
    address_address = fields.Char('Тоот', related='address_id.address')


    name_id = fields.Many2one("counter.name", "Тоолуурын нэр", tracking=True, required=True)

    # type_id = fields.Many2one("counter.type", "Тоолуурын төрөл", tracking=True, related='name_id.type_id')
    type = fields.Selection(COUNTER_TYPE, 'Тоолуурын төрөл', tracking=True, related='name_id.type', required=True)
    number = fields.Char("Тоолуурын дугаар")

    code = fields.Char('Тоолуурын №')
    # vannii haluun us, vannnii huiten us, gal togoonii haluun us, ...
    # name = fields.Char("Тоолуурын нэр", required=True)

    uom_id = fields.Many2one('uom.uom', 'Хэмжих нэгж', required=True)
    diameter = fields.Integer(string="Диаметр", default=15, tracking=True)
    warrant_id = fields.Many2one("counter.warrant", "Баталгаажсан", tracking=True)
    # batalgaajsan hugatsaaa orj ireh uyd duusah hugatsaag ni ail 4, baiguullaga bl 2 jileer nemeh
    approved_date = fields.Date(string="Баталгаажсан огноо", required=True)
    end_date = fields.Date(string="Дуусах огноо", required=True, default=lambda self: fields.Date.today()+timedelta(days=2190))
    state = fields.Selection(
        [
            ("new", "Шинэ"),  # 1 sar yvaad hereglegch deer suurilsan bolno
            ("confirm", "Баталгаажсан"),  # ashiglahgui baigaa
            ("normal", "Хэрэглэгч дээр суурилсан"),  # zaaltaar
            ("broken", "Гэмтсэн"),  # zadgai
            ("done", "Баталгаа дууссан"),
        ],
        default="normal",
        string="Төлөв",
        tracking=True,
    )

    registered_date = fields.Date(string="Бүртгэсэн огноо", required=True)

    mark = fields.Char("Марк")
    seal1 = fields.Char("Лац 1")
    seal2 = fields.Char("Лац 2")
    certificate = fields.Char("Сертификатны №")

    active = fields.Boolean(string="Active", default=True, tracking=True)

    category = fields.Selection(COUNTER_CATEGORY, string='Ангилал', readonly=False, required=True)
    # Suuliin zaaltaas oorchlolt oruulah field dutuu bga now_count, last_count ... count
    usage_div_ids = fields.One2many('counter.counter.usage.division', 'counter_id', 'Тариф хуваах')
    sharing_ids = fields.One2many('counter.counter.sharing', 'counter_id', 'Хуваагдах хэрэглээ')

    percent = fields.Float('Ш.Коэф', default=100.0)
    sha_coef = fields.Float('ША.Коэф', default=0.0)
    # sharing_ids =

    address_code_temp = fields.Char('Хэрэглэгчийн код (tmp)')
    method_type = fields.Selection(COUNTER_METHOD_TYPE, 'Бодогдох төрөл')

    description  = fields.Text('Тайлбар')
    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        domain = []
        if (operator == '='):
            domain = [('code', operator, name)]
        records = self.search(domain + args, limit=limit)
        return records.name_get()


    def unlink(self):
        for obj in self:
            for usage in obj.usage_div_ids:
                usage.unlink()
        return super(Counter, self).unlink()
    
    @api.onchange('category', 'address_type', 'name_id')
    def on_change_category(self):
        if self.category and self.address_type and self.name_id:
            self.update_usage_div_ids()

    @api.model
    def create(self, vals):
        if not vals.get('number') and not vals.get('code'):
            vals['code'] = self.env['ir.sequence'].next_by_code('counter.counter.code')
            _logger.warning("========================================================")
            _logger.warning(vals['code'])
            _logger.warning("========================================================")
        record = super(Counter, self).create(vals)
        if 'name_id' in vals and 'usage_div_ids' not in vals:
            record.update_usage_div_ids()
        return record

    def update_usage_div_ids(self):
        for counter in self:
            counter.usage_div_ids = [(5, 0, 0)]

            pricelist_ids = counter.get_pricelist_ids()

            new_usage_divs = []
            for pricelist_id in pricelist_ids:
                pricelist = counter.env['ref.pricelist'].browse(pricelist_id)
                if pricelist.exists():
                    new_usage_divs.append((0, 0, {
                        'pricelist_id': pricelist_id,
                        'counter_id': counter.id,
                        'service_type_id': pricelist.service_type_id.id,
                    }))
            
            # Update usage_div_ids with new records
            counter.usage_div_ids = new_usage_divs

    def get_pricelist_ids(self):
        category = self.category
        address_type = self.address_type
        type = self.type

        pricelist_ids = []
        if category == 'counter':
            if type == 'hot_water':
                if address_type == 'OS':
                    pricelist_ids = [276, 167, 229]
                elif address_type == 'AAN':
                    pricelist_ids = [285, 169, 236]
            elif type == 'cold_water':
                if address_type == 'OS':
                    pricelist_ids = [276, 167]
                elif address_type == 'AAN':
                    pricelist_ids = [285, 169]
        elif category == 'thermal_counter':
            if address_type == 'OS':
                pricelist_ids = [252]
            elif address_type == 'AAN':
                pricelist_ids = [254]
        
        return pricelist_ids
        # counter.counter.usage.division

    def action_archive(self):
        result = super(Counter, self).action_archive()
        ids = self.ids
        self.env.cr.execute(f"""
            select ccl.id counter_line_id, cclg.name as group_name from counter_counter_line ccl 
            inner join counter_counter_line_group cclg ON cclg.id = ccl.group_id
            where cclg.state = 'draft' and ccl.counter_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
        """)
        datas = self.env.cr.dictfetchall()
        delete_ids = []
        groups_name = []
        for data in datas:
            delete_ids += [data.get('counter_line_id')]
            groups_name += [data.get('group_name')]
        if delete_ids:
            self.env.cr.execute(f"""DELETE FROM counter_counter_line where id in {tuple(delete_ids) if len(delete_ids) > 1 else f"({delete_ids[0]})" }""")
            groups_name_str = str(groups_name)
            groups_name_str = groups_name_str.replace('[','')
            groups_name_str = groups_name_str.replace(']','')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Харгалзах тоолуурын заалтыг устгалаа',
                    'message': f'Тоолуурын заалтыг групп-үүд:{groups_name_str}',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Архивлах үйлдэл амжилттай хийгдлээ',
                    'message': f'',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }
class CounterSharing(models.Model):
    _name = "counter.counter.sharing"
    _description = "Хуваагдах хэрэглээ"

    counter_id = fields.Many2one(
        "counter.counter", "Тоолуур", tracking=True,  ondelete="cascade"
    )  # undsen tootiin tooluur

    counter_address_id = fields.Many2one('ref.address', 'Тоолуурын тоот', related="counter_id.address_id", store=True)
    counter_address_apartment_code = fields.Char('Тоолуурын байр', related="counter_address_id.apartment_id.code", store=True)
    counter_address_code = fields.Char('Тоолуурын хэрэглэгчийн код', related="counter_address_id.code", store=True)
    counter_address_address = fields.Char( 'Тоолуурын тоот', related="counter_address_id.address", store=True)
    counter_address_owner = fields.Char('Тоолуур эзэмшигчийн нэр', related="counter_address_id.name", store=True)

    counter_name_id = fields.Many2one('counter.name', string='Тоолуурын нэр', related="counter_id.name_id", store=True)
    counter_code = fields.Char('Тоолуурын №', related="counter_id.code", store=True)

    address_id = fields.Many2one("ref.address", "Тоот", tracking=True, required=True)  # huvaaltsah toot
    address_code = fields.Char('Тоотын код', related="address_id.code")
    address_address = fields.Char('Тоот', related="address_id.address")
    apartment_code = fields.Char('Байрны код', related="address_id.apartment_id.code")
    apartment_id = fields.Many2one('ref.apartment', 'Байр', related="address_id.apartment_id")
    # type_id = fields.Many2one("counter.type", "Тоолуурын төрөл", tracking=True)
    percent = fields.Float(string="Хувь", default=0, tracking=True)



COUNTER_LINE_STATE = [('draft', 'Ноорог'), ('closed', 'Хаагдсан'), ('confirmed', 'Баталгаажсан'), ('done', 'Дууссан')]
def get_years():
    year_list = []
    curr_year = int(datetime.now().strftime('%Y'))
    for i in range(curr_year, 2019, -1):
        year_list.append((str(i), str(i)))
    return year_list
class CounterLineGroup(models.Model):
    _name = 'counter.counter.line.group'
    _description = 'Тоолуурын заалтын групп'
    _sql_constraints = [
        ('date_uniq', 'unique (year, month, company_id, address_type)', 'Тоолуурын заалтын групп үүсчихсэн байна!'),
    ]
    # inspector_id = fields.Many2one('res.users', 'Байцаагч', required=True)
    year = fields.Selection(get_years(),'Жил', required=True)
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
    ],'Сар', required=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True, default=lambda self: self.env.company.id)
    state = fields.Selection(COUNTER_LINE_STATE, 'Төлөв', default='draft', required=True)
    name = fields.Char('Нэр', compute="_compute_name", store=True)
    close_date = fields.Datetime('Хаах хугацаа')
    created_lines = fields.Boolean('Мөр үүссэн', compute="_compute_created_lines", )
    line_ids = fields.One2many('counter.counter.line', 'group_id', string='Мөр')
    address_type = fields.Selection(ADDRESS_TYPE, string="Тоотын төрөл", default=lambda self: self.env.user.access_type)
    def _compute_created_lines(self):
        for obj in self:
            obj.created_lines = True if obj.line_ids else False
    @api.depends('company_id','year','month')
    def _compute_name(self):
        for obj in self:
            obj.name = f"{obj.company_id.name} - {obj.year} - {obj.month}"
    def create_details(self):
        for obj in self:
            query = f"""
                CALL create_counter_line('{obj.year}', '{obj.month}', {obj.env.uid}, {obj.id}, {obj.company_id.id});
            """
            self.env.cr.execute(query)
            return {
                'name': _('Тоолуурын заалт'),
                'type': 'ir.actions.act_window',
                'view_mode': 'tree',
                'res_model': 'counter.counter.line',
                'domain': [('group_id', '=', obj.id)]
            }
    def show_details(self):
        for obj in self:
            return {
                'name': _('Тоолуурын заалт'),
                'type': 'ir.actions.act_window',
                'view_mode': 'tree',
                'res_model': 'counter.counter.line',
                'domain': [('group_id', '=', obj.id)],
                'context': {'search_default_category_group': 1}
            }
    def update_details_by_xls(self):
        for obj in self:
            return {
                'name': _('Тоолуурын заалт засварлах'),
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'target': 'new',
                'res_model': 'counter.line.xls.reader',
                'view_id':  self.env.ref('ub_kontor.counter_line_xls_reader_form').id,
                'context': {
                    'default_group_id': obj.id
                }
            }

    def write(self, vals):
        res = super(CounterLineGroup, self).write(vals)
        if('year' in vals or 'month' in vals  or 'company_id' in vals):
            for obj in self:
                self.env.cr.execute(f'DELETE FROM counter_counter_line WHERE group_id = {obj.id};')
        return res
    def close(self):
        for obj in self:
            obj.state = 'closed'
    def confirm(self):
        for obj in self:
            obj.state = 'confirmed'

    def done(self):
        for obj in self:
            obj.state = 'done'
    def draft(self):
        for obj in self:
            obj.state = 'draft'
class CounterLine(models.Model):
    _name = "counter.counter.line"
    _description = "Тоолуурын заалт"
    _order = 'apartment_code,float_address,counter_name asc'

    counter_id = fields.Many2one("counter.counter", "Тоолуур", tracking=True, readonly=True)
    counter_primary_key = fields.Integer('ID', related="counter_id.id")

    now_counter = fields.Float(string="Эхний заалт", default=0, tracking=True)
    last_counter = fields.Float(string="Эцсийн заалт", default=0, tracking=True)
    difference = fields.Float(string="Зөрүү", default=0.0, tracking=True, compute="_compute_difference", store=True, readonly=False)
    fraction = fields.Float(string="Задгай", default=0.0, tracking=True)  # int or float


    address_id = fields.Many2one('ref.address', 'Тоот', readonly=True)
    address_type = fields.Selection(ADDRESS_TYPE, 'Эзэмшигчийн төрөл', readonly=True)
    address_code = fields.Char('Хэрэглэгчийн код', readonly=False)


    inspector_id = fields.Many2one('hr.employee', 'Байцаагч', readonly=True)
    # counter_type_id = fields.Many2one('counter.type', 'Тоолуурын төрөл', readonly=True)
    counter_type = fields.Selection(COUNTER_TYPE, 'Тоолуурын төрөл', readonly=True)
    counter_number = fields.Char('Тоолуурын дугаар', readonly=True)
    counter_code = fields.Char('Тоолуурын №', related="counter_id.code")
    counter_category = fields.Selection(COUNTER_CATEGORY, string='Тоолуурын ангилал', readonly=True)

    group_id = fields.Many2one('counter.counter.line.group', 'Групп', required=True, ondelete="cascade", index=True)

    state = fields.Selection([('draft', 'Ноорог'), ('sent', 'Илгээсэн')], string='Төлөв', default='draft')
    year = fields.Selection(get_years(),string="Он", readonly=True)

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
    ],string="Сар", readonly=True, store=True)
    company_id = fields.Many2one('res.company', 'Компани', readonly=True)

    address_owner = fields.Char( 'Эзэмшигч', related="address_id.name")
    apartment_id = fields.Many2one("ref.apartment", "Байр")
    counter_name_id = fields.Many2one("counter.name", "Тоолуурын нэр")
    counter_name = fields.Char('Тоотын нэр')
    apartment_code = fields.Char(string='Байрны код')
    address_address = fields.Char('Тоот')
    float_address = fields.Float('Float address')

    @api.depends('now_counter', 'last_counter')
    def _compute_difference(self):
        for obj in self:
            obj.difference = obj.last_counter - obj.now_counter

    @api.model
    def create_procedure(self):
        """"""
        self.env.cr.execute("""DROP PROCEDURE if EXISTS create_counter_line;""")
        procedure = """
            CREATE OR REPLACE PROCEDURE create_counter_line(line_year char, line_month char, userid integer, groupid integer, companyid integer)
            LANGUAGE plpgsql
            AS $$
            DECLARE
                rec record;
            BEGIN
                FOR rec IN (
                    SELECT cc.id as counter_id, COALESCE(last_counter_line_data.last_counter, 0) as last_counter,
                        ra.id as address_id, ra.type as address_type, ra.code as address_code, cn.type as counter_type,
                        cc.number as counter_number, cc.category as counter_category, ra.inspector_id as inspector_id,  cn.id as counter_name_id, 
                        apartment.code as apartment_code, ra.company_id as company_id, ra.address as address_address, apartment.id as apartment_id, CAST(REGEXP_REPLACE(ra.address , '[^0-9\.]', '', 'g') AS FLOAT) as float_address,
                        cn.name as counter_name
                    FROM counter_counter cc
                    INNER JOIN ref_address ra ON ra.id = cc.address_id and ra.company_id = companyid and ra.type in (select address_type from counter_counter_line_group where id = groupid)
                    inner join ref_apartment apartment on apartment.id = ra.apartment_id
                    INNER JOIN counter_name cn ON cn.id = cc.name_id
                    left join (
                            select cc3.id as counter_id, count(ccl2.id) as line_count from counter_counter cc3 
                            inner join counter_counter_line ccl2 on ccl2.counter_id = cc3.id
                            inner join counter_counter_line_group cclg on cclg.id = ccl2.group_id and cclg.id = groupid
                            group by cc3.id
                    ) cl_count on cl_count.counter_id = cc.id 
                    left JOIN
                    (
                        select max(ccl.id) as last_counter_line, cc2.id as counter_id  FROM 
                        counter_counter cc2 
                        inner join ref_address ra2 on ra2.id = cc2.address_id and ra2.company_id = companyid
                        left join counter_counter_line ccl on ccl.counter_id = cc2.id
                        group by cc2.id
                    ) last_counter_line on last_counter_line.counter_id = cc.id
                    left join counter_counter_line last_counter_line_data on last_counter_line_data.id = last_counter_line.last_counter_line
                    WHERE ra.active=True and cc.active=True and ra.company_id = companyid and COALESCE(cl_count.line_count, 0) = 0 and cc.state != 'broken'
                ) LOOP
                    INSERT INTO counter_counter_line(counter_id, year, month, now_counter, last_counter, difference, fraction,
                                                     address_id, address_type, address_code, counter_type, counter_number, counter_category,
                                                     write_uid, create_uid, create_date, state, inspector_id, group_id, counter_name_id, 
                                                     apartment_code, company_id,address_address, apartment_id, float_address,counter_name)
                    VALUES(rec.counter_id, line_year, line_month, rec.last_counter, rec.last_counter, 0.0, 0.0,
                           rec.address_id, rec.address_type, rec.address_code, rec.counter_type, rec.counter_number, rec.counter_category,
                           userid, userid, now() , 'draft', rec.inspector_id, groupid, rec.counter_name_id, rec.apartment_code, 
                           rec.company_id,rec.address_address, rec.apartment_id, rec.float_address,rec.counter_name
                    );
                END LOOP;
            EXCEPTION
                WHEN OTHERS THEN
                    RAISE NOTICE 'Transaction rolled back due to an exception: %', SQLERRM;
            END;
            $$;
        """
        self.env.cr.execute(procedure)


class CounterUsageDivision(models.Model):
    _name = "counter.counter.usage.division"
    _description = "Тариф хуваах"
    _order = 'id desc'
    counter_id = fields.Many2one("counter.counter", "Тоолуур", tracking=True, required=True)
    counter_category = fields.Selection(COUNTER_CATEGORY, 'Тоолуурын ангилал', related="counter_id.category")
    # precent = fields.Float('Хувь', default=100.0, required=True)
    percent = fields.Float('Хувь', default=100.0, required=True)


    # tsever, bohir, uhh
    pricelist_type_id = fields.Many2one("ref.pricelist.type", "Төрөл", tracking=True, related="pricelist_id.type_id")

    pricelist_id = fields.Many2one("ref.pricelist", "Тариф", tracking=True, domain="[('type_id', '=', pricelist_type_id),('category', 'not in', ('user_service',))]", required=True)

    service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээ', required=True)
    #  domain="[('category', '=', counter_id.category)]"