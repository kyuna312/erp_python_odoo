from odoo import api, fields, models, _
from odoo.exceptions import UserError
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def create_user(self):
        for obj in self:
            if(not obj.work_email):
                raise UserError(_("Ажилтны мэйл хаягийг оруулна уу!"))
            if (not obj.company_id):
                raise UserError(_("Ажилтны харьяалагдах компаныг оруулна уу!"))
            if (obj.user_id):
                # raise UserError(_("Ажилтанд холбоотой хэрэглэгч аль хэдийн үүссэн байна"))
                return {
                    'name': _('Хэрэглэгч'),
                    'type': 'ir.actions.act_window',
                    'target': 'current',
                    'view_mode': 'form',
                    'res_model': 'res.users',
                    'view_id': self.env.ref('base.view_users_form').id,
                    'res_id': obj.user_id.id
                }
            user = self.env['res.users'].create({
                'name': obj.name,
                'login': obj.work_email,
                'email': obj.work_email,
                'company_id': obj.company_id.id,
                'company_ids': [(6, 0, [obj.company_id.id])]
                # 'groups_id': [(6, 0, [self.ref('hr_timesheet.group_timesheet_manager')])],
            })
            obj.write({
                'user_id': user.id
            })
            return {
                'name': _('Хэрэглэгч'),
                'type': 'ir.actions.act_window',
                'target': 'current',
                'view_mode': 'form',
                'res_model': 'res.users',
                'view_id': self.env.ref('base.view_users_form').id,
                'res_id': user.id
            }