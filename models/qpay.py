from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests, json
import  logging
from .ref import ADDRESS_TYPE
from itertools import groupby
# class AccountMove(models.Model):
#     _inherit = 'account.move'
#
#     dotood_code = fields.Char('Дотоод код')

# class InvoiceMove(models.AbstractModel):
#     _name = "account.move.qpay.invoice.rel"
#
#     qpay_invoice_id = fields.Many2one('qpay.invoice', ondelete="cascade")
#     account_move_id = fields.Many2one('account.Move', ondelete="cascade")
logger = logging.getLogger('QPAY:')
class QpayInvoice(models.Model):
    _name = "qpay.invoice"
    _description = "Qpay нэхэмжлэх"
    _rec_name = "invoice_number"

    invoice_number = fields.Char("Дотоод нэхэмжлэх дугаар", required=True)

    user_id = fields.Many2one("res.partner", "Хэрэглэгч", tracking=True, readonly=True)
    reference = fields.Char("Гэрээ дугаар", index=True, required=True)
    qpay_invoice = fields.Char("Qpay нэхэмжлэх", required=True)
    amount = fields.Float("Үнийн дүн", required=True)
    is_paid = fields.Boolean(string="Төлөгдсөн эсэх", default=False)

    # invoice_ids = fields.Many2many("account.move", "account_move_qpay_invoice_rel", 'qpay_invoice_id', 'account_move_id',string="Нэхэмжлэхүүд", )
    invoice_ids = fields.Many2many('pay.receipt.address.invoice', string='Нэхэмжлэлүүд')
    # payment_id is unnecessary
    payment_id = fields.Many2one('account.payment', 'Төлбөр')
    paid_user_type = fields.Selection(ADDRESS_TYPE, string='Төлсөн хэрэглэгчийн төрөл', required=True)
    paid_user_register = fields.Char(string="Регистер")
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True)

    auth_user_id = fields.Integer(string='Django user')
    registered = fields.Boolean('Төлбөрт бүртгэсэн эсэх', default=False)
    @api.model
    def initial(self):
        try:
            self.env.cr.execute(
                """
                    ALTER TABLE pay_receipt_address_invoice_qpay_invoice_rel ADD COLUMN IF NOT EXISTS id SERIAL;
                    ALTER TABLE pay_bank_account_qpay_configuration_rel ADD COLUMN IF NOT EXISTS id SERIAL;
                """
            )
        except Exception as ex:
            logger.warning(str(ex))

    def enter_paid_status_cron(self):
        company_ids = self.env['res.company'].sudo().search([]).ids
        for company_id in company_ids:
            qpay_account = f"""
                select account.id as account_id from pay_bank_account account where company_id = {company_id} and short_code='(QPAY)' and type='incoming'
            """
            self.env.cr.execute(qpay_account)
            qpay_account = self.env.cr.dictfetchall()
            qpay_account_id = None
            if(qpay_account):
                qpay_account_id = qpay_account[0].get('account_id')
            else:
                continue
            qpay_invoice_list = self.search([('company_id', '=', company_id), ('registered', '=', False), ('is_paid', '=', True)])
            for qpay_invoice in qpay_invoice_list:
                amount = qpay_invoice.amount
                invoice_ids = qpay_invoice.invoice_ids.ids
                if not invoice_ids:
                    continue
                query = f"""
                    SELECT invoice.address_id as address_id from pay_receipt_address_invoice invoice where id in {tuple(invoice_ids) if len(invoice_ids)>1 else f"({invoice_ids[0]})"}
                """
                self.env.cr.execute(query)
                address_ids = self.env.cr.dictfetchall()
                address_ids = [data.get('address_id') for data in address_ids]
                address_ids = list(set(address_ids))
                if len(address_ids) == 1:
                    payment = self.env['pay.address.payment'].sudo().create({
                        'account_id': qpay_account_id,
                        'amount': amount,
                        'address_id': address_ids[0],
                        'state': 'confirmed',
                        'payment_ref': qpay_invoice.reference,
                        'ref': qpay_invoice.reference,
                        'date': datetime.now().date(),
                    })
                    data = payment.prepare_line_by_invoice(invoice_ids=invoice_ids)
                    self.env['pay.address.payment.line'].sudo().create(data)
                    qpay_invoice.write({
                        'registered':True
                    })
                else:
                    continue


    # def action_checkqpay(self):
    #     print("check qpay")
    #     ICPSudo = self.env["ir.config_parameter"].sudo()
    #
    #     domain = ICPSudo.get_param("suh_erp.domain")
    #     url = (
    #         "http://main.toozaa.mn:8080/pay/checkPayment/"
    #         + self.qpay_invoice
    #         + "/"
    #         + domain
    #         + "/mn/"
    #     )
    #     resJson = requests.get(url)
    #     resStr = str(resJson.content, "UTF-8")
    #     try:
    #         clientObj = json.loads(resStr)
    #     except:
    #         raise UserError(_("Холболтын алдаа" + resStr))
    #
    #     if clientObj["status"]:
    #         raise ValidationError(_("Төлбөр төлөгдсөн байна"))
    #     else:
    #         raise UserError(_("Төлөгдөөгүй байна"))
    #
    # def set_invoice_ids(self, ids):
    #     # invs = self.env['account.move'].browse(ids)
    #     for id in ids:
    #         self.invoice_ids = [(4, id)]
    #     return "ok"



class QpayBank(models.Model):
    _name = "qpay.bank"
    _description = "Qpay банк"
    _rec_name = "mon"

    code = fields.Char("Код", required=True)
    eng = fields.Char("Англи", required=True)
    mon = fields.Char("Монгол", required=True)

class Kontor(models.Model):
    _name = "qpay.configuration"
    name = fields.Char('Нэр')
    register = fields.Char('Байгууллага Регистр	')
    phone = fields.Char('Утас')
    email = fields.Char('Имэйл')
    company_id = fields.Many2one('res.company', 'ХҮТ')
    lat = fields.Char('Өргөрөг')
    lng = fields.Char('Уртраг')
    mcc_code = fields.Char('MCC код', default='5311')
    city = fields.Selection([('11000', 'Улаанбаатар')], string='Хот', default='11000')
    district = fields.Selection([('12000', 'Багануур'), ('12300', 'Багахангай'),
       ('12600', 'Налайх дүүрэг'), ('13000', 'Баянзүрх дүүрэг'),
       ('14000', 'Сүхбаатар дүүрэг'), ('15000', 'Чингэлтэй дүүрэг'),
       ('16000', 'Баянгол дүүрэг'), ('17000', 'Хан-Уул'),
       ('18000', 'Сонгинохайрхан дүүрэг')], string='Дүүрэг (QPay)'
    )
    address = fields.Char('Тоот')
    owner_surname = fields.Char('Овог')
    owner_name = fields.Char('Нэр')
    owner_register = fields.Char('Регистр')
    # bank_id = fields.Many2one('res.bank', 'Банк')
    # name_bank = fields.Char('Дансны нэр')
    # account_bank = fields.Char('Дансны дугаар')
    qpay_terminal = fields.Char('Qpay терминал ID')
    qpay_token_expire = fields.Datetime('Qpay token expire')
    merchant_id = fields.Char('Merchant ID')
    qpay_token = fields.Char(string="Qpay token", readonly=True)
    active = fields.Boolean(default=True)
    # journal_ids = fields.Many2many('account.journal', string='Журналууд', domain="[('type', '=','bank'), ('company_id', '=', company_id)]")
    account_ids = fields.Many2many('pay.bank.account', string='Данснууд', domain="[('company_id', '=', company_id)]")


    def action_createMerchant(self):
        ICPSudo = self.env["ir.config_parameter"].sudo()
        token = ICPSudo.get_param("kontor.token") # xml !
        url = ICPSudo.get_param("ub_kontor.kontor_web") # xml !
        # domain = ICPSudo.get_param('suh_erp.domain')

        # print("domain: ", self.domain)
        # print("token: ", token)

        curl = url + "/qpay/createMerchant/" + str(self.company_id.id) + "?token=" + token

        # print(curl)
        x = requests.get(curl)
        if x.text == "ok":
            raise UserError(_("Амжилттай"))
        else:
            raise UserError(_("Амжилтгүй: " + x.text))