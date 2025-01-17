from passlib.utils.des import mdes_encrypt_int_block

from odoo import api, fields, models, _



class PayReceiptAddressInvoiceSearch(models.TransientModel):
    _name = 'pay.receipt.address.invoice.search'

    inspector_ids = fields.Many2many('hr.employee', string="Байцаагч",domain=lambda self: [('user_id', 'in', self.env.ref('ub_kontor.group_kontor_inspector').users.ids)])

    def search_invoice(self):
        current_receipt = self.env['pay.receipt'].search([], order="year desc,month desc", limit=1)
        invoice_list = self.env['pay.receipt.address.invoice'].search([('inspector_id', 'in', self.inspector_ids.ids), ('month', '=', current_receipt.month), ('year', '=', current_receipt.year)])
        return {
            'name': _('Нэхэмжлэл'),
            'type': 'ir.actions.act_window',
            'target': 'current',
            'view_mode': 'tree,form',
            'res_model': 'pay.receipt.address.invoice',
            'domain': [('id', 'in', invoice_list.ids)],
            'context': {
                # 'search_default_year_group': 1,
                # 'search_default_month_group': 1,
            }
        }
