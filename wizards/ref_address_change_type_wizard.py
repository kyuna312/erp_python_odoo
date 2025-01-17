from odoo import api, fields, models, _
from odoo.exceptions import UserError
from ..models.ref import ADDRESS_TYPE
class RefAddressChangeTypeWizard(models.TransientModel):
    _name = 'ref.address.change.type'
    address_type = fields.Selection(ADDRESS_TYPE, string='Тоотын төрөл', required=True)
    def change_address_type(self):
        model = self.env.context.get('active_model')
        if(model =='ref.address'):
            address_type = self.address_type
            if(address_type):
                ids = self.env.context.get('active_ids')
                if len(ids) > 10:
                    raise UserError('Нэг дор хамгийн ихдээ 10 тоотын төрлийг өөрчлөнө!.')
                address_type = self.address_type
                query = f"""
                    select counter_line.id line_id, cl_group.name as group_name from counter_counter_line counter_line
                    inner join counter_counter_line_group cl_group on cl_group.id = counter_line.group_id
                    where cl_group.state = 'draft' and counter_line.address_id in {tuple(ids) if len(ids) > 1 else f'({ids[0]})'}
                """
                self.env.cr.execute(query)
                delete_counter_line_datas = self.env.cr.dictfetchall()
                delete_counter_line_ids = [line.get('line_id') for line in delete_counter_line_datas]
                if delete_counter_line_ids:
                    self.env.cr.execute(f"""
                        DELETE FROM counter_counter_line WHERE id in {tuple(delete_counter_line_ids) if len(delete_counter_line_ids) > 1 else f'({delete_counter_line_ids[0]})'}
                    """)
                address_list = self.env['ref.address'].browse(ids)
                for address in address_list:
                    parent_address = self.env['ref.address'].sudo().search([('type', '=', self.address_type), ('id', '=', address.parent_id.id), ('active', '=', False)], order="id desc", limit=1)
                    new_address = None
                    if(parent_address):
                        new_address = parent_address
                        new_address.action_unarchive()
                    else:
                        child_address = self.env['ref.address'].sudo().search([('type', '=', self.address_type), ('parent_id', '=', address.id), ('active', '=', False)], order="id desc", limit=1)
                        if child_address:
                            new_address = child_address
                            new_address.action_unarchive()
                        else:
                            new_address = self.env['ref.address'].sudo().create({
                        'apartment_id': address.apartment_id.id,
                        'name': address.name,
                        'type': address_type,
                        'category_id': address.category_id.id,
                        'activity_type_id': address.activity_type_id.id,
                        'inspector_id': address.inspector_id.id,
                        'address': address.address,
                        'family': address.family,
                        'pure_water': address.pure_water,
                        'impure_water': address.impure_water,
                        'heating_water_fee': address.heating_water_fee,
                        'heating': address.heating,
                        'proof': address.proof,
                        'mineral_water': address.mineral_water,
                        'uzeli': address.uzeli,
                        'phone': address.phone,
                        'sms': address.sms,
                        'receivable_uid': address.receivable_uid.id,
                        'parent_id': address.id
                    })
                    self.env['counter.counter'].sudo().search([('address_id', '=', address.id)]).write({
                        'address_id': new_address.id
                    })
                    self.env['service.timed.condition'].sudo().search([('address_id', '=', address.id)]).write({
                        'address_id': new_address.id
                    })
                address_list.action_archive()
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Тоотын төрлийг амжилттай шилжүүллээ!',
                        'message': '',
                        'type': 'success',
                        'sticky': False,
                        'next': {
                            'type': 'ir.actions.act_window_close',
                        }
                    }
                }
