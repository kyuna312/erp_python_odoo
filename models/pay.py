from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests
from .ref import ADDRESS_TYPE

PAY_RECEIPT_STATE = [('draft', 'Ноорог'), ('confirmed', 'Баталгаажсан'), ('invoice_created', 'Нэхэмжлэл үүссэн'),
                     ('cancelled', 'Цуцалсан')]
from datetime import datetime, timedelta
import logging
from urllib.parse import quote
import base64
import xlsxwriter
import io
from itertools import groupby
from operator import itemgetter

loggger = logging.getLogger('pay module:')


def get_years():
    year_list = []
    curr_year = int(datetime.now().strftime('%Y'))
    for i in range(curr_year, 2019, -1):
        year_list.append((str(i), str(i)))
    return year_list


class PayReceipt(models.Model):
    _name = 'pay.receipt'
    _description = 'Төлбөрийн баримт'
    _rec_name = "name"
    _sql_constraints = [
        ('pay_receipt_unique', 'unique (year,month,company_id,address_type)', 'Төлбөрийн баримт давхцаж байна!'),
    ]
    year = fields.Selection(get_years(), 'Он', required=True)
    month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Сар', required=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', index=True, default=lambda self: self.env.user.company_id.id)
    state = fields.Selection(PAY_RECEIPT_STATE, 'Төлөв', default='draft')
    receipt_address_ids = fields.One2many('pay.receipt.address', 'receipt_id', string='Төлбөрийн баримт')
    # receipt_address_view_ids = fields.One2many('pay.receipt.address', 'receipt_id', string='Төлбөрийн баримт')
    name = fields.Char('Нэр', store=True, compute="_compute_name")
    address_type = fields.Selection(ADDRESS_TYPE, 'Тоотын төрөл', required=True,
                                    default=lambda self: self.env.user.access_type)
    uncreated_address_ids = fields.Many2many('ref.apartment', string='Үүсээгүй байрнууд', store=False,
                                             compute="_compute_uncreated_apartment_ids")
    process = fields.Integer('Процесс', store=True)

    xls_report = fields.Binary(string='Excel тайлан')
    day_adjustment_ids = fields.One2many('pay.receipt.days.adjustments', 'receipt_id', 'Өөрчлөгдөх өдрүүд')

    first_balance = fields.Float('Эхний үлдэгдэл')

    total_amount_by_service = fields.Float('Үйлчилгээний нийт дүн', compute="compute_current_total_amount")
    total_amount_by_address = fields.Float('Тоот нийт дүн', compute="compute_current_total_amount")
    diff_amount  = fields.Float('Зөрүү', compute="compute_current_total_amount")
    def compute_current_total_amount(self):
        ids = self.ids
        if ids:
            query = f"""
                select pra.receipt_id as receipt_id ,sum(round(cast(pral.total_amount as numeric),2)) as amount 
                from pay_receipt_address pra 
                inner join pay_receipt_address_line pral on pral.receipt_address_id = pra.id 
                where pra.receipt_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
                group by pra.receipt_id;
            """
            self.env.cr.execute(query)
            total_amount_list_by_service = self.env.cr.dictfetchall()
            total_amount_list_by_service = groupby(total_amount_list_by_service, key=lambda x: x['receipt_id'])
            total_amount_list_by_service = {key: list(group) for key, group in total_amount_list_by_service}
            query = f"""
                select pra.receipt_id as receipt_id, sum(round(cast(pra.total_amount as numeric),2)) as amount 
                from pay_receipt_address pra
                where pra.receipt_id in {tuple(ids) if len(ids) > 1 else f"({ids[0]})"}
                group by pra.receipt_id;
            """
            self.env.cr.execute(query)
            total_amount_list_by_address = self.env.cr.dictfetchall()
            total_amount_list_by_address = groupby(total_amount_list_by_address, key=lambda x: x['receipt_id'])
            total_amount_list_by_address = {key: list(group) for key, group in total_amount_list_by_address}
            for obj in self:
                id = obj.id
                total_amount_by_service = total_amount_list_by_service.get(id)[0].get('amount') if total_amount_list_by_service.get(id) else 0.0
                total_amount_by_address = total_amount_list_by_address.get(id)[0].get('amount') if total_amount_list_by_address.get(id) else 0.0
                obj.total_amount_by_service = total_amount_by_service
                obj.total_amount_by_address = total_amount_by_address
                obj.diff_amount = total_amount_by_service - total_amount_by_address

    def show_address_with_difference(self):
        for obj in self:
            query = f"""
                select pra.id as id, round(cast(pra.total_amount as numeric),2), round(cast(sum(pral.total_amount) as numeric),2) as total_amount 
                from pay_receipt_address pra 
                inner join pay_receipt_address_line pral on pra.id = pral.receipt_address_id 	
                where pra.receipt_id = {obj.id}
                group by pra.id 
                having round(cast(pra.total_amount as numeric),2) != round(cast(sum(pral.total_amount) as numeric),2)
            """
            self.env.cr.execute(query)
            receipt_address_ids_with_diff =  self.env.cr.dictfetchall()
            receipt_address_ids_with_diff = [r.get('id') for r in receipt_address_ids_with_diff]
            return {
                'name': _('Төлбөрүүд'),
                'type': 'ir.actions.act_window',
                'target': 'current',
                'view_mode': 'tree,form',
                'res_model': 'pay.receipt.address',
                'domain': [('id', 'in', receipt_address_ids_with_diff)]
            }
    def _compute_uncreated_address_ids(self):
        for obj in self:
            self.env.cr.execute(f"""
                select apartment.id as apartment_id, count(address.family) as family_count
                from ref_apartment apartment 
                inner join ref_address address on apartment.id = address.apartment_id {'and address.family > 0' if obj.address_type == 'OS' else ''} and address.type='{obj.address_type}'
                where address.id not in (
                    select pra.address_id from pay_receipt_address pra where pra.receipt_id = {obj.id}
                ) and address.company_id = {obj.company_id.id} and address.active=True
                group by apartment.id
            """)
            apartment_list = self.env.cr.fetchall()
            obj.uncreated_address_ids = [(6, 0, [apartment for apartment, family_count in apartment_list])]
            if (obj.state == 'draft'):
                uncreated = len(apartment_list)
                created = len(obj.receipt_address_ids.ids)
                total = uncreated + created
                try:
                    obj.process = created * 100 / total
                except Exception as ex:
                    obj.process = 0

    def _compute_uncreated_apartment_ids(self):
        for obj in self:
            company_id = obj.company_id.id
            query = f"""
                select ra.id as apartment_id, count(address.id) as apartment_count from ref_apartment ra
                inner join ref_address address on address.apartment_id = ra.id and address.type = '{obj.address_type}'
                where ra.company_id = {company_id} and ra.id not in (
                    select apartment.id from pay_receipt pr 
                    inner join pay_receipt_address pra on pra.receipt_id = pr.id and pr.id ={obj.id}
                    inner join ref_address address on address.id = pra.address_id and address.company_id = {company_id}
                    inner join ref_apartment apartment on apartment.id = address.apartment_id and apartment.active = True 
                    group by apartment.id
                ) and ra.active = True
                group by ra.id
            """
            self.env.cr.execute(query)
            uncreated_apartment_list = self.env.cr.dictfetchall()
            obj.uncreated_address_ids = [(6, 0, [])]
            obj.uncreated_address_ids = [
                (6, 0, [apartment.get('apartment_id') for apartment in uncreated_apartment_list if
                        apartment.get('apartment_count') > 0])]
            if (obj.state == 'draft'):
                uncreated_apartment = len(uncreated_apartment_list)

                query = f"""
                    select ra.apartment_id as apartment_id from pay_receipt pr 
                    inner join pay_receipt_address pra on pra.receipt_id = pr.id and pr.id = {obj.id}
                    inner join ref_address ra on ra.id = pra.address_id
                    where pr.id = {obj.id}
                    group by ra.apartment_id 
                """
                self.env.cr.execute(query)
                created_apartment_count = len(self.env.cr.dictfetchall())
                try:
                    obj.process = created_apartment_count * 100 / (created_apartment_count + uncreated_apartment)
                except Exception as ex:
                    obj.process = 0

    def create_invoice(self):
        for obj in self:
            return {
                'name': _('Нэхэмжлэл үүсгэх'),
                'type': 'ir.actions.act_window',
                'target': 'new',
                'view_mode': 'form',
                'res_model': 'pay.receipt.create.invoice',
                'view_id': self.env.ref('ub_kontor.pay_receipt_create_invoice_form').id,
                'context': {
                    'default_pay_receipt_id': obj.id
                }
            }

    @api.depends('year', 'month')
    def _compute_name(self):
        for obj in self:
            obj.name = f"{obj.year} - {obj.month}"

    def confirm(self):
        for obj in self:
            obj.state = 'confirmed'
            self.env.cr.execute(f"""
                UPDATE pay_receipt_address SET state = 'confirmed' where receipt_id = {obj.id}
            """)

    def draft(self):
        for obj in self:
            obj.state = 'draft'
            self.env.cr.execute(f"""
                            UPDATE pay_receipt_address SET state = 'draft' where receipt_id = {obj.id}
                        """)

    def cancel(self):
        for obj in self:
            self.env.cr.execute(f"""SELECT invoice_id FROM pay_receipt pr
                INNER JOIN pay_receipt_address pra ON  pra.receipt_id = pr.id
                INNER JOIN account_move am on am.id = pra.invoice_id
                where am.state != 'cancel' and pr.id = {obj.id}
            """)
            uncanceled_invoice = self.env.cr.fetchall()
            if not uncanceled_invoice:
                obj.state = 'cancelled'
                self.env.cr.execute(f"""
                                UPDATE pay_receipt_address SET state = 'cancelled' where receipt_id = {obj.id}
                            """)
            else:
                raise UserError(_('Цуцлагдаагүй нэхэмжлэл байна'))

    def show_details_by_service(self):
        for obj in self:
            # return {
            #     'name': _('Баримтын задаргаа'),
            #     'type': 'ir.actions.act_window',
            #     'view_mode': 'form',
            #     'target': 'new',
            #     'res_model': 'pay.receipt.search.items.wizard',
            #     'context': {
            #         'action_name': _('Баримтын задаргаа'),
            #         'search_model': 'pay.receipt.address.line',
            #         'search_domain': [('receipt_address_id.receipt_id', '=', obj.id)],
            #         'base_context': {'search_default_inspector_id_group': 1,'search_default_apartment_id_group': 1},
            #         'view_mode': 'tree,graph'
            #     }
            # }
            return {
                'name': _('Баримтын задаргаа'),
                'type': 'ir.actions.act_window',
                'view_mode': 'tree,graph,pivot',
                'res_model': 'pay.receipt.address.line',
                'target': 'current',
                'domain': [('receipt_address_id.receipt_id', '=', obj.id)],
                'context': {
                    'search_default_service_type_id_group': 1
                }
            }

    def show_details_by_address(self):
        for obj in self:
            # return {
            #     'name':  _('Баримтын мөр хайх'),
            #     'type': 'ir.actions.act_window',
            #     'target': 'new',
            #     'view_mode': 'form',
            #     'res_model': 'pay.receipt.search.items.wizard',
            #     'context': {
            #         'action_name':  _('Баримтын мөр хайх'),
            #         'search_model': 'pay.receipt.address',
            #         'search_domain': [('receipt_id', '=', obj.id)],
            #         'base_context': {'search_default_inspector_id_group': 1,'search_default_apartment_id_group': 1},
            #         'view_mode': 'tree,form,graph'
            #     }
            # }
            return {
                'name': _('Баримтын мөр'),
                'type': 'ir.actions.act_window',
                'view_mode': 'tree,form,graph,pivot',
                'res_model': 'pay.receipt.address',
                'target': 'current',
                'domain': [('receipt_id', '=', obj.id)],
                # 'context': {
                #     'search_default_inspector_id_group': 1,
                #     'search_default_apartment_id_group': 1,
                # }
            }

    def create_receipt_address(self):
        for obj in self:
            return {
                'name': _('Төлбөрийн баримтын мөр үүсгэх'),
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'pay.receipt.wizard',
                'target': 'new',
                'context': {
                    'default_pay_receipt_id': obj.id,
                },
            }

    def change_days(self):
        for obj in self:
            obj.day_adjustment_ids.change_days()
            obj.action_recompute()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Хоног өөрчлөлт амжилттай хийгдлээ',
                    'message': f'',
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    }
                }
            }
            # return {
            #     'name': _('Хоног өөрчлөх'),
            #     'type': 'ir.actions.act_window',
            #     'view_mode': 'form',
            #     'target': 'new',
            #     'res_model': 'pay.receipt.change.days',
            #     'context': {
            #         'default_receipt_id': obj.id,
            #         'default_address_type': obj.address_type,
            #         'default_company_id': obj.company_id.id
            #     }
            # }

    def unlink(self):
        for obj in self:
            query = f"""
                select invoice.id from pay_receipt_address pra 
                inner join pay_receipt_address_invoice invoice on invoice.receipt_address_id = pra.id
                where pra.receipt_id = {obj.id}
                group by invoice.id
            """
            self.env.cr.execute(query)
            invoice_ids = self.env.cr.dictfetchall()
            if invoice_ids:
                raise UserError(f'{obj.year} оны {obj.month}-р сарын нэхэмжлэлүүдийг устгаагүй байна!.')
            self.env.cr.execute(f"""
                call delete_pay_receipt('{obj.year}', '{obj.month}', {obj.company_id.id}, '{obj.address_type}');
            """)
        return super(PayReceipt, self).unlink()

    def delete_row(self):
        for obj in self:
            self.env.cr.execute(f"""
                SELECT invoice.id as invoice_id FROM pay_receipt_address_invoice invoice
                inner join pay_receipt_address receipt_address on receipt_address.id = invoice.receipt_address_id and receipt_address.receipt_id = {obj.id}
                limit 1
            """)
            has_invoice = self.env.cr.dictfetchall()
            if has_invoice:
                raise UserError('Төлбөл зохихтой холбоотой нэхэмжлэл аль хэдийн үүссэн учир устгах боломжгүй!')
            self.env.cr.execute(f"""
                call delete_pay_receipt('{obj.year}', '{obj.month}', {obj.company_id.id}, '{obj.address_type}');
            """)
            return True

    def send_sms(self):
        """Currently haven't used that function yet"""
        loggger.warning("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ SMS CRON IS WORKING ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        self.env.cr.execute("""
            SELECT pra.id as id, partner.id as partner_id, apartment.name as apartment,address.address as address,partner.phone as phone, pra.total_amount as total_amount, receipt.year as year, receipt.month as month
                FROM pay_receipt_address pra
            INNER JOIN pay_receipt receipt ON receipt.id = pra.receipt_id
            INNER JOIN account_move invoice ON invoice.receipt_address_id = pra.id and invoice.state = 'posted'
            INNER JOIN res_partner partner ON partner.id = invoice.partner_id
            INNER JOIN ref_address address ON partner.id = address.partner_id
            INNER JOIN ref_apartment apartment ON apartment.id = address.apartment_id
            WHERE sms1_sent is not True and invoice.payment_state != 'paid' and invoice.move_type='out_invoice'
        """)
        ICPSudo = self.env["ir.config_parameter"].sudo()
        web_domain = ICPSudo.get_param("ub_kontor.kontor_web")
        sms_url = str(web_domain) + "/{phone}/?sms={msg_body}"
        data_send_sms = self.env.cr.dictfetchall()
        for data in data_send_sms:
            msg = f"""{data.get('apartment')}-{data.get('address')} toot {data.get('month')} sariin tulbur {data.get('total_amount')}mnt garlaa. Toozaa app-aar tuluh bol https://qr1.be/DAOS"""
            msg = quote(msg)
            # response = requests.get("" + data.get('phone') + "/?sms=" + msg)
            response = requests.get(sms_url.format(phone=data.get('phone'), msg_body=msg))

            if (response.status_code == 200):
                self.env.cr.execute(f"""
                    UPDATE pay_receipt_address SET sms1_sent = True WHERE id = {data.get('id')}
                """)
        self.env.cr.execute("""
            SELECT string_agg(pra.id::text, ',')as ids, partner.id as partner_id, apartment.name as apartment,address.address as address,
                partner.phone as phone, sum(pra.amount_residual) as total_amount, count(pra.id) as invoice_count 
                FROM pay_receipt_address pra
            INNER JOIN account_move invoice ON invoice.receipt_address_id = pra.id and invoice.state = 'posted'
            INNER JOIN res_partner partner ON partner.id = invoice.partner_id
            INNER JOIN ref_address address ON partner.id = address.partner_id
            INNER JOIN ref_apartment apartment ON apartment.id = address.apartment_id
            WHERE sms1_sent is True and sms2_sent is not True and posted_date + INTERVAL '15 day' <= now() and invoice.payment_state != 'paid' and invoice.move_type='out_invoice'
            group by address.id, partner.id, apartment.id
        """)
        data_send_sms = self.env.cr.dictfetchall()
        for data in data_send_sms:
            msg = f"""{data.get('apartment')}-{data.get('address')} toot uldegdel {data.get('total_amount')}mnt TOOZAA app-aar tuluh bol https://qr1.be/DAOS"""
            msg = quote(msg)
            response = requests.get(sms_url.format(phone=data.get('phone'), msg_body=msg))
            if (response.status_code == 200):
                self.env.cr.execute(f"""
                    UPDATE pay_receipt_address SET sms2_sent = True WHERE id in ({data.get('id')})
                """)

    def get_xls_report(self):
        for obj in self:
            xls_content = io.BytesIO()
            workbook_wt = xlsxwriter.Workbook(xls_content)
            sheet_wt = workbook_wt.add_worksheet()
            sheet_wt.write(0, 0, 'Байцаагч')
            sheet_wt.write(0, 1, 'Хэрэглэгчийн код')
            sheet_wt.write(0, 2, 'Байр')
            sheet_wt.write(0, 3, 'Тоот')
            sheet_wt.write(0, 4, 'Овог')
            sheet_wt.write(0, 5, 'Нэр')
            self.env.cr.execute(f"""
                select pra.id as id ,he.name as inspector_name, ra.code as address_code, apartment.code as apartment_code, ra.address as address_address,ra.surname as surname, ra.name as name, 
                pra.total_amount as total_amount
                from pay_receipt pr
                inner join pay_receipt_address pra on pra.receipt_id  = pr.id
                inner join ref_address ra on ra.id = pra.address_id 
                inner join ref_apartment apartment on apartment.id = ra.apartment_id 
                left join hr_employee he on he.id = pra.inspector_id
                where pr.id = {obj.id}
                group by pra.id, he.id, ra.id, apartment.id

            """)
            receipt_address_datas = self.env.cr.dictfetchall()
            self.env.cr.execute(f"""
                select CONCAT(rp.id,',',rst.id) as id, CONCAT(rst.name, ' /', rp.name, '/') as service_name
                from pay_receipt pr 
                inner join pay_receipt_address pra on pra.receipt_id = pr.id
                inner join pay_receipt_address_line pral on pral.receipt_address_id = pra.id
                left join ref_pricelist rp on rp.id = pral.pricelist_id
                left join ref_service_type rst on rst.id = pral.service_type_id 
                where pr.id = {obj.id} and (rp.id is not null or pral.service_type_id is not null)
                group by CONCAT(rp.id,',',rst.id), CONCAT(rst.name, ' /', rp.name, '/')
                order by CONCAT(rst.name, ' /', rp.name, '/')
            """)
            used_pricelist_datas = self.env.cr.dictfetchall()
            self.env.cr.execute(f"""
                select pra.id as pra_id, CONCAT(pral.pricelist_id,',',pral.service_type_id) as pricelist_id, SUM(round(cast(pral.noat as numeric),2)) as noat, 
                SUM(round(cast(pral.total_amount as numeric),2)) as total_amount, SUM(round(cast(pral.price as numeric),2)) as price  
                from pay_receipt pr
                inner join pay_receipt_address pra on pra.receipt_id = pr.id
                inner join pay_receipt_address_line pral on pral.receipt_address_id = pra.id
                where pr.id = {obj.id} and (pral.pricelist_id is not null or pral.service_type_id is not null)
                group by pra.id,CONCAT(pral.pricelist_id,',',pral.service_type_id)
                order by pra.id, CONCAT(pral.pricelist_id,',',pral.service_type_id) asc
            """)
            receipt_address_line_datas = self.env.cr.dictfetchall()
            # self.env.cr.execute(f"""
            #     select pra.id as pra_id, sum(pral.noat) as noat, sum(pral.total_amount) as total_amount, sum(pral.price) as price
            #     from pay_receipt pr
            #     inner join pay_receipt_address pra on pra.receipt_id = pr.id
            #     inner join pay_receipt_address_line pral on pral.receipt_address_id = pra.id
            #     where pr.id = {obj.id} and (pral.pricelist_id is null and pral.service_type_id is null)
            #     group by pra.id
            #     order by pra.id asc
            # """)
            # receipt_addres_payments = self.env.cr.dictfetchall()
            grouped_data = {}
            for key1, group1 in groupby(receipt_address_line_datas, key=itemgetter('pra_id')):
                grouped_data[key1] = {}
                sub_group = list(group1)  # Convert group1 to list to use it multiple times
                for key2, group2 in groupby(sub_group, key=itemgetter('pricelist_id')):
                    grouped_data[key1][key2] = list(group2)
            receipt_address_line_datas = grouped_data

            # grouped_data = groupby(receipt_addres_payments, key=lambda x: x['pra_id'])
            # receipt_addres_payments = {key: list(group) for key, group in grouped_data}

            title_column_count = 6
            for pricelist in used_pricelist_datas:
                sheet_wt.write(0, title_column_count, pricelist.get('service_name'))
                title_column_count += 1
            # sheet_wt.write(0, title_column_count, 'Төлбөрт үйлчилгээ')
            # title_column_count+=1
            sheet_wt.write(0, title_column_count, 'Нийт')
            row_start_count = 1
            for receipt_address in receipt_address_datas:
                sheet_wt.write(row_start_count, 0, receipt_address.get('inspector_name'))
                sheet_wt.write(row_start_count, 1, receipt_address.get('address_code'))
                sheet_wt.write(row_start_count, 2, receipt_address.get('apartment_code'))
                sheet_wt.write(row_start_count, 3, receipt_address.get('address_address'))
                sheet_wt.write(row_start_count, 4, receipt_address.get('surname'))
                sheet_wt.write(row_start_count, 5, receipt_address.get('name'))
                col_start_count = 6
                for pricelist in used_pricelist_datas:
                    line = receipt_address_line_datas.get(receipt_address.get('id'))
                    if line:
                        line = line.get(pricelist.get('id'))
                        if line:
                            sheet_wt.write(row_start_count, col_start_count, line[0].get('total_amount'))
                    col_start_count += 1
                # payment_line = receipt_addres_payments.get(receipt_address.get('id'))
                # sheet_wt.write(row_start_count, col_start_count, payment_line[0].get('total_amount') if payment_line else '' )
                # col_start_count += 1
                sheet_wt.write(row_start_count, col_start_count, receipt_address.get('total_amount'))
                row_start_count += 1
            workbook_wt.close()
            xls_content.seek(0)
            xlsx_data = base64.b64encode(xls_content.read())
            obj.write({'xls_report': xlsx_data})
            name = 'Төлбөл_зохих.xlsx'
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/?model=pay.receipt&id={self.id}&field=xls_report&filename_field={name}&download=true&filename={name}',
                'target': 'self',
                # 'name': name
            }

    def action_get_bank_json(self):
        # url = self.env["ir.config_parameter"].sudo().get_param("ub_kontor.kontor_web")
        for obj in self:
            # return {
            #     "type": "ir.actions.act_url",
            #     "target": "self",
            #     "url": f"{url}/bank/files/{obj.company_id.id}/?token=kdisoe9e93eiiwow;;830woieafj24&pay_receipt={obj.id}",
            # }
            return {
                'name': _('Төрийн банкны файл татах'),
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'target': 'new',
                'res_model': 'bank.statement.export.json',
                'context': {
                    'default_receipt_id': obj.id,
                    'default_method': "receipt"
                }
            }

    def action_get_bank_json_by_apartment(self):
        for obj in self:
            return {
                'name': _('Төрийн банкны файл татах'),
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'target': 'new',
                'res_model': 'bank.statement.export.json',
                'context': {
                    'default_receipt_id': obj.id,
                    'default_method_id': f'ref.apartment'
                }
            }

    def action_recompute(self):
        for obj in self:
            self.env.cr.execute(f"""
                CALL update_pay_receipt({self.env.uid}, '{obj.year}', '{obj.month}', {obj.company_id.id}, '{obj.address_type}');
            """)
            obj.clear_invoice_difference()

    @api.model
    def create_procedure(self):
        self.env.cr.execute("""DROP PROCEDURE if EXISTS create_pay_receipt_apartment;""")
        procedure = """
                                

                    CREATE OR REPLACE PROCEDURE public.create_pay_receipt_apartment(
	userid integer,
	line_year character varying,
	line_month character varying,
	ap_id integer[],
	tcompany_id integer,
	ttype character varying)
LANGUAGE 'plpgsql'
AS $BODY$
                            DECLARE row_number INT;
                            DECLARE rec RECORD;
                            DECLARE sha RECORD;
                            DECLARE rashaan RECORD;
                            DECLARE amount FLOAT;
							DECLARE amount1 FLOAT;
                            DECLARE noat FLOAT;
							DECLARE noat1 FLOAT;
                            DECLARE total_amount FLOAT;
							DECLARE total_amount1 FLOAT;
                            DECLARE is_insert BOOLEAN;
                                days INTEGER;
                                valuee FLOAT;
								valuee1 FLOAT;
                                uvul_tarif FLOAT;
                                une FLOAT;
                                sar INTEGER;
                            BEGIN
                        -- usnii tooluur bodoh
                        -- tsever us, bohir us, uxx
                                DROP TABLE IF EXISTS temp_counter_calc;
                                CREATE TEMPORARY TABLE temp_counter_calc AS
                                -- address_id, service_type_id, uom_id
                                SELECT --*
                                    cc.id, cc.address_id, cc.state, cc.registered_date, ra.type,
                                    ra.pure_water, ra.impure_water, ra.heating, ra.heating_water_fee, ra.proof, ra.mineral_water,
                            --     	ccl.now_counter, ccl.last_counter, ccl.difference, 
                                    ccl.fraction,
                                    CASE WHEN cn.return_type='1' THEN ccl.difference ELSE ccl.difference*-1 END as ccl_difference,
                                    cn.type cn_type, cn.return_type,
                                    100 ccud_percent, --ccud.service_type_id,
                                    pl.id pl_id, pl.price, --pl.uom_id,
                                    ccs.percent ccs_percent,
                                    CASE WHEN cn.return_type='1' THEN
                                        (CASE WHEN ccs.percent is not null THEN ccl.difference * (100-ccs.percent)/100 * ccud.percent/100 ELSE ccl.difference * ccud.percent/100 END)
                                    ELSE
                                        (CASE WHEN ccs.percent is not null THEN ccl.difference * (100-ccs.percent)/100 * -1 * ccud.percent/100 ELSE ccl.difference * -1 * ccud.percent/100 END)	
                                    END  as ccl_difference_exact,
                                    (CASE WHEN ccs.percent is not null THEN ccl.fraction * (100-ccs.percent)/100 * ccud.percent/100 ELSE ccl.fraction * ccud.percent/100 END) as ccl_fraction_exact
                                -- SELECT * 
                                FROM counter_counter cc 
                                INNER JOIN ref_address ra ON cc.address_id=ra.id and ra.company_id=tcompany_id AND ra.type=ttype AND ra.active=true AND ra.apartment_id = ANY(ap_id) 
                                INNER JOIN counter_counter_line ccl ON cc.id=ccl.counter_id 
                                    and group_id in (SELECT id FROM counter_counter_line_group cclg WHERE cclg.year=line_year and cclg.month=line_month)
                                INNER JOIN counter_name cn ON cn.id=cc.name_id
                                LEFT JOIN counter_counter_usage_division ccud ON cc.id=ccud.counter_id
                                INNER JOIN ref_pricelist pl ON pl.id=ccud.pricelist_id
                                LEFT JOIN (SELECT counter_id, sum(percent) percent FROM counter_counter_sharing GROUP BY counter_id) ccs 
                                    ON cc.id=ccs.counter_id
                                WHERE (cc.category='counter' OR cc.category='thermal_counter') AND (cc.state='new' OR cc.state='confirm' OR cc.state='normal');
                                
                                -- huvaagdah hereglee (shared counter)
                                INSERT INTO temp_counter_calc
                                SELECT --*
                                    cc.id, nccs.address_id, cc.state, cc.registered_date, ra.type,
                                    ra.pure_water, ra.impure_water, ra.heating, ra.heating_water_fee, ra.proof, ra.mineral_water,
                                --     	ccl.now_counter, ccl.last_counter, ccl.difference, 
                                    ccl.fraction,
                                    CASE WHEN cn.return_type='1' THEN ccl.difference ELSE ccl.difference*-1 END as ccl_difference,
                                    cn.type cn_type, cn.return_type,
                                    100 ccud_percent, --ccud.service_type_id, -- ccud.percent baisang 100 bolgoson
                                    pl.id pl_id, pl.price, --pl.uom_id,
                                    nccs.percent ccs_percent,
                                    CASE WHEN cn.return_type='1' THEN
                                        (CASE WHEN nccs.percent is not null THEN ccl.difference * (nccs.percent)/100 * ccud.percent/100 ELSE ccl.difference * ccud.percent/100 END)
                                    ELSE
                                        (CASE WHEN nccs.percent is not null THEN ccl.difference * (nccs.percent)/100 * -1 * ccud.percent/100 ELSE ccl.difference * -1 * ccud.percent/100 END)	
                                    END  as ccl_difference_exact,
                                    (CASE WHEN nccs.percent is not null THEN ccl.fraction * (nccs.percent)/100 * ccud.percent/100 ELSE ccl.fraction * ccud.percent/100 END) as ccl_fraction_exact
                                -- SELECT * 
                                FROM counter_counter_sharing nccs
                                INNER JOIN counter_counter cc ON nccs.counter_id=cc.id
                                INNER JOIN ref_address ra ON nccs.address_id=ra.id and ra.company_id=tcompany_id AND ra.type=ttype AND ra.active=true AND ra.apartment_id = ANY(ap_id)
                                INNER JOIN counter_counter_line ccl ON cc.id=ccl.counter_id 
                                    and group_id in (SELECT id FROM counter_counter_line_group cclg WHERE cclg.year=line_year and cclg.month=line_month)
                                INNER JOIN counter_name cn ON cn.id=cc.name_id
                                LEFT JOIN counter_counter_usage_division ccud ON cc.id=ccud.counter_id
                                INNER JOIN ref_pricelist pl ON pl.id=ccud.pricelist_id
                                -- LEFT JOIN (SELECT counter_id, sum(percent) percent FROM counter_counter_sharing GROUP BY counter_id) ccs 
                                -- 	ON cc.id=ccs.counter_id
                                WHERE (cc.category='counter' OR cc.category='thermal_counter');
                                
                                -- select shugamiin aldagdal
                                SELECT pl.service_type_id, pl.uom_id, rst.name FROM ref_pricelist pl INNER JOIN ref_service_type rst ON  pl.service_type_id=rst.id WHERE pl.code='130' INTO sha;
                                SELECT pl.service_type_id, pl.uom_id, pl.id pl_id, pl.price, rst.name FROM ref_pricelist pl INNER JOIN ref_service_type rst ON  pl.service_type_id=rst.id WHERE pl.code='72' INTO rashaan;
                                
                                FOR rec IN (
                                    SELECT t1.*, pl.service_type_id, pl.uom_id, pl.price, pl.days pricelist_days, pl.code plcode, rst.name, ra.apartment_id, ra.inspector_id FROM (
                                        SELECT 
                                            address_id, pl_id, sum(ccl_difference_exact) ccl_difference, sum(ccl_fraction_exact) fraction, 
                                            bool_or(heating) heating, bool_or(heating_water_fee) heating_water_fee, bool_or(impure_water) impure_water, bool_or(pure_water) pure_water, bool_or(mineral_water) mineral_water,
                                            max(ccud_percent) ccud_percent
                                        FROM temp_counter_calc --WHERE apartment_id = ANY(ap_id)
                                        GROUP BY address_id, pl_id ORDER BY address_id
                                    ) t1 
                                    INNER JOIN ref_pricelist pl ON t1.pl_id=pl.id
                                    INNER JOIN ref_service_type rst ON  pl.service_type_id=rst.id
                                    INNER JOIN ref_address ra ON ra.id=t1.address_id and ra.company_id=tcompany_id AND ra.type=ttype AND ra.active=true 
                                ) LOOP
                                    is_insert = False;
                                    amount := rec.price * (round(rec.ccl_difference::numeric, 2) + round(rec.fraction::numeric, 2)) * rec.ccud_percent / 100;
                                    noat := amount * 0.1;
                                    total_amount := amount + noat;
									total_amount := round(total_amount::numeric, 2);
                                    days := 30;
                                    valuee := rec.ccl_difference + rec.fraction;
                                    -- 249 tsever us, 251 bohir us, 250 uxx
                                    -- OS 17 tsever us, 35 bohir us, 24 uxx
                                    -- AAN 19 tsever us, 37 bohir us, 32 uxx
                                    IF rec.plcode='17' OR rec.plcode='19' THEN
                                        IF rec.pure_water THEN 
                                            is_insert = True;
                                            IF rec.plcode='19' THEN -- baiguullagiin tsever us ued rashaan bodno
                                                IF rec.mineral_water AND valuee>0 THEN -- tsever us hereglesen ued
                                                    INSERT INTO public.pay_receipt_address_line(
                                                        service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                                        usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount, 
                                                        apartment_id, inspector_id, pricelist_days)
                                                    VALUES (
                                                        rashaan.service_type_id, rashaan.name, valuee*rashaan.price, valuee*rashaan.price, rashaan.pl_id, rashaan.uom_id, days, userid, now(), 
                                                        valuee, 100, rashaan.price, 0, null, rec.address_id, valuee*rashaan.price, 
                                                        rec.apartment_id, rec.inspector_id, rec.pricelist_days);
                        --  							ON CONFLICT(receipt_address_id, address_id, pricelist_id) 
                        --  							DO UPDATE SET
                        --  								amount = pay_receipt_address_line.amount + valuee*rashaan.price,
                        --  								total_amount = pay_receipt_address_line.total_amount + valuee*rashaan.price,
                        --  								noat = pay_receipt_address_line.noat + 0,
                        --  								write_uid = userid,
                        --  								write_date = now();
                                                END IF;
                                            END IF;
                                        END IF;
                                    ELSIF rec.plcode='35' OR rec.plcode='37' THEN
                                        IF rec.impure_water THEN 
                                            is_insert = True;
                                        END IF;
                                    ELSIF rec.plcode='24' OR rec.plcode='32' THEN
                                        IF rec.heating_water_fee THEN 
                                            is_insert = True;
                                        END IF;
                                    -- halaalt, shugamiin aldagdal baiguullaga 45
                                    ELSIF rec.plcode='45' OR rec.plcode='44' OR rec.plcode='43' THEN
                                        IF rec.heating THEN 
                                            -- shugamiin aldagdal
											valuee1 := valuee*0.05;
 											valuee1 := round(valuee1::numeric, 2);
											amount1 := rec.price * valuee1;
											noat1 := amount1 * 0.1;
		                                    total_amount1 := amount1 + noat1;
                                            IF amount1>0 THEN 
                                                INSERT INTO public.pay_receipt_address_line(
                                                    service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                                    usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount, 
                                                    apartment_id, inspector_id, pricelist_days)
                                                VALUES (
                                                    sha.service_type_id, sha.name, TRUNC(amount1::numeric, 2), TRUNC(amount1::numeric, 2), rec.pl_id, sha.uom_id, days, userid, now(), 
                                                    valuee1, rec.ccud_percent, rec.price, noat1, null, rec.address_id, TRUNC(total_amount1::numeric, 2), 
                                                    rec.apartment_id, rec.inspector_id, rec.pricelist_days);
                        
                                            END IF;
                                            is_insert = True;
                                        END IF;
                                    ELSE
                                        is_insert = True;
                                    END IF;
                                    IF is_insert and amount>0 THEN
                                        INSERT INTO public.pay_receipt_address_line(
                                            service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                            usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount, 
                                            apartment_id, inspector_id, pricelist_days)
                                        VALUES (
                                            rec.service_type_id, rec.name, amount, amount, rec.pl_id, rec.uom_id, days, userid, now(), 
                                            valuee, rec.ccud_percent, rec.price, noat, null, rec.address_id, total_amount, 
                                            rec.apartment_id, rec.inspector_id, rec.pricelist_days);
                                    END IF;
                                END LOOP;
                        
                        -- halaalt bodoh mkv - 42 halaalt tooluurgui
                        -- AAN 46 halaalt 
                        -- dulaanii tooluurtai ailiig hasah, zuvhun haluun us tootsoh ued uugeer bodno
                                FOR rec IN (
                                    SELECT --* 
                                        ra.id address_id, ra.heating, rst.name, ras.square, ras.square_coef, ras.capacity, ras.capacity_coef, 
                                        pl.service_type_id, pl.price, pl.uom_id, pl.id pricelist_id, pl.days pricelist_days, pl.code plcode,
                                        ra.apartment_id, ra.inspector_id
                                    FROM ref_address ra 
                                    INNER JOIN (SELECT * FROM ref_address_square WHERE state='active') ras ON ras.address_id=ra.id and (ras.square>0 OR ras.capacity>0)
                                    LEFT JOIN (SELECT * FROM ref_pricelist WHERE code='42' OR code='46') pl ON 1=1
                                    INNER JOIN ref_service_type rst ON  pl.service_type_id=rst.id
                                    WHERE ra.company_id=tcompany_id AND ra.type=ttype AND ra.active=true  AND ra.apartment_id = ANY(ap_id)
										and ra.id NOT IN ( SELECT address_id FROM counter_counter cc
											LEFT JOIN ref_address ra ON cc.address_id=ra.id and ra.company_id=tcompany_id AND ra.type=ttype AND ra.active=true AND ra.apartment_id = ANY(ap_id)
											WHERE cc.category='thermal_counter' AND (cc.state='new' OR cc.state='confirm' OR cc.state='normal') GROUP BY cc.address_id
										)
                                ) LOOP
                                    amount := 0;
                                    IF rec.plcode='42' AND rec.square>0 THEN -- m2-aar bodoh
                                        amount := rec.price * rec.square * rec.square_coef / 100;
                                        noat := amount * 0.1;
                                        total_amount := amount + noat;
										total_amount := round(total_amount::numeric, 2);
                                        days := 30;
                                        valuee := rec.square;
                                    ELSIF rec.plcode='46' AND rec.capacity>0 THEN -- m3-eer bodoh 46
                                        amount := rec.price * rec.capacity * rec.capacity_coef / 100;
                                        noat := amount * 0.1;
                                        total_amount := amount + noat;
										total_amount := round(total_amount::numeric, 2);
                                        days := 30;
                                        valuee := rec.capacity;
                                    END IF;
                                    IF rec.heating and amount>0 THEN
                                        INSERT INTO public.pay_receipt_address_line(
                                            service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                            usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount, 
                                            apartment_id, inspector_id, pricelist_days)
                                        VALUES (
                                            rec.service_type_id, rec.name, amount, amount, rec.pricelist_id, rec.uom_id, days, userid, now(), 
                                            valuee, rec.square_coef, rec.price, noat, null, rec.address_id, total_amount, 
                                            rec.apartment_id, rec.inspector_id, rec.pricelist_days);
                                    END IF;
                                END LOOP;
                        -- Usnii tooluurgui zadgai bodoh
                        -- 244 tsever, 262 bohir, 252 uxx, 253 uxx uvul
                        -- 18 tsever, 36 bohir, 26 uxx, 27 uxx uvul
                        -- 		SELECT EXTRACT(MONTH FROM CURRENT_DATE) INTO sar;
                                SELECT price FROM ref_pricelist WHERE code='27' INTO uvul_tarif;
                                FOR rec IN (
                                    SELECT --* 
                                        ra.id address_id, ra.pure_water, ra.impure_water, ra.heating, ra.heating_water_fee, ra.proof, ra.mineral_water,
                                        ra.apartment_id, ra.inspector_id,
                                        rst.name, pl.service_type_id, pl.price, pl.days pricelist_days, pl.uom_id, pl.id pricelist_id, pl.code plcode, ra.family
                                    FROM ref_address ra
                                    LEFT OUTER JOIN counter_counter cc ON ra.id=cc.address_id AND cc.category='counter'
                                    LEFT JOIN (SELECT * FROM ref_pricelist WHERE code='18' or code='36' or code='26') pl ON 1=1
                                    INNER JOIN ref_service_type rst ON  pl.service_type_id=rst.id
                                    WHERE ra.company_id=tcompany_id AND ra.type=ttype AND ra.active=true AND ra.apartment_id = ANY(ap_id) 
                                        AND ra.id NOT IN (SELECT address_id FROM counter_counter_sharing) -- dundiin tooluurtai ailiig zadgaigaas hasah
                                        AND ( cc.id is null OR -- tooluurgui ailuudiig songoh
                                        -- buh tooluur ni evdersen ailuudiig songoh
                                        cc.id IN (SELECT max(s_cc.id)  FROM counter_counter s_cc
                                            LEFT JOIN ref_address s_ra ON s_cc.address_id=s_ra.id AND s_ra.company_id=tcompany_id AND s_ra.type=ttype AND s_ra.active=true -- AND ra.apartment_id = ANY(ap_id) ene udaashruulna
                                            WHERE (s_cc.state='broken' OR s_cc.state='done')  
                                                AND s_cc.address_id NOT IN (SELECT t_cc.address_id FROM counter_counter t_cc 
													LEFT JOIN ref_address t_ra ON t_ra.id=t_cc.address_id WHERE t_ra.company_id=tcompany_id AND t_ra.type=ttype AND t_cc.category='counter' AND t_cc.state!='broken' AND t_cc.state!='done'
																		   ) GROUP BY address_id)
                                        )
                                ) LOOP
                                    is_insert = False;
                                    if rec.plcode = '26' THEN
                                        IF rec.heating_water_fee THEN 
                                            is_insert = True;
                                        END IF;	
                                        CASE
                                            WHEN line_month IN ('10', '11', '12', '01', '02', '03', '04') THEN -- uvliin saruud
                        -- 						amount := rec.family * uvul_tarif;
                                                une := uvul_tarif;
                                            WHEN line_month = '05' THEN
                        -- 						amount := rec.family * uvul_tarif * 15/30 + rec.family * rec.price * 16/30;
                                                une := uvul_tarif * 15/31 + rec.price * 16/31;
                                            WHEN line_month = '09' THEN
                        -- 						amount := rec.family * uvul_tarif * 15/30 + rec.family * rec.price * 15/30;
                                                une := uvul_tarif * 15/30 + rec.price * 15/30;
                                            ELSE -- zuniii saruud 6, 7, 8
                        -- 						amount := rec.family * rec.price;
                                                une := rec.price;
                                        END CASE;
                                        amount := rec.family * une;
                                        noat := amount * 0.1;
                                        total_amount := amount + noat;
										total_amount := round(total_amount::numeric, 2);
                                        days := 30;
                                        valuee := rec.family;
                                    ELSE -- tsever, bohir
                                        IF rec.pure_water AND rec.plcode = '18' THEN 
                                            is_insert = True;
                                        END IF;	
                                        IF rec.impure_water AND rec.plcode = '36' THEN 
                                            is_insert = True;
                                        END IF;	
                                        amount := rec.family * rec.price;
                                        noat := amount * 0.1;
                                        total_amount := amount + noat;
										total_amount := round(total_amount::numeric, 2);
                                        days := 30;
                                        valuee := rec.family;
                                        une := rec.price;
                                    END IF;			
                                    IF is_insert AND amount>0 THEN
                                        INSERT INTO public.pay_receipt_address_line(
                                            service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                            usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount, 
                                            apartment_id, inspector_id, pricelist_days)
                                        VALUES (
                                            rec.service_type_id, rec.name, amount, amount, rec.pricelist_id, rec.uom_id, days, userid, now(), 
                                            valuee, 100, une, noat, null, rec.address_id, total_amount, 
                                            rec.apartment_id, rec.inspector_id, rec.pricelist_days);
                                    END IF;
                                END LOOP;
                        -- Hereglegchiin uilchilgee bodoh
                        -- SELECT * FROM ref_address
                                FOR rec IN (
                                    SELECT --* 
                                        sa.id, sa.address_id, sa.service_type_id, sa.value, sa.percent, sa.is_noat, sa.pricelist_id, sa.day,
                                        rst.name, pl.price, pl.uom_id, pl.code plcode, pl.days pricelist_days,
                                        ra.pure_water, ra.impure_water, ra.heating, ra.heating_water_fee, ra.proof, ra.mineral_water, 
                                        ra.apartment_id, ra.inspector_id,
                                        ras.square, ras.square_coef, ras.capacity, ras.capacity_coef, ras.gradge_square, ras.public_ownership_square
                                    FROM service_address sa
                                    INNER JOIN ref_service_type rst ON rst.id=sa.service_type_id
                                    INNER JOIN ref_pricelist pl ON pl.id=sa.pricelist_id
                                    INNER JOIN ref_address ra ON ra.id=sa.address_id and ra.type=ttype AND ra.apartment_id = ANY(ap_id)
                                    LEFT JOIN (SELECT * FROM ref_address_square WHERE state='active') ras ON ras.id=ra.id
                                    WHERE sa.company_id=tcompany_id AND ra.type=ttype AND ra.active=true AND sa.active=true AND sa.type='user_service' --LIMIT 5
                                ) LOOP
                                    is_insert = False;
                                    amount := rec.price * rec.value * rec.percent / 100 * rec.day/rec.pricelist_days;
                                    noat := 0;
                                    if rec.is_noat THEN
                                        noat := amount * 0.1;
                                    END IF;
                                    total_amount := amount + noat;
									total_amount := round(total_amount::numeric, 2);
                                    -- usnii suuri huraamj 247
                                    IF rec.plcode='53' THEN 
--                                         IF rec.pure_water THEN 
                                    	is_insert = True;
--                                         END IF;
                                    -- dulaanii suuri huraamj 248
                                    ELSIF rec.plcode='65' OR rec.plcode='66' OR rec.plcode='67' THEN 
--                                         IF rec.heating THEN 
                                    	is_insert = True;
--                                         END IF;
                                        
                                    -- engiin bodolt hiideg uilchilgeenuud
                                    -- us, dulaanii suuri-aas busad uilchilgee
                                    -- GRAJ halaalt bodoh 259
                                    -- Niitiin ezemshil tulbur bodoh 260
                                    ELSE
                                        is_insert = True;
                                    END IF;
                                    
                                    IF is_insert and amount>0 THEN
                                        INSERT INTO public.pay_receipt_address_line(
                                            service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                            usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount,
                                            apartment_id, inspector_id, pricelist_days)
                                        VALUES (
                                            rec.service_type_id, rec.name, amount, amount, rec.pricelist_id, rec.uom_id, rec.day, userid, now(), 
                                            rec.value, rec.percent, rec.price, noat, null, rec.address_id, total_amount,
                                            rec.apartment_id, rec.inspector_id, rec.pricelist_days);
                                    END IF;
                        
                                END LOOP;
                        
                        -- nemelt uilchilgee bodoh
                                FOR rec IN (
                                    SELECT --* 
                                        sa.id, sa.address_id, sa.service_type_id, sa.value, sa.percent, sa.is_noat, sa.pricelist_id, sa.day,
                                        rst.name, -- pl.price, pl.uom_id,
                                        ra.apartment_id, ra.inspector_id,
                                        sa.price
                                    FROM service_address sa
                                    INNER JOIN ref_service_type rst ON rst.id=sa.service_type_id
                        --  			INNER JOIN ref_pricelist pl ON pl.id=sa.pricelist_id
                                    INNER JOIN ref_address ra ON ra.id=sa.address_id AND ra.apartment_id = ANY(ap_id)
                                    WHERE sa.company_id=tcompany_id AND ra.type=ttype AND ra.active=true 
                                        AND sa.active=true AND sa.type='additional_service' AND sa.year=line_year AND sa.month=line_month --LIMIT 5
                                ) LOOP
                                    amount := rec.price * rec.value * rec.percent / 100;
                                    noat := 0;
                                    if rec.is_noat THEN
                                        noat := amount * 0.1;
                                    END IF;
                                    total_amount := amount + noat;			
									total_amount := round(total_amount::numeric, 2);
                                    days := 30;
                                    IF amount>0 THEN
                                        INSERT INTO public.pay_receipt_address_line(
                                            service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                            usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount, 
                                            apartment_id, inspector_id, pricelist_days)
                                        VALUES (
                                            rec.service_type_id, rec.name, amount, amount, rec.pricelist_id, null, days, userid, now(), 
                                            rec.value, rec.percent, rec.price, noat, null, rec.address_id, total_amount,
                                            rec.apartment_id, rec.inspector_id, 30);
                                    END IF;
                        
                                END LOOP;
                        
                        -- tolbort uilchilgee bodoh
                                FOR rec IN (
                                    SELECT -- *
                                        sp.address_id, sp.service_type_id, sp.work_name, sp.total_amount,
                                        ra.apartment_id, ra.inspector_id
                                    FROM service_payment sp
                                    INNER JOIN ref_address ra ON ra.id=sp.address_id AND ra.company_id=tcompany_id 
                                        AND ra.type=ttype AND ra.active=true AND sp.active=true
                                        AND sp.year=line_year AND sp.month=line_month AND ra.apartment_id = ANY(ap_id)
                                ) LOOP
                                    amount := rec.total_amount;
                                    noat := amount * 0.1;
                                    total_amount := amount + noat;
									total_amount := round(total_amount::numeric, 2);
                                    days := 30;
                                    valuee := 1;
                                    
                                    IF amount>0 THEN
                                        INSERT INTO public.pay_receipt_address_line(
                                            service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                            usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount,
                                            apartment_id, inspector_id, pricelist_days)
                                        VALUES (
                                            rec.service_type_id, 'Төлбөрт үйлчилгээ', amount, amount, null, null, days, userid, now(), --rec.work_name
                                            valuee, 100, rec.total_amount, noat, null, rec.address_id, total_amount, 
                                            rec.apartment_id, rec.inspector_id, 30);
                                    END IF;
                        
                                END LOOP;
                                
                        -- huiten usnii tooluurtai, haluun usnii tooluurgui ued
                        -- barimt bodoh
                            EXCEPTION
                                WHEN OTHERS THEN
                                    RAISE NOTICE 'Transaction rolled back due to an exception: % %', SQLERRM, row_number;
                            END;
                        
            
                        
$BODY$;




        """
        self.env.cr.execute(procedure)
        self.env.cr.execute("""DROP PROCEDURE if EXISTS update_pay_receipt;""")
        procedure = """
            CREATE OR REPLACE PROCEDURE public.update_pay_receipt(userid integer, line_year character, line_month character, tcompany_id integer, ttype character varying)
             LANGUAGE plpgsql
            AS $procedure$
                DECLARE 
                    rec RECORD;
                    is_insert BOOLEAN;
                    pr_row pay_receipt%rowtype;
                    pra_id INTEGER;
            
                BEGIN
                    -- 75 huvi hunii barimt, 81 baiguullagiin barimt	
                    INSERT INTO pay_receipt_address_line 
                        (address_id, service_type_id, name, amount, pricelist_id, price, uom_id, 
                         total_amount, days, usage, transition_coef, noat, create_uid, create_date, apartment_id, inspector_id)
                         
                    SELECT 
                        ra.id address_id, pl.service_type_id, 'Баримт' as name, pl.price, pl.id pricelist_id, pl.price, pl.uom_id, 
                        pl.price*0.1+pl.price total_amount, 30 days, 1 usage, 100 transition_coef, pl.price*0.1 noat,
                        userid create_uid, now() create_date, ra.apartment_id, ra.inspector_id
                    FROM ref_address ra 
                    LEFT JOIN ref_pricelist pl ON (pl.code='75' AND ra.type='OS') OR (pl.code='81' AND ra.type='AAN')
                    WHERE ra.id NOT IN (
                        SELECT pral1.address_id FROM pay_receipt_address_line pral1
                        INNER JOIN pay_receipt_address pra1 ON pra1.id=pral1.receipt_address_id
                        INNER JOIN pay_receipt pr1 ON pr1.id=pra1.receipt_id
                        INNER JOIN ref_pricelist pl1 ON pral1.pricelist_id=pl1.id AND (pl1.code='75' OR pl1.code='81')
                        WHERE pr1.year=line_year AND pr1.month=line_month AND pr1.address_type=ttype
                    ) AND ra.id IN (
                        SELECT pral1.address_id FROM pay_receipt_address_line pral1
                        INNER JOIN pay_receipt_address pra1 ON pra1.id=pral1.receipt_address_id
                        INNER JOIN pay_receipt pr1 ON pr1.id=pra1.receipt_id
                        WHERE pr1.year=line_year AND pr1.month=line_month AND pr1.address_type=ttype
                        GROUP BY pral1.address_id
                    ) 
                    AND ra.type=ttype; -- 10210645
                    
            -- 		SELECT * FROM pay_receipt_address_line
            -- 		SELECT * FROM ref_pricelist
            -- 		SELECT * FROM ref_address
                    
                    SELECT * FROM pay_receipt INTO pr_row WHERE year=line_year AND month=line_month AND state='draft' 
                        AND company_id=tcompany_id AND address_type=ttype;
            
                    IF not found THEN
                        raise notice 'Tuhain sariin bichilt oldsongui';
                    ELSE
                    
            -- 			raise notice 'Film is found %' , pr_row.id;
            -- 	SELECT * FROM ref_address LIMIT 100
            -- 	SELECT * FROM ref_apartment LIMIT 100
                        FOR rec IN (
                            SELECT nt.*, rh.id horoo_id, rh.duureg_id FROM (
                                SELECT 
                                    pral.address_id, sum(pral.amount) amount, sum(pral.noat) noat, sum(pral.total_amount) total_amount,
                                    max(ra.apartment_id) apartment_id, max(ra.inspector_id) inspector_id
                                FROM pay_receipt_address_line pral
                                INNER JOIN ref_address ra ON ra.id=pral.address_id AND ra.type=ttype AND ra.active=true AND ra.company_id = tcompany_id
                                LEFT JOIN pay_receipt_address pra ON pral.receipt_address_id=pra.id
                                WHERE receipt_address_id is null OR pra.receipt_id=pr_row.id  -- 1 test ugugdul
                                GROUP BY pral.address_id
                            ) nt 
                            LEFT JOIN ref_apartment rap ON nt.apartment_id=rap.id
                            LEFT JOIN ref_horoo rh ON rap.horoo_id=rh.id
            -- 				LEFT JOIN ref_duureg rd ON rh.duureg_id=rd.id
                            
                        ) LOOP
            -- 				SELECT nextval('pay_receipt_address_id_seq') into pra_id;
                            INSERT INTO public.pay_receipt_address(
                                address_id, amount, noat, total_amount, state, receipt_id, create_uid, create_date, inspector_id, apartment_id, horoo_id, duureg_id)
                            VALUES 
                                (rec.address_id, rec.amount, rec.noat, rec.total_amount, 'draft', pr_row.id, userid, now(), rec.inspector_id, rec.apartment_id, rec.horoo_id, rec.duureg_id)
                            ON CONFLICT(receipt_id, address_id) 
                            DO UPDATE SET
                                amount = rec.amount,
                                total_amount = rec.total_amount,
                                noat = rec.noat,
                                write_uid = userid,
                                write_date = now();
                        END LOOP;
                        
                        -- shine uusgesen pay_receipt_address-tai holboh			
                        UPDATE pay_receipt_address_line t1
                        SET receipt_address_id = pra.id
                        FROM pay_receipt_address_line pral
                            JOIN pay_receipt_address pra ON pral.receipt_address_id is null and pral.address_id=pra.address_id
                            JOIN pay_receipt pr ON pra.receipt_id=pr.id 
                        WHERE
                            t1.id = pral.id AND pr.year=line_year AND pr.month=line_month;
            -- 			FOR rec IN (
            -- 				SELECT * FROM pay_receipt_address WHERE receipt_id=pr_row.id
            -- 			) LOOP
            -- 				UPDATE pay_receipt_address_line 
            -- 				SET receipt_address_id=rec.id
            -- 				WHERE receipt_address_id is null and address_id=rec.address_id;
            -- 			END LOOP;
                        
                    END IF;
                
            
                EXCEPTION
                    WHEN OTHERS THEN
                        RAISE NOTICE 'Transaction rolled back due to an exception: %', SQLERRM;
                END;
            $procedure$;
        """
        self.env.cr.execute(procedure)
        self.env.cr.execute("""DROP PROCEDURE if EXISTS delete_pay_receipt;""")
        procedure = """
            CREATE OR REPLACE PROCEDURE public.delete_pay_receipt(line_year character varying, line_month character varying, tcompany_id integer, ttype character varying)
             LANGUAGE plpgsql
            AS $procedure$
                        DECLARE
                            rec record;
                        BEGIN
                            DELETE FROM pay_receipt_address_line 
                            WHERE receipt_address_id IN (
                                SELECT 
                                  pra.id 
                                FROM pay_receipt_address pra 
                                LEFT JOIN pay_receipt pr ON pr.id=pra.receipt_id 
                                WHERE pr.company_id=tcompany_id AND pr.address_type=ttype AND pr.year=line_year AND pr.month=line_month AND pr.state='draft'
                            );
            
                            DELETE FROM pay_receipt_address
                            WHERE receipt_id IN (
                                SELECT id FROM pay_receipt pr
                                WHERE pr.company_id=tcompany_id AND pr.address_type=ttype AND pr.year=line_year AND pr.month=line_month AND pr.state='draft'
                            );
                        EXCEPTION
                            WHEN OTHERS THEN
                                RAISE NOTICE 'Transaction rolled back due to an exception: %', SQLERRM;
                        END;
                        
            $procedure$
            ;
        """
        self.env.cr.execute(procedure)
        self.env.cr.execute("""DROP PROCEDURE if EXISTS change_days_address_line;""")
        procedure = """
            CREATE OR REPLACE PROCEDURE public.change_days_address_line(
	userid integer,
	line_year character varying,
	line_month character varying,
	tcompany_id integer,
	ttype character varying)
LANGUAGE 'plpgsql'
AS $BODY$
                            DECLARE rec RECORD;
                            DECLARE tamount FLOAT;
                            DECLARE tnoat FLOAT;
                            DECLARE ttotal_amount FLOAT;
                            DECLARE is_insert BOOLEAN;
                                tdays INTEGER;
                                valuee FLOAT;
                                uvul_tarif FLOAT;
                                une FLOAT;
                                currmonth FLOAT;
                                sar INTEGER;
                            BEGIN
                        -- honog oorchlogdson tolboruudiig dahin bodoh
                                SELECT EXTRACT(DAY FROM (DATE_TRUNC('month', TO_DATE('2023-' || line_month || '-01', 'YYYY-MM-DD')) + INTERVAL '1 month' - INTERVAL '1 day')) AS days_in_given_month INTO currmonth;
                                FOR rec IN (
                                    SELECT * FROM pay_receipt_address_line 
                                        WHERE receipt_address_id IN (
                                            SELECT 
                                            pra.id 
                                            FROM pay_receipt_address pra 
                                            LEFT JOIN pay_receipt pr ON pr.id=pra.receipt_id 
                                            WHERE pr.company_id=tcompany_id AND pr.address_type=ttype AND pr.year=line_year AND pr.month=line_month AND pr.state='draft'
                                        ) AND days_changed=true
                                ) LOOP
                                    tamount := rec.price * rec.usage * rec.transition_coef / 100 * rec.days/rec.pricelist_days;
                                    IF rec.noat>0 THEN
                                        tnoat := tamount * 0.1;
                                    ELSE
                                        tnoat := 0;
                                    END IF;
                                    ttotal_amount := tamount + tnoat;
									ttotal_amount := round(ttotal_amount::numeric, 2);
                        -- 			tdays := rec.days;
                                    UPDATE public.pay_receipt_address_line SET 
                                        amount=tamount, 
                                        days=rec.days, 
                                        write_uid=userid, 
                                        write_date=now(), 
                                        noat=tnoat, 
                                        total_amount=ttotal_amount
                                    WHERE id=rec.id;
                                END LOOP;
                                
                                CALL update_pay_receipt(userid, line_year, line_month, tcompany_id, ttype);
                            EXCEPTION
                                WHEN OTHERS THEN
                                    RAISE NOTICE 'Transaction rolled back due to an exception: %', SQLERRM;
                            END;
                        
            
                
$BODY$;
        """
        self.env.cr.execute(procedure)
        self.env.cr.execute("""DROP PROCEDURE if EXISTS update_deduction;""")
        procedure = """
            -- DROP PROCEDURE public.update_deduction(int4, int4, int4, varchar);

                CREATE OR REPLACE PROCEDURE public.update_deduction(
	userid integer,
	deduction_id integer,
	tcompany_id integer,
	ttype character varying)
LANGUAGE 'plpgsql'
AS $BODY$
                            DECLARE row_number INT;
                            DECLARE rec RECORD;
                            DECLARE sha RECORD;
                            DECLARE rashaan RECORD;
                            DECLARE amount FLOAT;
                            DECLARE noat FLOAT;
                            DECLARE total_amount FLOAT;
                            DECLARE is_insert BOOLEAN;
                                days INTEGER;
                                valuee FLOAT;
                                uvul_tarif FLOAT;
                                une FLOAT;
                                sar INTEGER;
                            BEGIN
                        		DELETE FROM pay_receipt_address_line WHERE service_deduction_group_id=deduction_id;
								FOR rec IN (SELECT --* 
										sd.id, sd.group_id, sd.service_type_id, sd.pricelist_id, sd.calc_type, sd.type, sd.description, sd.year, sd.month, sd.value, 
										ra.id address_id, ra.family, ras.square, ra.apartment_id, ra.inspector_id, pl.code plcode, pl.days pldays, pl.price plprice
									FROM public.service_deduction sd
									RIGHT JOIN ref_address_service_deduction_rel rasdr ON sd.id=rasdr.service_deduction_id
									LEFT JOIN ref_address ra ON rasdr.ref_address_id=ra.id
									LEFT JOIN ref_address_square ras ON ra.id=ras.address_id
									LEFT JOIN ref_pricelist pl ON sd.pricelist_id=pl.id
										WHERE sd.group_id=deduction_id
								) LOOP
									IF rec.calc_type='amount' THEN
										valuee := 1.0;
										amount := rec.value;
										noat := amount * 0.1;
										total_amount := amount + noat;
										days := 30;

										IF rec.type = '-' THEN
											amount := amount * -1;
											noat := noat * -1;
											total_amount := total_amount * -1;
										END IF;
                                        INSERT INTO public.pay_receipt_address_line(
                                            service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
                                            usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount,
                                            apartment_id, inspector_id, pricelist_days, service_deduction_group_id)
                                        VALUES (
                                            rec.service_type_id, rec.description, amount, amount, rec.pricelist_id, null, days, userid, now(), --rec.work_name
                                            valuee, 100, total_amount, noat, null, rec.address_id, total_amount, 
                                            rec.apartment_id, rec.inspector_id, 30, rec.group_id);
									ELSE -- honogoor
										amount := 0;
 										IF rec.plcode='26' OR rec.plcode='18' OR rec.plcode='36' THEN -- usnii tooluurgui zadgai, tsever bohir uxx
											valuee := rec.family;
											amount := rec.plprice * valuee * days/rec.pldays;
											noat := amount * 0.1;
											total_amount := amount + noat;
											days := rec.value;
 										END IF;
										IF rec.plcode='42' OR rec.plcode='46' THEN
											valuee := rec.square;
											amount := rec.plprice * valuee * days/rec.pldays;
											noat := amount * 0.1;
											total_amount := amount + noat;
											days := rec.value;
										END IF;

										IF rec.type = '-' THEN
											amount := amount * -1;
											noat := noat * -1;
											total_amount := total_amount * -1;
										END IF;
 										IF amount > 0 THEN
											INSERT INTO public.pay_receipt_address_line(
												service_type_id, name, amount, started_amount, pricelist_id, uom_id, days, create_uid, create_date,
												usage, transition_coef, price, noat, receipt_address_id, address_id, total_amount,
												apartment_id, inspector_id, pricelist_days, service_deduction_group_id)
											VALUES (
												rec.service_type_id, rec.description, amount, amount, rec.pricelist_id, null, days, userid, now(), --rec.work_name
												valuee, 100, total_amount, noat, null, rec.address_id, total_amount, 
												rec.apartment_id, rec.inspector_id, 30, rec.group_id);
 										END IF;
                                    END IF;
									
								END LOOP;
							
                            EXCEPTION
                                WHEN OTHERS THEN
                                    RAISE NOTICE 'Transaction rolled back due to an exception: % %', SQLERRM, row_number;
                            END;
                        
            
$BODY$;
        """
        self.env.cr.execute(procedure)

    def clear_invoice_difference(self):
        for obj in self:
            invoice_list = self.env['pay.receipt.address.invoice'].search(
                [('year', '=', obj.year), ('month', '=', obj.month)])
            if invoice_list:
                self.env.cr.execute(f"""
                    UPDATE pay_receipt_address_invoice invoice SET amount_total = round(cast(pra.total_amount as numeric),2), amount_tax = round(cast(pra.noat as numeric),2), amount_untaxed = round(cast(pra.amount as numeric),2), receipt_address_id = pra.id
                    FROM pay_receipt_address pra
                    inner join pay_receipt pr on pr.id = pra.receipt_id and pr.id = {obj.id}
                    WHERE pra.address_id =  invoice.address_id and pr.year = invoice.year and pr.month = invoice.month
                """)
                invoice_list.compute_residual_amount()


class PayReceiptAddress(models.Model):
    _name = 'pay.receipt.address'
    _description = 'Төлбөрийн баримт (Тоот)'
    _sql_constraints = [
        ('address_receipt_uniq', 'unique (address_id, receipt_id)', 'Тоот болон баримт давхцаж байна!'),
    ]
    # (address_id,receipt_id)
    address_id = fields.Many2one('ref.address', 'Тоот', required=True, index=False)
    address_address = fields.Char('Тоот', related="address_id.address")
    apartment_code = fields.Char('Байрны код', related="address_id.apartment_id.code")
    # horoo_id = fields.Many2one('ref.horoo', 'Хороо',  store=True,)
    horoo_id = fields.Integer('Хороо ID', index=True)
    # duureg_id = fields.Many2one('ref.duureg', 'Дүүрэг', store=True)
    duureg_id = fields.Integer('Дүүрэг', store=True, index=True)

    apartment_id = fields.Many2one('ref.apartment', 'Байр', compute="compute_apartment", index=False, store=True)
    amount = fields.Float('Үнийн дүн')
    noat = fields.Float('НӨАТ')

    total_amount = fields.Float('Нийт дүн')

    state = fields.Selection(PAY_RECEIPT_STATE, 'Төлөв', default='draft')
    receipt_id = fields.Many2one('pay.receipt', 'Төлбөрийн баримт', index=False)
    # mcode
    inspector_id = fields.Many2one('hr.employee', 'Байцаагч', index=True)
    line_ids = fields.One2many('pay.receipt.address.line', 'receipt_address_id', string='Төлбөрийн баримтын задаргаа')
    # invoice_id = fields.Many2one('account.move', 'Нэхэмжлэл')
    counter_qty = fields.Integer('Тоолуурын тоо/ширхэг')
    family = fields.Integer(string="Ам бүл")
    partner_id = fields.Many2one('res.partner', 'Partner', related="address_id.partner_id", store=False)
    address_code = fields.Char('Тоотын код', related="address_id.code")
    sms1_sent = fields.Boolean('Мессеж 1 илгээсэн', default=False)
    sms2_sent = fields.Boolean('Мессеж 2 илгээсэн', default=False)
    year = fields.Selection(get_years(), 'Он', store=True, related='receipt_id.year')
    month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Сар', store=True, related='receipt_id.month')

    def compute_apartment(self):
        for obj in self:
            obj.apartment_id = obj.address_id.apartment_id.id

    def action_get_bank_json(self):
        url = self.env["ir.config_parameter"].sudo().get_param("ub_kontor.kontor_web")
        ids = self.ids
        model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')
        if active_ids:
            active_address_ids = f"""
                SELECT address_id as address_id, receipt_id as receipt_id FROM pay_receipt_address WHERE id in {tuple(active_ids) if len(active_ids) > 1 else f"({active_ids[0]})"}
            """
            self.env.cr.execute(active_address_ids)
            active_address_ids = self.env.cr.dictfetchall()
            active_pay_receipt = list(set([pra.get('receipt_id') for pra in active_address_ids]))

            active_address_ids = [pra.get('address_id') for pra in active_address_ids]
        if len(ids) > 1:
            result = {
                'name': _('Төрийн банкны файл татах'),
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'target': 'new',
                'res_model': 'bank.statement.export.json',
                'context': {
                    'default_receipt_id': active_pay_receipt[0],
                    'default_method': 'address',
                    'default_address_ids': active_address_ids
                }
            }
        else:
            for obj in self:
                # return {
                #     "type": "ir.actions.act_url",
                #     "target": "self",
                #     "url": f"{url}/bank/bl_single/{obj.apartment_id.code}/?token=kdisoe9e93eiiwow;;830woieafj24&pay_receipt={obj.receipt_id.id}",
                # }
                result = {
                    'name': _('Төрийн банкны файл татах'),
                    'type': 'ir.actions.act_window',
                    'view_mode': 'form',
                    'target': 'new',
                    'res_model': 'bank.statement.export.json',
                    'context': {
                        'default_receipt_id': obj.receipt_id.id,
                        'default_method': 'address',
                        'default_address_ids': [obj.address_id.id]
                    }
                }
        return result

    # def post_invoice(self):
    #     for line in self:
    #         if line.state != 'invoice_created':
    #             raise UserError(_(f"{line.address_id.full_address} дээрх төлбөрийн баримт нэхэмжлэл үүссэн төлвөөс өөр төлөвт байна!"))
    #         if(line.invoice_id):
    #             line.invoice_id.action_post()
    #
    # def create_invoice(self):
    #     for line in self: ....

    def name_get(self):
        result = []
        for obj in self:
            name = f"{obj.address_id.name_get()[0][1]}"
            result.append((obj.id, name))
        return result

    @api.onchange('line_ids')
    def compute_amount(self):
        for obj in self:
            amount = 0
            noat = 0
            total_amount = 0
            for line in obj.line_ids:
                amount += line.amount or 0.0
                total_amount += line.total_amount or 0.0
                noat += line.noat or 0.0
            obj.amount = amount
            obj.noat = noat
            obj.total_amount = total_amount

    def write(self, vals):
        result = super(PayReceiptAddress, self).write(vals)
        if (vals.get('total_amount') or vals.get('amount') or vals.get('noat')):
            ids = self.ids
            invoice_ids = self.env['pay.receipt.address.invoice'].search(
                [('receipt_address_id', 'in', ids), ('payment_state', '=', 'not_paid')])
            if (invoice_ids):
                invoice_ids.write({
                    'amount_total': vals.get('total_amount'),
                    'amount_tax': vals.get('noat'),
                    'amount_untaxed': vals.get('amount'),
                })
                invoice_ids.compute_residual_amount()
            pass
        return result


class PayReceiptAddressLine(models.Model):
    _name = 'pay.receipt.address.line'
    _description = 'Төлбөрийн баримтын задаргаа'
    _rec_name = "name"
    # _sql_constraints = [
    #     ('address_receipt_uniq', 'unique (address_id, service_type_id, pricelist_id, receipt_address_id)', 'Төлбөрийн баримтын задаргаа дээр хаяг болон баримт давхцаж байна!'),
    # ]
    receipt_address_id = fields.Many2one('pay.receipt.address', 'Төлбөрийн баримт', required=False)
    # receipt_address_id = fields.Integer('Төлбөрийн баримт', index=True)
    address_id = fields.Many2one('ref.address', 'Тоот', index=False, required=True)
    address_address = fields.Char('Тоот', related="address_id.address")
    apartment_code = fields.Char('Байрны код', related="address_id.apartment_id.code")
    # apartment_id = fields.Many2one('ref.apartment', 'Байр', index=False, store=True)
    apartment_id = fields.Integer('Байр')
    # inspector_id = fields.Many2one('hr.employee', 'Ажилтан', index=False, store=True)
    inspector_id = fields.Integer('Байцаагч ID')
    service_type_id = fields.Many2one('ref.service.type', 'Үйлчилгээний төрөл')
    # service_deduction_group_id = fields.Many2one('service.deduction.group', 'Хасагдах хэрэглээ')
    service_deduction_group_id = fields.Integer('Хасагдах хэрэглээ')
    name = fields.Char("Нэр", required=False)
    # name = fields.Char("Нэр", required=True)
    amount = fields.Float('Дүн')
    pricelist_id = fields.Many2one('ref.pricelist', 'Тариф')
    pricelist_days = fields.Integer('Тариф хоног', compute="_compute_pricelist_days", store=True)
    started_amount = fields.Float('Анхны дүн')

    @api.depends('pricelist_id')
    def _compute_pricelist_days(self):
        for obj in self:
            obj.pricelist_days = obj.pricelist_id.days

    price = fields.Float('Үнэ')
    # uom_id = fields.Many2one('uom.uom', 'Хэмжих нэгж', compute="_compute_uom_id", store=True)
    uom_id = fields.Integer('Хэмжих нэгж')
    total_amount = fields.Float('Нийт дүн')
    days = fields.Integer('Хоног')
    days_changed = fields.Boolean('Хоног өөрчлөгдсөн эсэх', default=False)
    usage = fields.Float('Хэрэглээ')
    transition_coef = fields.Integer('Шилжих коэф')
    noat = fields.Float('НӨАТ')
    is_date_change = fields.Boolean('Хоног өөрчлөх эсэх', default=True)
    # company_id = fields.Many2one('res.company','ХҮТ', index=False, related="address_id.company_id", store=True)
    company_id = fields.Integer('ХҮТ ID')
    year = fields.Selection(get_years(), 'Он', store=True, related="receipt_address_id.year")
    month = fields.Selection([
        ('01', '1-р сар'),
        ('02', '2-р сар'),
        ('03', '3-р сар'),
        ('04', '4-р сар'),
        ('05', '5-р сар'),
        ('06', '6-р сар'),
        ('07', '7-р сар'),
        ('08', '8-р сар'),
        ('09', '9-р сар'),
        ('10', '10-р сар'),
        ('11', '11-р сар'),
        ('12', '12-р сар'),
    ], 'Сар', store=True, related="receipt_address_id.month")

    # Төрийн банкны JSON файлд тоолуурын заалтуудыг бүртгэж харуулах хэрэгцээ гарсан тул төлбрийн баримтын задаргаа дээр тоолуурын заалтын тоон утгыг хадгалдаг болов
    now_counter = fields.Float(string="Эхний заалт", default=0, tracking=True, readonly=True)
    last_counter = fields.Float(string="Эцсийн заалт", default=0, tracking=True, readonly=True)
    difference_counter = fields.Float(string="Зөрүү заалт", default=0.0, tracking=True,
                                      readonly=True)
    fraction_counter = fields.Float(string="Задгай заалт", default=0.0, tracking=True, readonly=True)
    timed_service_id = fields.Integer( 'Хугацаат үйлчилгээ')
    service_payment_id = fields.Integer('Төлбөрт үйлчилгээ')
    @api.onchange('amount')
    def compute_total_amount(self):
        for obj in self:
            obj.noat = obj.amount * 0.1
            obj.total_amount = obj.noat + obj.amount

    @api.depends('pricelist_id')
    def _compute_uom_id(self):
        for obj in self:
            obj.uom_id = obj.pricelist_id.uom_id.id

    def write(self, vals):
        if (vals.get('days')):
            vals['days_changed'] = True
        result = super(PayReceiptAddressLine, self).write(vals)
        return result


class PayReceiptDaysChange(models.Model):
    _name = 'pay.receipt.days.adjustments'
    receipt_id = fields.Many2one('pay.receipt', 'Төлбөл зохих', required=True)
    company_id = fields.Many2one('res.company', 'ХҮТ', related="receipt_id.company_id", store=True)

    apartment_ids = fields.Many2many('ref.apartment', string='Байр', domain="[('company_id', '=', company_id)]")
    address_ids = fields.Many2many('ref.address', string='Тоот',
                                   domain="[('apartment_id', 'in', apartment_ids),('company_id', '=', company_id)]")
    days_of_pure_water = fields.Integer(string="Цэвэр ус", default=30)
    days_of_impure_water = fields.Integer(string="Бохир ус", default=30)
    days_of_heating = fields.Integer(string="Халаалт", default=30)
    days_of_hot_water = fields.Integer('Халуун ус', default=30)
    description = fields.Text('Тайлбар')
    apartment_count = fields.Integer('Нийт сонгогдсон байр', compute="_compute_address_count", store=False)
    address_count = fields.Integer('Нийт сонгогдсон тоот', compute="_compute_address_count", store=False)
    PRICELIST_CODE = {
        'AAN': {
            'pure_water': ('23',),
            'impure_water': ('41',),
            'heating': ('46', '47', '48', '42',),
            'hot_water': ('29',),
        },
        'OS': {
            'pure_water': ('18',),
            'impure_water': ('36',),
            'heating': ('42',),  # 85 graj halaalt, 88 niitiin ezemshill
            'hot_water': ('26', '27'),
        },
    }

    def _compute_address_count(self):
        for obj in self:
            obj.apartment_count = len(obj.apartment_ids.ids)
            if (not obj.address_ids):
                obj.address_count = self.env['ref.address'].search_count(
                    [('apartment_id', 'in', obj.apartment_ids.ids)])
            else:
                obj.address_count = len(obj.address_ids.ids)

    def change_days(self):
        receipt_ids = []
        for obj in self:
            receipt_ids += [obj.receipt_id.id]
            address_type = obj.receipt_id.address_type
            domain = [('receipt_id', '=', obj.receipt_id.id)]
            if (obj.apartment_ids):
                domain += [('apartment_id', 'in', obj.apartment_ids.ids)]
            if (obj.address_ids):
                domain += [('address_id', 'in', obj.address_ids.ids)]
            receipt_address = self.env['pay.receipt.address'].search(domain)
            if len(receipt_address) == 0:
                raise UserError("Төлбөрийн баримтын мөр үүсээгүй байна")
            receipt_address = f"{tuple(receipt_address.ids)}" if len(
                receipt_address.ids) > 1 else f"({receipt_address.ids[0]})"
            pure_water_pricelist_ids = self.env['ref.pricelist'].search([  # ('address_type', '=', obj.address_type),
                ('category', '=', 'has_no_counter'),
                ('code', 'in', self.PRICELIST_CODE.get(address_type).get('pure_water'))]).ids
            if (pure_water_pricelist_ids):
                pure_water_pricelist_ids = f"{tuple(pure_water_pricelist_ids)}" if (
                        len(pure_water_pricelist_ids) > 1) else f"({pure_water_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                       UPDATE pay_receipt_address_line SET days={obj.days_of_pure_water}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                       WHERE receipt_address_id in {receipt_address} and pricelist_id in {pure_water_pricelist_ids} and is_date_change = True;
                   """)
            impure_water_pricelist_ids = self.env['ref.pricelist'].search([  # ('address_type', '=', obj.address_type),
                ('category', '=', 'has_no_counter'),
                ('code', 'in', self.PRICELIST_CODE.get(address_type).get('impure_water'))]).ids

            if (impure_water_pricelist_ids):
                impure_water_pricelist_ids = f"{tuple(impure_water_pricelist_ids)}" if (
                        len(impure_water_pricelist_ids) > 1) else f"({impure_water_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                       UPDATE pay_receipt_address_line SET days={obj.days_of_impure_water}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                       WHERE receipt_address_id in {receipt_address} and pricelist_id in {impure_water_pricelist_ids} and is_date_change = True;
                   """)

            heating_pricelist_ids = self.env['ref.pricelist'].search([  # ('address_type', '=', obj.address_type),
                ('category', '=', 'has_no_counter'),
                ('code', 'in', self.PRICELIST_CODE.get(address_type).get('heating'))]).ids
            if (heating_pricelist_ids):
                heating_pricelist_ids = f"{tuple(heating_pricelist_ids)}" if (
                        len(heating_pricelist_ids) > 1) else f"({heating_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                       UPDATE pay_receipt_address_line SET days={obj.days_of_heating}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                       WHERE receipt_address_id in {receipt_address} and pricelist_id in {heating_pricelist_ids} and is_date_change = True;
                   """)

            hot_water_pricelist_ids = self.env['ref.pricelist'].search([  # ('address_type', '=', obj.address_type),
                ('category', '=', 'has_no_counter'),
                ('code', 'in', self.PRICELIST_CODE.get(address_type).get('hot_water'))]).ids
            if (hot_water_pricelist_ids):
                hot_water_pricelist_ids = f"{tuple(hot_water_pricelist_ids)}" if (
                        len(hot_water_pricelist_ids) > 1) else f"({hot_water_pricelist_ids[0]})"
                self.env.cr.execute(f"""
                   UPDATE pay_receipt_address_line SET days={obj.days_of_hot_water}, write_date=now(), write_uid={self.env.uid}, days_changed=True
                   WHERE receipt_address_id in {receipt_address} and pricelist_id in {hot_water_pricelist_ids} and is_date_change = True;
               """)
        receipt_ids = list(set(receipt_ids))
        receipt_list = self.env['pay.receipt'].browse(receipt_ids)
        for receipt in receipt_list:
            self.env.cr.execute(
                f"""CALL change_days_address_line({self.env.uid}, '{receipt.year}', '{receipt.month}', {receipt.company_id.id}, '{receipt.address_type}');"""
            )


class AccountMove(models.Model):
    _inherit = 'account.move'

    nc_year = fields.Char(string="Он", index=True)
    nc_month = fields.Char(string="Сар", index=True)
    # is_paid = fields.Boolean(string='Төлсөн', default=False
    auto_pay = fields.Boolean('Автоматаар төлбөр төлөх', default=False)

    # receipt_address_id = fields.Many2one('pay.receipt.address', 'Конторын төлбөрийн баримт', ondelete="no action")
    receipt_address_id = fields.Integer('Конторын төлбөрийн баримт')
    posted_date = fields.Date('Posted date')

    def write(self, vals):
        if (vals.get('state') == 'posted'):
            vals['posted_date'] = str(datetime.now().date())
        return super(AccountMove, self).write(vals)


"""
    select payment.partner_id as partner_id, sum(payment.payment_amount - payment.invoice_amount_total) as residual
    from (select payment.id as payment_id, payment.amount as payment_amount, payment.partner_id as partner_id, sum(invoice.amount_total) as invoice_amount_total from (SELECT
        payment.id as payment_id,
        invoice.id AS invoice_id
    FROM account_payment payment
    JOIN account_move move ON move.id = payment.move_id
    JOIN account_move_line line ON line.move_id = move.id
    JOIN account_partial_reconcile part ON
        part.debit_move_id = line.id
        OR
        part.credit_move_id = line.id
    JOIN account_move_line counterpart_line ON
        part.debit_move_id = counterpart_line.id
        OR
        part.credit_move_id = counterpart_line.id
    JOIN account_move invoice ON invoice.id = counterpart_line.move_id
    JOIN account_account account ON account.id = line.account_id
    WHERE account.internal_type IN ('receivable', 'payable')
        AND line.id != counterpart_line.id
        AND invoice.move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund', 'out_receipt', 'in_receipt')
    GROUP BY payment.id, invoice.move_type, invoice.id) payment_related_table
    inner join account_move invoice on invoice.id = payment_related_table.invoice_id
    inner join account_payment payment on payment.id = payment_related_table.payment_id
    group by payment.id) payment
    group by payment.partner_id
"""


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    usage = fields.Float('Хэрэглээ')
    # receipt_address_line_id = fields.Many2one('pay.receipt.address.line', 'Төлбөрийн баримтын задаргаа', ondelete="no action")
    receipt_address_line_id = fields.Integer('Төлбөрийн баримтын задаргаа')


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    paid_user_type = fields.Selection(ADDRESS_TYPE, string='Төлсөн хэрэглэгчийн төрөл')
    paid_user_register = fields.Char(string="Регистер")
    email = fields.Char('Баримт хүлээн авах мэйл')


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'
    paid_user_type = fields.Selection(ADDRESS_TYPE, string='Төлсөн хэрэглэгчийн төрөл')
    paid_user_register = fields.Char(string="Регистер")
    email = fields.Char('Баримт хүлээн авах мэйл')

    def _create_payments(self):
        result = super(AccountPaymentRegister, self)._create_payments()
        result.write({
            'paid_user_type': self.paid_user_type,
            'paid_user_register': self.paid_user_register,
            'email': self.email
        })
        return result
