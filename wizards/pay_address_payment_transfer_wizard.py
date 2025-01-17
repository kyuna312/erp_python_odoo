from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayAddressPaymentTransferWizard(models.TransientModel):
    _name = 'pay.address.payment.transfer'

    address_id = fields.Many2one('ref.address', 'Тоот', required=True, sudo=True)
    payment_id = fields.Many2one('pay.address.payment', 'Төлбөр', required=True)
    payment_residual = fields.Float('Төлбөрийн үлдэгдэл', related='payment_id.residual_amount')
    amount = fields.Float('Төлөх дүн', required=True)

    def action_transfer_amount(self):
        return self.sudo().transfer_amount()


    def transfer_amount(self):
        if self.amount<= 0.0:
            raise UserError('0.0 дүнгээр шилжүүлэг хийх боломжгүй!')
        if self.payment_residual < self.amount:
            raise UserError('Шилжүүлэх дүн төлбөрийн үлдэгдлээс их байна!')
        created_payment = self.env['pay.address.payment'].sudo().create({
            'address_id': self.address_id.id,
            'amount': self.amount,
            'parent_id': self.payment_id.id,
            'payment_ref': self.payment_id.payment_ref,
            'ref': self.payment_id.ref,
            'date': self.payment_id.date,
            'statement_line_id': self.payment_id.statement_line_id.id,
            'account_id': self.payment_id.account_id.id
        })
        if created_payment:
            created_payment.register_invoices()
            # query = f"""
            #     UPDATE pay_address_payment SET amount={ self.payment_id.amount - self.amount}  WHERE id = {self.payment_id.id}
            # """
            # self.env.cr.execute(query)
            # self.payment_id.write({
            #     'amount': self.payment_id.amount - self.amount
            # })
            query = f"""
                            UPDATE pay_address_payment SET residual_amount={self.payment_id.residual_amount - self.amount}, amount={self.payment_id.amount - self.amount}  WHERE id = {self.payment_id.id}
                        """
            self.payment_id.amount -= self.amount

            self.env.cr.execute(query)
            self.payment_id.compute_residual_amount()
        if self.address_id.type == self.env.user.access_type:
            return {
                'name': _('Төлбөр'),
                'type': 'ir.actions.act_window',
                'target': 'new',
                'view_mode': 'form',
                'res_model': 'pay.address.payment',
                'res_id': created_payment.id
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Шилжүүлэг амжилттай хийгдлээ',
                'message': 'Үйлчилгээ амжилттай үүслээ.',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                }
            }
        }
