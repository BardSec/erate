from fpdf import FPDF
from datetime import date, datetime
from io import BytesIO


class ERateReport(FPDF):
    """Base PDF class with standard header/footer."""

    def __init__(self, title='E-Rate Report', district_name=''):
        super().__init__()
        self.report_title = title
        self.district_name = district_name
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        self.set_font('Helvetica', 'B', 14)
        self.cell(0, 8, self.district_name, new_x='LMARGIN', new_y='NEXT', align='L')
        self.set_font('Helvetica', 'B', 11)
        self.cell(0, 6, self.report_title, new_x='LMARGIN', new_y='NEXT', align='L')
        self.set_font('Helvetica', '', 8)
        self.cell(0, 5, f'Generated: {datetime.now().strftime("%B %d, %Y")}',
                  new_x='LMARGIN', new_y='NEXT', align='L')
        self.line(10, self.get_y() + 2, 200, self.get_y() + 2)
        self.ln(6)

    def footer(self):
        self.set_y(-20)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_fill_color(240, 240, 240)
        self.cell(0, 8, f'  {title}', fill=True, new_x='LMARGIN', new_y='NEXT')
        self.ln(3)

    def key_value(self, key, value):
        self.set_font('Helvetica', 'B', 9)
        self.cell(60, 6, key, new_x='END')
        self.set_font('Helvetica', '', 9)
        self.cell(0, 6, str(value), new_x='LMARGIN', new_y='NEXT')

    def table_header(self, headers, widths):
        self.set_font('Helvetica', 'B', 8)
        self.set_fill_color(66, 133, 244)
        self.set_text_color(255, 255, 255)
        for header, width in zip(headers, widths):
            self.cell(width, 7, header, border=1, fill=True, align='C')
        self.ln()
        self.set_text_color(0, 0, 0)

    def table_row(self, values, widths, fill=False):
        self.set_font('Helvetica', '', 8)
        if fill:
            self.set_fill_color(245, 245, 245)
        for value, width in zip(values, widths):
            self.cell(width, 6, str(value)[:40], border=1, fill=fill, align='L')
        self.ln()


def generate_annual_summary(tenant, funding_year, form471s, c2_budget, invoices):
    """Generate Annual E-rate Summary Report PDF."""
    pdf = ERateReport(
        title=f'Annual E-Rate Summary — FY{funding_year.year}',
        district_name=tenant.name,
    )
    pdf.alias_nb_pages()
    pdf.add_page()

    # District Info
    pdf.section_title('District Information')
    pdf.key_value('Funding Year:', str(funding_year.year))
    pdf.key_value('Discount Rate:', f'{funding_year.discount_rate}%')
    pdf.key_value('NSLP Percentage:', f'{funding_year.nslp_percentage}%')
    pdf.key_value('Total Enrollment:', str(funding_year.total_enrollment or 'N/A'))
    pdf.key_value('Urban/Rural:', funding_year.urban_rural or 'N/A')
    pdf.ln(5)

    # FRN Summary
    pdf.section_title('Funding Requests (Form 471s)')
    total_requested = sum(f.amount_requested or 0 for f in form471s)
    total_committed = sum(f.amount_committed or 0 for f in form471s)
    pdf.key_value('Total FRNs:', str(len(form471s)))
    pdf.key_value('Total Requested:', f'${total_requested:,.2f}')
    pdf.key_value('Total Committed:', f'${total_committed:,.2f}')
    pdf.ln(3)

    if form471s:
        headers = ['FRN', 'Category', 'Vendor', 'Requested', 'Committed', 'Status']
        widths = [30, 15, 45, 30, 30, 25]
        pdf.table_header(headers, widths)
        for i, f in enumerate(form471s):
            vendor_name = f.vendor.name if f.vendor else 'N/A'
            pdf.table_row([
                f.frn or 'N/A',
                f.category or '',
                vendor_name,
                f'${f.amount_requested or 0:,.2f}',
                f'${f.amount_committed or 0:,.2f}',
                f.status or '',
            ], widths, fill=(i % 2 == 0))
    pdf.ln(5)

    # C2 Budget
    if c2_budget:
        pdf.section_title('Category 2 Budget Status')
        pdf.key_value('Budget Cycle:', f'{c2_budget.cycle_start_year}–{c2_budget.cycle_end_year}')
        pdf.key_value('Total Budget:', f'${c2_budget.calculated_budget or 0:,.2f}')
        pdf.key_value('Spent to Date:', f'${c2_budget.spent_to_date or 0:,.2f}')
        pdf.key_value('Remaining:', f'${c2_budget.amount_remaining:,.2f}')
        pdf.key_value('Utilization:', f'{c2_budget.percent_used}%')
        pdf.ln(5)

    # Invoices
    if invoices:
        pdf.section_title('Invoices')
        total_claimed = sum(i.amount_claimed or 0 for i in invoices)
        total_reimbursed = sum(i.amount_reimbursed or 0 for i in invoices)
        pdf.key_value('Total Claimed:', f'${total_claimed:,.2f}')
        pdf.key_value('Total Reimbursed:', f'${total_reimbursed:,.2f}')
        pdf.ln(3)
        headers = ['FRN', 'Type', 'Submitted', 'Claimed', 'Reimbursed', 'Status']
        widths = [30, 20, 25, 30, 30, 25]
        pdf.table_header(headers, widths)
        for i, inv in enumerate(invoices):
            frn = inv.form471.frn if inv.form471 else 'N/A'
            pdf.table_row([
                frn,
                inv.invoice_type or '',
                str(inv.submitted_date or ''),
                f'${inv.amount_claimed or 0:,.2f}',
                f'${inv.amount_reimbursed or 0:,.2f}',
                inv.status or '',
            ], widths, fill=(i % 2 == 0))

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


def generate_deadline_report(tenant, events):
    """Generate Deadline Calendar Export PDF."""
    pdf = ERateReport(title='Deadline Calendar', district_name=tenant.name)
    pdf.alias_nb_pages()
    pdf.add_page()

    headers = ['Due Date', 'Title', 'Type', 'Status']
    widths = [30, 80, 30, 30]
    pdf.table_header(headers, widths)
    for i, evt in enumerate(events):
        status = 'Complete' if evt.is_complete else 'Pending'
        pdf.table_row([
            str(evt.due_date),
            evt.title,
            evt.event_type,
            status,
        ], widths, fill=(i % 2 == 0))

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


def generate_document_inventory(tenant, documents):
    """Generate Document Inventory Report PDF."""
    pdf = ERateReport(title='Document Inventory', district_name=tenant.name)
    pdf.alias_nb_pages()
    pdf.add_page()

    headers = ['Filename', 'Category', 'FY', 'Uploaded', 'Size']
    widths = [65, 30, 15, 30, 25]
    pdf.table_header(headers, widths)
    for i, doc in enumerate(documents):
        size = f'{(doc.file_size or 0) / 1024:.1f} KB' if doc.file_size else 'N/A'
        pdf.table_row([
            doc.original_filename,
            doc.category or 'other',
            str(doc.funding_year or ''),
            str(doc.uploaded_at.strftime('%Y-%m-%d') if doc.uploaded_at else ''),
            size,
        ], widths, fill=(i % 2 == 0))

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


def generate_vendor_summary(tenant, vendors, contracts):
    """Generate Vendor/Contract Summary PDF."""
    pdf = ERateReport(title='Vendor & Contract Summary', district_name=tenant.name)
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.section_title('Vendors')
    headers = ['Name', 'SPIN', 'Contact', 'Email', 'Services']
    widths = [40, 25, 35, 45, 30]
    pdf.table_header(headers, widths)
    for i, v in enumerate(vendors):
        services = ', '.join(v.service_types) if v.service_types else ''
        pdf.table_row([
            v.name,
            v.spin_number or '',
            v.contact_name or '',
            v.contact_email or '',
            services,
        ], widths, fill=(i % 2 == 0))
    pdf.ln(5)

    pdf.section_title('Contracts')
    headers = ['Vendor', 'Start', 'End', 'Auto-Renew', 'Description']
    widths = [35, 25, 25, 20, 70]
    pdf.table_header(headers, widths)
    for i, c in enumerate(contracts):
        vendor_name = c.vendor_rel.name if c.vendor_rel else 'N/A'
        pdf.table_row([
            vendor_name,
            str(c.start_date or ''),
            str(c.end_date or ''),
            'Yes' if c.auto_renews else 'No',
            (c.description or '')[:50],
        ], widths, fill=(i % 2 == 0))

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf
