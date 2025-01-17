import datetime

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError



class PaymentRegistrationWizard(models.TransientModel):
    _name = 'pay.payment.register'
    amount = fields.Float('Дүн', required=True)
    account_id = fields.Many2one('pay.bank.account', 'Данс', required=True, domain=[('type', '=', 'incoming')])
    payment_date = fields.Date('Огноо', required=True, default=fields.Date.today())
    communication = fields.Char('Nemo', required=True)
    address_id = fields.Many2one('ref.address', 'Тоот', required=True)
    invoice_ids = fields.Many2many('pay.receipt.address.invoice', 'Нэхэмжлэлүүд', store=False, domain="[('payment_state', '=', 'paid')]")
    payment_ref = fields.Text('Гүйлгээний утга', required=True)
    def create_payment(self):
        payment = self.env['pay.address.payment'].create({
            'account_id': self.account_id.id,
            'amount': self.amount,
            'address_id': self.address_id.id,
            'state': 'confirmed',
            'payment_ref': self.payment_ref,
            'ref': self.communication,
            'date': self.payment_date,
        })
        data = payment.prepare_line_by_invoice(invoice_ids=self.invoice_ids.ids)
        self.env['pay.address.payment.line'].create(data)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Төлөлт амжилттай хийгдлээ',
                'message': f'',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                }
            }
        }