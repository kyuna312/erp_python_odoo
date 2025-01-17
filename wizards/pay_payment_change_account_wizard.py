from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayAddressPaymentChangeAccount(models.TransientModel):
    _name = 'pay.payment.change.account'
    account_id = fields.Many2one('pay.bank.account', 'Данс', required=True)
    reconcile = fields.Char('Тулгалт хийгдэх эсэх', compute="_compute_reconcile_field")

    @api.depends('account_id')
    def _compute_reconcile_field(self):
        for obj in self:
            obj.reconcile = obj.account_id.match_reconcile
    def change(self):
        model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')
        if(model != 'pay.address.payment'):
            return False
        active_ids_str = str(tuple(active_ids)) if len(active_ids) > 1 else f"({active_ids[0]})"
        account_id = self.account_id.id
        query = f"""
            select * from pay_address_payment payment
            where payment.state != 'done' and payment.id in {active_ids_str}
        """
        self.env.cr.execute(query)
        payment_list = self.env.cr.dictfetchall()
        if not payment_list:
            raise UserError("Тулгагдсан төлбөрийн данс шилжүүлэх боломжгүй!")
        payment_ids = [payment.get('id') for payment in payment_list]
        result = [{
                'address_id': payment.get('address_id'),
                'account_id': account_id,
                'payment_ref': payment.get('payment_ref'),
                'ref': payment.get('ref'),
                'date': payment.get('date'),
                'amount': payment.get('residual_amount'),
                'statement_line_id': payment.get('statement_line_id'),
                'state': 'confirmed',
                'parent_id': payment.get('id')
            } for payment in payment_list]
        created_payment_list = self.env['pay.address.payment'].create(result)
        self.env.cr.execute(f"""
            update pay_address_payment 
            set amount = amount-residual_amount, residual_amount=0.0 where id in {tuple(payment_ids) if len(payment_ids) > 1 else f"({payment_ids[0]})"} """)
        self.env['pay.address.payment'].browse(payment_ids).compute_residual_amount()
        return {
            'name': _('Салгагдсан төлбөрүүд'),
            'type': 'ir.actions.act_window',
            'target': 'current',
            'view_mode': 'tree,form',
            'res_model': 'pay.address.payment',
            'domain': [('id', 'in', created_payment_list.ids)]
        }
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Төлбөрүүдийн дансыг амжилттай өөрчиллөө',
        #         'message': f"""Өөрчлөгдсөн төлбөрийн тоо:{len([])} \n
        #                        Өөрчлөгдөөгүй төлбөрийн тоо: {len([]) - len([])}""",
        #         'type': 'success',
        #         'sticky': False,
        #         'next': {
        #             'type': 'ir.actions.act_window_close',
        #         }
        #     }
        # }



