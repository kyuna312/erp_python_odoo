from odoo import api, fields, models, _
import json
import base64
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
class AccountBankStatementImport(models.TransientModel):
    _inherit = "account.bank.statement.import"

    statement_bank = fields.Selection(
        [
            ('statebank_json', 'Төрийн банк (JSON)'),
            ("statebank", "Төрийн банк"),
            ("khanbank", "Хаан банк"),
            # ('other', 'Бусад банк'),
        ],
        default="statebank_json",
        string="Аль банкы хуулга",
        required=True,
    )
    company_id = fields.Many2one('res.company', 'ХҮТ', required=True,  default=lambda self: self.env.company.id)

    def get_partner_by_code(self, code):
        address = self.env['ref.address'].search([('code', '=', code), ('active', '=', True)], order="id desc", limit=1)
        return address.partner_id.id if address else None
    def import_file(self):
        if(self.statement_bank == 'statebank_json'):
            for data_file in self.attachment_ids:
                file_name = data_file.name.lower()
                if (
                    file_name.strip().endswith(".json")
                ):
                    json_data_list = json.loads(base64.b64decode(data_file.datas))
                    statement_vals = {
                        "name": "Statement Of " + str(datetime.today().date()),
                        "journal_id": self.env.context.get("active_id"),
                        "company_id": self.company_id.id,
                        "line_ids": [(0,0,
                            {
                                "date": datetime.strptime(data.get('TDATE'),'%Y/%m/%d %H:%M:%S').date(),
                                "payment_ref": data.get('TRDESCR'),
                                "ref": f"{data.get('FACT')}/{data.get('BANKCODE')}",
                                "partner_id": self.get_partner_by_code(data.get('CCODE')),
                                "amount": float(data.get('INCOME')),
                                "currency_id": self.get_currency('MNT'),
                                # "narration": line[6],
                            }
                        ) for data in json_data_list],
                    }
                    statement = self.env['account.bank.statement'].create(statement_vals)

                    return {
                        "type": "ir.actions.act_window",
                        "res_model": "account.bank.statement",
                        "view_mode": "form",
                        "res_id": statement.id,
                        "views": [(False, "form")],
                    }
                else:
                    raise UserError(_('Төрийн банк (JSON) сонголтод зөвхөн JSON өрөгтгөлтэй файл оруулана уу !'))
        return super(AccountBankStatementImport, self).import_file()



