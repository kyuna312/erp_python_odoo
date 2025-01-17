from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests

class PayReceiptWizard(models.TransientModel):
    _name = 'pay.receipt.wizard'
    pay_receipt_id = fields.Many2one('pay.receipt', 'Төлбөрийн баримт', readonly=True, required=True)
    method = fields.Selection([('inspector', 'Байцаагч'),('apartment', 'Байр')], string='Байр/Байцаагч',required=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', related="pay_receipt_id.company_id",required=True)
    inspector_id = fields.Many2one('hr.employee', 'Байцаагч', domain=lambda self: [('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)])
    apartment_ids = fields.Many2many('ref.apartment', string='Байр',domain="[('company_id', '=', company_id)]")


    def create_pay_recipt_line(self):
        apartment_ids = []
        if(self.method == 'inspector'):
            # apartment_list = self.env['ref.apartment'].search([('inspector_id', '=', self.inspector_id.id), ('company_id', '=', self.pay_receipt_id.company_id.id)])

            self.env.cr.execute(f"""
                select apartment.id as apartment_id from ref_address ra 
                inner join ref_apartment apartment on apartment.id = ra.apartment_id
                where ra.inspector_id = {self.inspector_id.id} and ra.company_id = {self.pay_receipt_id.company_id.id} and ra.type = '{self.pay_receipt_id.address_type}'
                group by apartment.id
            """)
            apartment_ids = self.env.cr.dictfetchall()
            apartment_ids = [r.get('apartment_id') for r in apartment_ids]
        elif(self.method == 'apartment'):
            apartment_ids = self.apartment_ids.ids
        # userid integer, line_year character, line_month character, company_id integer, ttype character
        # Баримтын нэхэмжлэх үүсгэх
        if apartment_ids:
            self.env.cr.execute(f"""
                CALL create_pay_receipt_apartment({self.env.uid}, '{self.pay_receipt_id.year}', '{self.pay_receipt_id.month}', ARRAY{apartment_ids}, {self.pay_receipt_id.company_id.id}, '{self.pay_receipt_id.address_type}');
                CALL update_pay_receipt({self.env.uid}, '{self.pay_receipt_id.year}', '{self.pay_receipt_id.month}', {self.pay_receipt_id.company_id.id}, '{self.pay_receipt_id.address_type}');
            """)
            self.pay_receipt_id.clear_invoice_difference()
        else:
            raise UserError('Уучлаарай!\n Таны байцаагчид харгалзах байр олдсонгүй')
        # apartment_ids

    # def unlink(self):
    #     return