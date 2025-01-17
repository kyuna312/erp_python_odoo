from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests
from .ref import ADDRESS_TYPE

# class UbUser(models.Model):
#     _name = "auth.user"
#     _description = "Хэрэглэгч"
#     # _rec_name = "invoice_number"
#
#     # name = fields.Char("Нэр", required=True)
#     # surname = fields.Char("Овог", required=True)
#     # # register = fields.Char('Регистр', required=True)
#     # phone = fields.Char("Утас", required=True, tracking=True)
#     # email = fields.Char("И-мэйл", required=True, tracking=True)
#     # main_partner = fields.Integer("Үндсэн бүртгэл Id", required=True, readonly=True)
#     password = fields.Char('password', max_length=128)
#     last_login = fields.Datetime('Last login')
#     first_name = fields.Char('First name')
#     last_name = fields.Char('Last name')
#     email = fields.Char('Email')
#     date_joined = fields.Datetime('Date joined')
#     is_active = fields.Boolean('is active')
#     username = fields.Char('Username')
#     phone = fields.Char('Phone')
#     is_superuser = fields.Boolean('is superuser')
#     last_login_moved0 = fields.Datetime('Last login moved0')
#     date_joined_moved0 = fields.Datetime('Date joined moved0')
#     is_staff = fields.Boolean('Is staff')

class OdooUser(models.Model):
    _inherit = 'res.users'
    access_type = fields.Selection(ADDRESS_TYPE, 'Хандах төрөл', default="AAN", required=True, context={'user_preference': True})
    SELF_WRITEABLE_FIELDS = ['signature', 'action_id', 'company_id', 'email', 'name', 'image_1920', 'lang', 'tz', 'api_key_ids', 'api_key_ids', 'api_key_ids', 'api_key_ids', 'api_key_ids', 'api_key_ids', 'api_key_ids', 'api_key_ids', 'notification_type', 'api_key_ids', 'notification_type', 'api_key_ids', 'notification_type', 'api_key_ids', 'notification_type', 'additional_note', 'address_home_id', 'address_id', 'barcode', 'birthday', 'category_ids', 'children', 'coach_id', 'country_of_birth', 'department_id', 'display_name', 'emergency_contact', 'emergency_phone', 'employee_bank_account_id', 'employee_country_id', 'gender', 'identification_id', 'is_address_home_a_company', 'job_title', 'private_email', 'km_home_work', 'marital', 'mobile_phone', 'notes', 'employee_parent_id', 'passport_id', 'permit_no', 'employee_phone', 'pin', 'place_of_birth', 'spouse_birthdate', 'spouse_complete_name', 'visa_expire', 'visa_no', 'work_email', 'work_location', 'work_phone', 'certificate', 'study_field', 'study_school', 'api_key_ids', 'notification_type', 'additional_note', 'address_home_id', 'address_id', 'barcode', 'birthday', 'category_ids', 'children', 'coach_id', 'country_of_birth', 'department_id', 'display_name', 'emergency_contact', 'emergency_phone', 'employee_bank_account_id', 'employee_country_id', 'gender', 'identification_id', 'is_address_home_a_company', 'job_title', 'private_email', 'km_home_work', 'marital', 'mobile_phone', 'notes', 'employee_parent_id', 'passport_id', 'permit_no', 'employee_phone', 'pin', 'place_of_birth', 'spouse_birthdate', 'spouse_complete_name', 'visa_expire', 'visa_no', 'work_email', 'work_location', 'work_phone', 'certificate', 'study_field', 'study_school', 'api_key_ids', 'notification_type', 'additional_note', 'address_home_id', 'address_id', 'barcode', 'birthday', 'category_ids', 'children', 'coach_id', 'country_of_birth', 'department_id', 'display_name', 'emergency_contact', 'emergency_phone', 'employee_bank_account_id', 'employee_country_id', 'gender', 'identification_id', 'is_address_home_a_company', 'job_title', 'private_email', 'km_home_work', 'marital', 'mobile_phone', 'notes', 'employee_parent_id', 'passport_id', 'permit_no', 'employee_phone', 'pin', 'place_of_birth', 'spouse_birthdate', 'spouse_complete_name', 'visa_expire', 'visa_no', 'work_email', 'work_location', 'work_phone', 'certificate', 'study_field', 'study_school', 'api_key_ids', 'notification_type', 'additional_note', 'address_home_id', 'address_id', 'barcode', 'birthday', 'category_ids', 'children', 'coach_id', 'country_of_birth', 'department_id', 'display_name', 'emergency_contact', 'emergency_phone', 'employee_bank_account_id', 'employee_country_id', 'gender', 'identification_id', 'is_address_home_a_company', 'job_title', 'private_email', 'km_home_work', 'marital', 'mobile_phone', 'notes', 'employee_parent_id', 'passport_id', 'permit_no', 'employee_phone', 'pin', 'place_of_birth', 'spouse_birthdate', 'spouse_complete_name', 'visa_expire', 'visa_no', 'work_email', 'work_location', 'work_phone', 'certificate', 'study_field', 'study_school', 'api_key_ids', 'notification_type', 'additional_note', 'address_home_id', 'address_id', 'barcode', 'birthday', 'category_ids', 'children', 'coach_id', 'country_of_birth', 'department_id', 'display_name', 'emergency_contact', 'emergency_phone', 'employee_bank_account_id', 'employee_country_id', 'gender', 'identification_id', 'is_address_home_a_company', 'job_title', 'private_email', 'km_home_work', 'marital', 'mobile_phone', 'notes', 'employee_parent_id', 'passport_id', 'permit_no', 'employee_phone', 'pin', 'place_of_birth', 'spouse_birthdate', 'spouse_complete_name', 'visa_expire', 'visa_no', 'work_email', 'work_location', 'work_phone', 'certificate', 'study_field', 'study_school', 'api_key_ids', 'notification_type', 'additional_note', 'address_home_id', 'address_id', 'barcode', 'birthday', 'category_ids', 'children', 'coach_id', 'country_of_birth', 'department_id', 'display_name', 'emergency_contact', 'emergency_phone', 'employee_bank_account_id', 'employee_country_id', 'gender', 'identification_id', 'is_address_home_a_company', 'job_title', 'private_email', 'km_home_work', 'marital', 'mobile_phone', 'notes', 'employee_parent_id', 'passport_id', 'permit_no', 'employee_phone', 'pin', 'place_of_birth', 'spouse_birthdate', 'spouse_complete_name', 'visa_expire', 'visa_no', 'work_email', 'work_location', 'work_phone', 'certificate', 'study_field', 'study_school', 'access_type']
    def write(self, vals):
        if(not vals.get('lang')):
            vals['lang'] = self.lang
        return super(OdooUser, self).write(vals)

    def get_access_type_template_data(self):
        types = dict(ADDRESS_TYPE)
        return {
            "access_types": ADDRESS_TYPE,
            "current_access_type":(self.env.user.access_type, types[self.env.user.access_type]),
        }
    def change_access_type(self, vals):
        self.env['res.users'].sudo().browse(self.env.uid).write({
            'lang': self.lang,
            'access_type': vals.get('access_type')
        })
        return True
# class AccountUsertoken(models.Model):
#     _name = "user.authtoken"
#     _description = "Нэвтрэх токен"
#     _rec_name = "token"
#
#     token = fields.Char("Token", index=True)
#     partner_id = fields.Many2one("res.partner", "Хэрэглэгч", required=False)
#     user_id = fields.Integer(string="Контор хэрэглэгч ID", required=True)
#     expire_date = fields.Datetime(string="Хүчингүй болох огноо", readonly=True)

# class Employee(models.Model):
#     _inherit = 'hr.employee'
    # is_inspector = fields.Boolean(store=False, compute="compute_inspector")
    #
    # def compute_inspector(self):
    #     for obj in self:
    #         obj.is_inspector = obj.user_id.has_group('ub_kontor.group_kontor_inspector')
