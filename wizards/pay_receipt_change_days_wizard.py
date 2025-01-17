from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests
from ..models.ref import ADDRESS_TYPE

PRICELIST_CODE = {
    'AAN': {
        'pure_water' : ('23',),
        'impure_water' : ('41',),
        'heating' : ('46','47','48','42',),
        'hot_water' : ('29',),
    },
    'OS':  {
        'pure_water' : ('18',),
        'impure_water' : ('36',),
        'heating' : ('42',), # 85 graj halaalt, 88 niitiin ezemshill
        'hot_water' : ('26','27'),
    },
}
class PayReceiptChangeDays(models.TransientModel):
    _name = "pay.receipt.change.days"
    receipt_id = fields.Many2one('pay.receipt', 'Төлбөрийн баримт')
    company_id = fields.Many2one('res.company', 'ХҮТ')
    address_type = fields.Selection(ADDRESS_TYPE, 'Төрөл')

    apartment_ids = fields.Many2many('ref.apartment', string='Байр', domain="[('company_id', '=', company_id)]")
    address_ids = fields.Many2many('ref.address', string='Тоот', domain="[('apartment_id', 'in', apartment_ids),('company_id', '=', company_id)]")

    # apartment_id = fields.Many2one('ref.apartment', string='Байр', domain="[('company_id', '=', company_id)]")
    # address_id = fields.Many2one('ref.address', 'Тоот', domain="[('apartment_id', '=', apartment_id)]")

    # line_ids = fields.Many2many('pay.receipt.address', string='Мөрүүд', domain="[('receipt_id', '=', receipt_id)]")
    days_of_pure_water = fields.Integer(string="Цэвэр ус", default=30)
    days_of_impure_water = fields.Integer(string="Бохир ус", default=30)
    days_of_heating = fields.Integer(string="Халаалт", default=30)
    days_of_hot_water = fields.Integer('Халуун ус',default=30)

    def change_days(self):

        for obj in self:
            domain = [('receipt_id', '=', obj.receipt_id.id)]
            if(obj.apartment_ids):
                domain += [('apartment_id', 'in', obj.apartment_ids.ids)]
            if(obj.address_ids):
                domain += [('address_id', 'in', obj.address_ids.ids)]
            # if(obj.pricelist_ids):
            receipt_address = self.env['pay.receipt.address'].search(domain)
            if len(receipt_address) == 0:
                raise UserError("Төлбөрийн баримтын мөр үүсээгүй байна")
            receipt_address = f"{tuple(receipt_address.ids)}" if len(receipt_address.ids) > 1 else f"({receipt_address.ids[0]})"
            pure_water_pricelist_ids = self.env['ref.pricelist'].search([ #('address_type', '=', obj.address_type),
                                                                         ('category', '=', 'has_no_counter'),
                                                                         ('code','in', PRICELIST_CODE.get(obj.address_type).get('pure_water'))]).ids
            if(pure_water_pricelist_ids):
                pure_water_pricelist_ids = f"{tuple(pure_water_pricelist_ids)}" if(len(pure_water_pricelist_ids)>1) else f"({pure_water_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                       UPDATE pay_receipt_address_line SET days={obj.days_of_pure_water}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                       WHERE receipt_address_id in {receipt_address} and pricelist_id in {pure_water_pricelist_ids} and is_date_change = True;
                   """)
            impure_water_pricelist_ids = self.env['ref.pricelist'].search([#('address_type', '=', obj.address_type),
                                                                           ('category', '=', 'has_no_counter'),
                                                                           ('code','in', PRICELIST_CODE.get(obj.address_type).get('impure_water'))]).ids

            if (impure_water_pricelist_ids):
                impure_water_pricelist_ids = f"{tuple(impure_water_pricelist_ids)}" if (
                            len(impure_water_pricelist_ids) > 1) else f"({impure_water_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                       UPDATE pay_receipt_address_line SET days={obj.days_of_impure_water}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                       WHERE receipt_address_id in {receipt_address} and pricelist_id in {impure_water_pricelist_ids} and is_date_change = True;
                   """)


            heating_pricelist_ids = self.env['ref.pricelist'].search([#('address_type', '=', obj.address_type),
                                                                      ('category', '=', 'has_no_counter'),
                                                                      ('code','in', PRICELIST_CODE.get(obj.address_type).get('heating'))]).ids
            if (heating_pricelist_ids):
                heating_pricelist_ids = f"{tuple(heating_pricelist_ids)}" if (
                        len(heating_pricelist_ids) > 1) else f"({heating_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                       UPDATE pay_receipt_address_line SET days={obj.days_of_heating}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                       WHERE receipt_address_id in {receipt_address} and pricelist_id in {heating_pricelist_ids} and is_date_change = True;
                   """)

            hot_water_pricelist_ids = self.env['ref.pricelist'].search([#('address_type', '=', obj.address_type),
                                                                        ('category', '=', 'has_no_counter'),
                                                                        ('code','in', PRICELIST_CODE.get(obj.address_type).get('hot_water'))]).ids
            if (hot_water_pricelist_ids):
                hot_water_pricelist_ids = f"{tuple(hot_water_pricelist_ids)}" if (
                        len(hot_water_pricelist_ids) > 1) else f"({hot_water_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                   UPDATE pay_receipt_address_line SET days={obj.days_of_hot_water}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                   WHERE receipt_address_id in {receipt_address} and pricelist_id in {hot_water_pricelist_ids} and is_date_change = True;
               """)
            self.env.cr.execute(
                f"""CALL change_days_address_line({self.env.uid}, '{obj.receipt_id.year}', '{obj.receipt_id.month}', {obj.receipt_id.company_id.id}, '{obj.receipt_id.address_type}');"""
            )
class PayReceiptGetBankJson(models.TransientModel):
    _name = 'pay.receipt.get.bank.json'