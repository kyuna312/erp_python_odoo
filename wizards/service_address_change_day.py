from odoo import api, fields, models, _

class ServiceAddressChangeDay(models.TransientModel):
    _name = 'service.address.change.day.wizard'

    day = fields.Integer('Өдөр')

    def change_days(self):
        print("days've changed")
        model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')
        if(model in ('service.address',)):
            self.env[model].browse(active_ids).write({
                'day': self.day
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Амжилттай!',
                    'message': 'Хоног өөрчлөгдлөө',
                    'sticky': False,
                    'type': 'success',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }