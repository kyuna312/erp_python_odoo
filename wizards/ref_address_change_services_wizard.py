from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests

class RefAddressChangeServicesWizard(models.Model):
    _name = 'ref.address.change.services.wizard'
    pure_water = fields.Boolean(string="Цэвэр ус", default=True, tracking=True)
    impure_water = fields.Boolean(string="Бохир ус", default=True, tracking=True)
    heating = fields.Boolean(string="Халаалт", default=True, tracking=True)
    proof = fields.Boolean(string="Баримт", default=True, tracking=True)
    heating_water_fee = fields.Boolean(string="УХХ", default=True, tracking=True)
    mineral_water = fields.Boolean(string='Ус рашаан ашигласны татвар', default=False, tracking=True)
    # def compute_address_domain(self):
    #     print("==========================")
    #     print(self.apartment_ids.ids)
    #     print("==========================")
    #     return [('apartment_id', 'in', self.apartment_ids.ids)] if self.apartment_ids else [()]
    # apartment_ids = fields.Many2many('ref.apartment', string='Байрнууд')
    # address_ids = fields.Many2many('ref.address', string='Тоотууд', domain=lambda self: self.compute_address_domain())


    def change_services(self):
        if(self.env.context.get('active_model') == 'ref.address' and self.env.context.get('active_ids')):
            self.env['ref.address'].search([('id', 'in', self.env.context.get('active_ids'))]).write({
                'pure_water': self.pure_water,
                'impure_water': self.impure_water,
                'heating': self.heating,
                'proof': self.proof,
                'heating_water_fee': self.heating_water_fee,
                'mineral_water': self.mineral_water,
            })
