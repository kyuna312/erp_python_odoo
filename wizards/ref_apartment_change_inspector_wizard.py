from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests
class RefApartmentChangeInspector(models.TransientModel):
    _name = 'ref.apartment.change.inspector.wizard'
    inspector_id = fields.Many2one('hr.employee', string='Байцаагч', domain=lambda self: [('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)])
    def change_inspector_id(self):
        model = self.env.context.get('active_model')
        if (model in ('ref.address')):
           ids = self.env.context.get('active_ids')
           if ids:
               self.env[model].search([('id', 'in', ids)]).write({'inspector_id': self.inspector_id.id})
               return True
           else:
               raise UserError(_("Идэвхтэй мөр олдсонгүй"))
        else:
            raise UserError(_("Зөвхөн Байр цэсээс байцаагч өөрчлөх боломжтой"))