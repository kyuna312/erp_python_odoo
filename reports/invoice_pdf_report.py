from odoo import models, fields, api


class InvoicePdfReport(models.AbstractModel):
    _name = 'report.ub_kontor.template_invoice_pdf_report'
    _description = 'Payment Receipt PDF Report Template'

    def get_bank_data(self, bank_name) -> []:
        dict_account_list = []
        account_list = self.env['pay.bank.account'].search([('name', 'ilike', bank_name), ('type', '=', 'incoming')], order='id desc', limit=1)
        dict_account_list += [
            {
              'name': account.bank_id.name,
              'number': account.number
            } for account in account_list
        ]
        return dict_account_list

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['pay.receipt.address.invoice'].browse(docids)
        dict_account_list = []
        dict_account_list += self.get_bank_data('Голомт')
        dict_account_list += self.get_bank_data('Хаан')
        dict_account_list += self.get_bank_data('Төрийн')
        dict_account_list += self.get_bank_data('Капитрон')
        return {
            'model': 'pay.receipt.address.invoice',
            'docs': docs,
            'dict_account_list': dict_account_list
        }
