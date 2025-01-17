from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.exceptions import ValidationError, UserError
from ..models.ref import CENTRAL_HEATING_STATION_LINE_TYPES


class CentralHeatingStationAllocationWizard(models.TransientModel):
    _name = 'central.heating.station.allocation.wizard'
    _description = 'ЦТП хувиарлах'
    apartment_id = fields.Many2one('ref.apartment', 'Байр', required=True)
    address_ids = fields.Many2many('ref.address', string ='Тоот', domain="[('apartment_id', '=', apartment_id)]")
    type = fields.Selection(CENTRAL_HEATING_STATION_LINE_TYPES, string="Төрөл", required=True)
    station_id = fields.Many2one('ref.central.heating.station', 'ЦТП', required=True)
    def allocate(self):
        address_ids = []
        if not self.address_ids and self.apartment_id:
            address_ids = self.env['ref.address'].search([('active', '=', True), ('apartment_id', '=', self.apartment_id.id)]).ids
        if self.address_ids:
            address_ids = self.address_ids.ids
        station_id = self.station_id.id
        type = self.type
        self.env['ref.central.heating.station.line'].create([
            {
                'type': type,
                'address_id': address_id,
                'station_id': station_id,
            } for address_id in address_ids])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'ЦТП амжилттай хувиарлагдлаа',
                'message': f'',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                }
            }
        }
