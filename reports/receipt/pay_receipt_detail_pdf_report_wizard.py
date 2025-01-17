from odoo import models, fields, api
from odoo.exceptions import UserError
from itertools import groupby
from operator import itemgetter
import base64
import xlsxwriter
import io


class PayReceiptDetailPdfReportWizard(models.TransientModel):
  _name = 'pay.receipt.detail.pdf.report.wizard'
  _description = 'Payment Receipt Detail Report Wizard'

  pay_receipt_id = fields.Many2one('pay.receipt', 'Баримтийн хугацаа сонгох', required=True)
  company_id = fields.Many2one('res.company', 'ХҮТ', index=True, default=lambda self: self.env.user.company_id.id)
  address_type = fields.Selection(
    [('OS', 'ОС'), ('AAN', 'ААН')],
    string='Тоотын төрөл',
    required=True,
    default=lambda self: self.env.user.access_type
  )
  filename = fields.Char(string="Filename", readonly=True)
  date = fields.Date(string='Date', default=fields.Date.today)

  def download_pdf(self):
    if not self.pay_receipt_id:
      raise UserError("The pay receipt record does not exist or has been deleted.")

    report_action = self.env.ref('ub_kontor.action_pay_receipt_detail_pdf_report', raise_if_not_found=False)
    if not report_action:
      raise UserError("The report action 'ub_kontor.action_pay_receipt_detail_pdf_report' is not defined.")

    return report_action.report_action(self.pay_receipt_id)

  def import_xls(self):
    """Generate XLS report for the pay receipt details."""
    xls_content = io.BytesIO()
    workbook = xlsxwriter.Workbook(xls_content, {'in_memory': True})
    sheet = workbook.add_worksheet()

    # Fetch report values
    data = self._get_report_values()
    header_list = data.get('header_data_list', [])
    section_1 = data.get('section_1', [])
    section_2 = data.get('section_2', {})

    # Setup the headers and populate the data
    self._setup_xls_headers(sheet, header_list, workbook)
    self._populate_xls_data(sheet, section_1, section_2, header_list, workbook)

    # Close and return the XLS content
    workbook.close()
    xls_content.seek(0)
    xlsx_data = base64.b64encode(xls_content.read()).decode('utf-8')
    self.filename = "pay_receipt_detail_report.xlsx"

    return {
      'type': 'ir.actions.act_url',
      'url': f'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{xlsx_data}',
      'target': 'new',
      'nodestroy': True,
    }

  def _setup_xls_headers(self, sheet, header_list, workbook):
    """Setup the headers for the XLS file."""
    header_format = {
      'main': workbook.add_format(
        {'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': True}),
      'static': workbook.add_format(
        {'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': True}),
      'dynamic': workbook.add_format(
        {'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': True}),
      'total': workbook.add_format(
        {'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#F5F5F5', 'border': True}),
    }

    static_headers = ['Байр', 'Өрх тоо', 'Ам бүл', 'Талбайн хэмжээ']

    # Main header and static headers
    sheet.merge_range(0, 0, 0, len(static_headers) - 1, 'Нийт', header_format['main'])
    sheet.write_row(1, 0, static_headers, header_format['static'])

    # Dynamic headers and "Дүн" column
    current_column = len(static_headers)
    for service_list in header_list:
      for service in service_list:
        service_name = service.get('service_name', 'Unnamed')
        sheet.merge_range(0, current_column, 1, current_column, service_name, header_format['dynamic'])
        current_column += 1

    sheet.merge_range(0, current_column, 1, current_column, 'Дүн', header_format['total'])

    # Adjust column widths
    column_widths = [15, 20, 20, 20] + [20] * len(header_list) + [20]
    for col_idx, width in enumerate(column_widths):
      sheet.set_column(col_idx, col_idx, width)

  def _populate_xls_data(self, sheet, section_1, section_2, header_list, workbook):
    """Populate the XLS sheet with data starting at row 3, including a 'Дүн' column."""
    totals = {'family': 0, 'address_count': 0, 'square': 0, 'total_sum': 0}
    square_format = workbook.add_format({'num_format': '0.00'})

    start_row = 2
    static_header_count = 4

    for row_idx, s1_data in enumerate(section_1, start=start_row):
      # Extract and write static data
      static_data = [s1_data.get('apartment_code', ''), s1_data.get('family', 0), s1_data.get('address_count', 0),
                     s1_data.get('square', 0)]
      sheet.write_row(row_idx, 0, static_data, square_format)

      # Calculate row total and write dynamic service data
      row_total = 0
      current_column = static_header_count

      for service_list in header_list:
        for service in service_list:
          service_id = service.get('service_id', None)
          total_amount = self._get_service_total(section_2, s1_data.get('apartment_id'), service_id)
          sheet.write(row_idx, current_column, total_amount, square_format)
          row_total += total_amount
          current_column += 1

      # Write row total
      sheet.write(row_idx, current_column, row_total, square_format)

  def _get_service_total(self, section_2, apartment_id, service_id):
    """Calculate total amount for the given apartment and service."""
    return section_2.get(apartment_id, {}).get(service_id, [{'total_amount': 0.0}])[0]['total_amount']

  def _get_report_values(self):
    """Get the report values for the selected pay receipt."""
    report_model = self.env['report.ub_kontor.template_pay_receipt_detail_pdf_report']
    return report_model._get_report_values([self.pay_receipt_id.id])


class PayReceiptDetailPdfReport(models.AbstractModel):
  _name = 'report.ub_kontor.template_pay_receipt_detail_pdf_report'
  _description = 'Payment Receipt Detail PDF Report Template'

  @api.model
  def _get_report_values(self, docids, data=None):
    if not docids:
      raise UserError("No document IDs provided.")
    if len(docids) > 1:
      raise UserError("it supports only a single pay receipt.")
    docs = self.env['pay.receipt'].browse(docids)
    address_type = docs[0].address_type if docs else ''
    company_logo = self.env.company.logo
    query = f"""
            select service_type."name" as service_name, service_type.id as service_id
            from pay_receipt_address pra 
            inner join pay_receipt_address_line pral on pral.receipt_address_id = pra.id and pra.receipt_id = {docs.id}
            inner join ref_service_type service_type on service_type.id = pral.service_type_id
            group  by service_type.id;
        """
    self.env.cr.execute(query)
    header_data_list = self.env.cr.dictfetchall()
    header_data_list = [header_data_list[i:i + 2] for i in range(0, len(header_data_list), 2)]
    query = f""" select apartment.id as apartment_id,apartment.code as apartment_code, sum(square.square) as square, 
      sum(pra.total_amount) as total_amount, sum(pra.family) as family, count(address.id) address_count from 
      pay_receipt_address pra inner join ref_address address on address.id = pra.address_id inner join ref_apartment 
      apartment on apartment.id = address.apartment_id left join ( select square.address_id as address_id, 
      sum(square.square) as square from ref_address_square square where square.state = 'active' group by 
      square.address_id ) square on square.address_id = address.id where pra.receipt_id = {docs.id}
              group by apartment.id
              order by apartment.id;
    """
    self.env.cr.execute(query)
    section_1 = self.env.cr.dictfetchall()
    query = f"""
            select service_type.id as service_id, address.apartment_id as apartment_id,
            sum(ROUND(CAST(pral.total_amount as numeric), 2)) as total_amount
            from pay_receipt_address pra 
            inner join pay_receipt_address_line pral on pral.receipt_address_id = pra.id and pra.receipt_id = {docs.id}
            inner join ref_service_type service_type on service_type.id = pral.service_type_id
            inner join ref_address address on address.id = pra.address_id
            group by address.apartment_id,service_type.id;
        """
    self.env.cr.execute(query)
    section_2 = self.env.cr.dictfetchall()
    grouped_data = {}
    for key1, group1 in groupby(section_2, key=itemgetter('apartment_id')):
      grouped_data[key1] = {}
      sub_group = list(group1)  # Convert group1 to list to use it multiple times
      for key2, group2 in groupby(sub_group, key=itemgetter('service_id')):
        grouped_data[key1][key2] = list(group2)
    section_2 = grouped_data
    return {
      'model': self._name,
      'docs': docs,
      'logo_data_uri': self.image_data_uri(company_logo),
      'address_type': self.get_address_type_display(address_type),
      'header_data_list': header_data_list,
      'section_1': section_1,
      'section_2': section_2
    }

  def image_data_uri(self, image):
    if not image:
      return ''
    return 'data:image/png;base64,' + image.decode('utf-8')

  def _get_detailed_results(self, docids):
    query = """
            SELECT 
                rst.id AS service_type_id, 
                uu.id AS uom_id,
                rst.name AS service_name, 
                uu.name AS uom_name, 
                rp.price AS pricelist_price, 
                rp.vat_type AS vat_type,
                ROUND(CAST(SUM(pral.amount / NULLIF(pral.price, 0)) AS NUMERIC), 2) AS qty,
                SUM(ROUND(CAST(pral.noat as numeric), 2)) AS total_vat, 
                SUM(ROUND(CAST(pral.total_amount as numeric), 2)) AS total_amount,
                pr.company_id
            FROM 
                pay_receipt pr 
            JOIN 
                pay_receipt_address pra ON pra.receipt_id = pr.id
            JOIN 
                pay_receipt_address_line pral ON pra.id = pral.receipt_address_id
            LEFT JOIN 
                ref_service_type rst ON rst.id = pral.service_type_id 
            LEFT JOIN 
                uom_uom uu ON uu.id = pral.uom_id 
            LEFT JOIN 
                ref_pricelist rp ON rp.id = pral.pricelist_id
            WHERE 
                pr.id IN %s
            GROUP BY 
                rst.id, uu.id, rp.id, pr.company_id
            ORDER BY 
                rst.name, uu.id
        """
    self.env.cr.execute(query, (tuple(docids),))
    return self.env.cr.dictfetchall()

  def _get_residual_results(self, docids):
    query = """
            SELECT 
                rst.id AS service_type_id, 
                uu.id AS uom_id,
                rst.name AS service_name, 
                uu.name AS uom_name, 
                rp.price AS pricelist_price, 
                rp.vat_type AS vat_type,
                ROUND(CAST(SUM(pral.amount / NULLIF(pral.price, 0)) AS NUMERIC), 2) AS qty, 
                SUM(ROUND(CAST(pral.noat as numeric), 2)) AS total_vat, 
                SUM(ROUND(CAST(pral.total_amount as numeric), 2)) AS total_amount,
                pr.company_id
            FROM 
                pay_receipt pr 
            JOIN 
                pay_receipt_address pra ON pra.receipt_id = pr.id
            JOIN 
                pay_receipt_address_line pral ON pra.id = pral.receipt_address_id
            LEFT JOIN 
                ref_service_type rst ON rst.id = pral.service_type_id 
            LEFT JOIN 
                uom_uom uu ON uu.id = pral.uom_id 
            LEFT JOIN 
                ref_pricelist rp ON rp.id = pral.pricelist_id
            WHERE 
                pr.id IN %s
            GROUP BY 
                rst.id, uu.id, rp.id, pr.company_id
            ORDER BY 
                rst.name, uu.id
        """
    self.env.cr.execute(query, (tuple(docids),))
    return self.env.cr.dictfetchall()

  def _get_aggregated_results(self, docids):
    # Get the detailed results to retrieve the total amount
    detailed_results = self._get_detailed_results(docids)

    # Sum the total_amount from the detailed results
    total_amount = sum(result['total_amount'] for result in detailed_results)

    pay_receipt = self.env['pay.receipt'].browse(docids[:1])
    company_id = pay_receipt.company_id.id
    address_type = pay_receipt.address_type

    if not company_id or not address_type:
      raise UserError("Company ID or address type could not be determined.")

    query = """
            SELECT 
                COUNT(DISTINCT apartment_id) AS "Нийт байр",
                COALESCE(SUM(family), 0) AS "Нийт ам бүл",
                COUNT(DISTINCT praid) AS "Нийт өрх",
                COUNT(DISTINCT CASE WHEN us_tooluur > 0 THEN praid END) AS "Усны тоолууртай",
                COUNT(DISTINCT praid) - COUNT(DISTINCT CASE WHEN us_tooluur > 0 THEN praid END) AS "Усны тоолуургүй",
                COALESCE(SUM(CASE WHEN us_tooluur > 0 THEN family ELSE 0 END), 0) AS "Ам бүл Усны тоолууртай",
                COALESCE(SUM(CASE WHEN us_tooluur = 0 THEN family ELSE 0 END), 0) AS "Ам бүл Усны тоолуургүй",
                COUNT(DISTINCT CASE WHEN dulaan_tooluur > 0 THEN praid END) AS "Дулааны тоолууртай",
                COUNT(DISTINCT praid) - COUNT(DISTINCT CASE WHEN dulaan_tooluur > 0 THEN praid END) AS "Дулааны тоолуургүй",
                %s AS "Нийт дүн"
            FROM (
                SELECT
                    max(pra.apartment_id) as apartment_id,
                    max(pra.address_id) as address_id,
                    max(pra.family) as family,
                    pra.id as praid,
                    COUNT(CASE WHEN cc.category = 'counter' THEN 1 END) AS us_tooluur,
                    COUNT(CASE WHEN cc.category = 'thermal_counter' THEN 1 END) AS dulaan_tooluur
                FROM
                    pay_receipt pr
                INNER JOIN
                    pay_receipt_address pra ON pr.id = pra.receipt_id
                INNER JOIN
                    pay_receipt_address_line pral ON pra.id = pral.receipt_address_id
                LEFT JOIN
                    ref_pricelist rpl ON pral.pricelist_id = rpl.id
                INNER JOIN
                    ref_address ra ON pra.address_id = ra.id
                LEFT JOIN 
                    counter_counter cc ON cc.address_id = ra.id
                WHERE
                    pr.company_id = %s -- hut-6
                    AND pr.address_type = %s
                    AND pr.year = %s AND pr.month = %s
                    AND ra.active = TRUE
                GROUP BY pra.id
            ) as tem 
        """

    # Get the year and month from the pay receipt
    pay_receipt = self.env['pay.receipt'].browse(docids[:1])
    company_id = pay_receipt.company_id.id
    address_type = pay_receipt.address_type
    year = pay_receipt.year
    month = pay_receipt.month

    # Now pass the `year` and `month` along with other parameters
    self.env.cr.execute(query, (total_amount, company_id, address_type, year, month))

    return self.env.cr.dictfetchall()

  def get_address_type_display(self, address_type):
    """Return the display value for the address type."""
    field = self.env['pay.receipt.detail.pdf.report.wizard']._fields['address_type']
    return dict(field.selection).get(address_type, '')
