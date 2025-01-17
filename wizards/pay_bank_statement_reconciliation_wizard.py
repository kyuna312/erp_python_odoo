
from odoo import api, fields, models, _


class PayBankStatementReconciliationWizard(models.TransientModel):
    _name = 'pay.bank.statement.reconciliation.wizard'
    statement_id  = fields.Many2one('pay.bank.statement', 'Банкны хуулга')
