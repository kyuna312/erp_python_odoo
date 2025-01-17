from odoo import api, fields, models, _
from .pay import PAY_RECEIPT_STATE
from datetime import datetime


def get_years():
  year_list = []
  curr_year = int(datetime.now().strftime('%Y'))
  for i in range(curr_year, 2019, -1):
    year_list.append((str(i), str(i)))
  return year_list


class PayReceiptAddressTemp(models.Model):
  _name = 'pay.receipt.address.temp'
  temp_id = fields.Integer('Temp ID')
  active = fields.Boolean('Идэвхтэй', default=True)
  # (address_id,receipt_id)
  address_id = fields.Many2one('ref.address', 'Тоот', required=True, index=False)
  address_address = fields.Char('Тоот', related="address_id.address")
  apartment_code = fields.Char('Байрны код', related="address_id.apartment_id.code")
  # horoo_id = fields.Many2one('ref.horoo', 'Хороо',  store=True,)
  horoo_id = fields.Integer('Хороо ID', index=True)
  # duureg_id = fields.Many2one('ref.duureg', 'Дүүрэг', store=True)
  duureg_id = fields.Integer('Дүүрэг', store=True, index=True)

  apartment_id = fields.Many2one('ref.apartment', 'Байр', compute="compute_apartment", index=False, store=True)
  amount = fields.Float('Үнийн дүн')
  noat = fields.Float('НӨАТ')

  total_amount = fields.Float('Нийт дүн')

  state = fields.Selection(PAY_RECEIPT_STATE, 'Төлөв', default='draft')
  receipt_id = fields.Many2one('pay.receipt', 'Төлбөрийн баримт', index=False)
  # mcode
  inspector_id = fields.Many2one('hr.employee', 'Байцаагч', index=True)
  line_ids = fields.One2many('pay.receipt.address.line', 'receipt_address_id', string='Төлбөрийн баримтын задаргаа')
  # invoice_id = fields.Many2one('account.move', 'Нэхэмжлэл')
  counter_qty = fields.Integer('Тоолуурын тоо/ширхэг')
  family = fields.Integer(string="Ам бүл")
  partner_id = fields.Many2one('res.partner', 'Partner', related="address_id.partner_id", store=False)
  address_code = fields.Char('Тоотын код', related="address_id.code")
  sms1_sent = fields.Boolean('Мессеж 1 илгээсэн', default=False)
  sms2_sent = fields.Boolean('Мессеж 2 илгээсэн', default=False)
  year = fields.Selection(get_years(), 'Он', store=True)
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
  ], 'Сар', store=True)

  def compute_apartment(self):
    for obj in self:
      obj.apartment_id = obj.address_id.apartment_id.id

  def action_get_bank_json(self):
    url = self.env["ir.config_parameter"].sudo().get_param("ub_kontor.kontor_web")
    for obj in self:
      # return {
      #     "type": "ir.actions.act_url",
      #     "target": "self",
      #     "url": f"{url}/bank/bl_single/{obj.apartment_id.code}/?token=kdisoe9e93eiiwow;;830woieafj24&pay_receipt={obj.receipt_id.id}",
      # }
      return {
        'name': _('Төрийн банкны файл татах'),
        'type': 'ir.actions.act_window',
        'view_mode': 'form',
        'target': 'new',
        'res_model': 'bank.statement.export.json',
        'context': {
          'default_receipt_id': obj.receipt_id.id,
          'default_method_id': f'ref.address,{obj.address_id.id}'
        }
      }

  # def post_invoice(self):
  #     for line in self:
  #         if line.state != 'invoice_created':
  #             raise UserError(_(f"{line.address_id.full_address} дээрх төлбөрийн баримт нэхэмжлэл үүссэн төлвөөс өөр төлөвт байна!"))
  #         if(line.invoice_id):
  #             line.invoice_id.action_post()
  #
  # def create_invoice(self):
  #     for line in self: ....

  def name_get(self):
    result = []
    for obj in self:
      name = f"{obj.address_id.name_get()[0][1]}"
      result.append((obj.id, name))
    return result

  @api.onchange('line_ids')
  def compute_amount(self):
    for obj in self:
      amount = 0
      noat = 0
      total_amount = 0
      for line in obj.line_ids:
        amount += line.amount or 0.0
        total_amount += line.total_amount or 0.0
        noat += line.noat or 0.0
      obj.amount = amount
      obj.noat = noat
      obj.total_amount = total_amount


class PayReceiptAddressLineTemp(models.Model):
  _name = 'pay.receipt.address.line.temp'
  temp_id = fields.Integer('Temp ID')
  active = fields.Boolean('Идэвхтэй', default=True)
  receipt_address_id = fields.Many2one('pay.receipt.address', 'Төлбөрийн баримт', required=False)
  # receipt_address_id = fields.Integer('Төлбөрийн баримт', index=True)
  address_id = fields.Many2one('ref.address', 'Тоот', index=False, required=True)
  address_address = fields.Char('Тоот', related="address_id.address")
  apartment_code = fields.Char('Байрны код', related="address_id.apartment_id.code")
  # apartment_id = fields.Many2one('ref.apartment', 'Байр', index=False, store=True)
  apartment_id = fields.Integer('Байр')
  # inspector_id = fields.Many2one('hr.employee', 'Ажилтан', index=False, store=True)
  inspector_id = fields.Integer('Байцаагч ID')
  service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээний төрөл')
  # service_deduction_group_id = fields.Many2one('service.deduction.group', 'Хасагдах хэрэглээ')
  service_deduction_group_id = fields.Integer('Хасагдах хэрэглээ')
  name = fields.Char("Нэр", required=False)
  # name = fields.Char("Нэр", required=True)
  amount = fields.Float('Дүн')
  pricelist_id = fields.Many2one('ref.pricelist', 'Тариф')
  pricelist_days = fields.Integer('Тариф хоног', compute="_compute_pricelist_days", store=True)
  started_amount = fields.Float('Анхны дүн')
  price = fields.Float('Үнэ')
  # uom_id = fields.Many2one('uom.uom', 'Хэмжих нэгж', compute="_compute_uom_id", store=True)
  uom_id = fields.Integer('Хэмжих нэгж')
  total_amount = fields.Float('Нийт дүн')
  days = fields.Integer('Хоног')
  days_changed = fields.Boolean('Хоног өөрчлөгдсөн эсэх', default=False)
  usage = fields.Float('Хэрэглээ')
  transition_coef = fields.Integer('Шилжих коэф')
  noat = fields.Float('НӨАТ')
  # company_id = fields.Many2one('res.company','ХҮТ', index=False, related="address_id.company_id", store=True)
  company_id = fields.Integer('ХҮТ ID')
  year = fields.Selection(get_years(), 'Он', store=True)
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
  ], 'Сар', store=True)

  # Төрийн банкны JSON файлд тоолуурын заалтуудыг бүртгэж харуулах хэрэгцээ гарсан тул төлбрийн баримтын задаргаа дээр тоолуурын заалтын тоон утгыг хадгалдаг болов
  now_counter = fields.Float(string="Эхний заалт", default=0, tracking=True, readonly=True)
  last_counter = fields.Float(string="Эцсийн заалт", default=0, tracking=True, readonly=True)
  difference_counter = fields.Float(string="Зөрүү заалт", default=0.0, tracking=True,
                                    readonly=True)
  fraction_counter = fields.Float(string="Задгай заалт", default=0.0, tracking=True, readonly=True)

  @api.depends('pricelist_id')
  def _compute_pricelist_days(self):
    for obj in self:
      obj.pricelist_days = obj.pricelist_id.days

  @api.onchange('amount')
  def compute_total_amount(self):
    for obj in self:
      obj.noat = obj.amount * 0.1
      obj.total_amount = obj.noat + obj.amount

  @api.depends('pricelist_id')
  def _compute_uom_id(self):
    for obj in self:
      obj.uom_id = obj.pricelist_id.uom_id.id

  def write(self, vals):
    if (vals.get('days')):
      vals['days_changed'] = True
    result = super(PayReceiptAddressLineTemp, self).write(vals)
    return result
