from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests

class PayRecieptSearchItemsWizard(models.TransientModel):
    _name = 'pay.receipt.search.items.wizard'
    # duureg_id = fields.Many2one('ref.duureg', 'Дүүрэг', tracking=True)
    # horoo_id = fields.Many2one('ref.horoo', 'Хороо', tracking=True)
    # inspector_ids = fields.Many2many('hr.employee', 'Байцаагч')
    # show_all = fields.Boolean('Бүгдийг харах')
    apartment_ids = fields.Many2many('ref.apartment', string='Байр', tracking=True)

    # @api.onchange('duureg_id')
    # def _onchange_duureg_id(self):
    #     if self.duureg_id:
    #         return {'domain': {'horoo_id': [('duureg_id', '=', self.duureg_id.id)]}}
    #     else:
    #         return {'domain': {'horoo_id': []}}
    #
    # @api.onchange('horoo_id')
    # def _onchange_horoo_id(self):
    #     if self.horoo_id:
    #         return {'domain': {'apartment_ids': [('horoo_id', '=', self.horoo_id.id)]}}
    #     else:
    #         return {'domain': {'horoo_id': []}}
    def search_items(self):
        context = self.env.context.get('base_context')
        local_domain=[]
        if(self.apartment_ids.ids):
            local_domain = [('apartment_id', 'in', self.apartment_ids.ids)]
        return {
            'type': 'ir.actions.act_window',
            'name': self.env.context.get('action_name'),
            'res_model': self.env.context.get('search_model'),
            'domain': self.env.context.get('search_domain')+local_domain,
            'view_mode': self.env.context.get('view_mode'),
            'target': 'current',
            'context': context,
        }