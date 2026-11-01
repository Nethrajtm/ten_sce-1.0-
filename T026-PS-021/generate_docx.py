"""
generate_docx.py
Generates a complete Word (.docx) project document for T026-PS-021.
Run: py generate_docx.py
Output: design/T026_PS021_Project_Document.docx
"""

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

doc = Document()

# ── Page margins ────────────────────────────────────────────────────────────
section = doc.sections[0]
section.page_width  = Inches(8.5)
section.page_height = Inches(11)
section.left_margin   = Inches(1)
section.right_margin  = Inches(1)
section.top_margin    = Inches(1)
section.bottom_margin = Inches(1)

# ── Colour palette ──────────────────────────────────────────────────────────
NAVY   = RGBColor(0x1A, 0x37, 0x6C)
TEAL   = RGBColor(0x00, 0x7A, 0x8A)
GREEN  = RGBColor(0x1B, 0x81, 0x3E)
ORANGE = RGBColor(0xD9, 0x63, 0x00)
RED    = RGBColor(0xC0, 0x39, 0x2B)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT  = RGBColor(0xE8, 0xF4, 0xFD)
LGRAY  = RGBColor(0xF2, 0xF2, 0xF2)
DGRAY  = RGBColor(0x40, 0x40, 0x40)


# ── Helper functions ─────────────────────────────────────────────────────────

def set_cell_bg(cell, hex_color: str):
    """Set table cell background colour."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex_color)
    tcPr.append(shd)


def set_cell_borders(cell, border_color="AAAAAA", size="4"):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for side in ['top', 'left', 'bottom', 'right']:
        b = OxmlElement(f'w:{side}')
        b.set(qn('w:val'),   'single')
        b.set(qn('w:sz'),    size)
        b.set(qn('w:space'), '0')
        b.set(qn('w:color'), border_color)
        tcBorders.append(b)
    tcPr.append(tcBorders)


def heading(text, level=1, color=NAVY):
    p = doc.add_heading(text, level=level)
    p.runs[0].font.color.rgb = color
    p.runs[0].font.bold = True
    return p


def para(text, bold=False, italic=False, color=None, size=11, align=None):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.size  = Pt(size)
    r.font.bold  = bold
    r.font.italic = italic
    if color:
        r.font.color.rgb = color
    if align:
        p.alignment = align
    return p


def code_block(text):
    p = doc.add_paragraph()
    p.style = doc.styles['Normal']
    r = p.add_run(text)
    r.font.name = 'Courier New'
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x1E, 0x40, 0x0E)
    p.paragraph_format.left_indent = Inches(0.4)
    # light green bg via shading
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  'EAF4EA')
    pPr.append(shd)
    return p


def info_box(title, text, bg='E8F4FD', title_color=None):
    """Coloured info box using a 1-col table."""
    tbl = doc.add_table(rows=2, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    # title row
    tc = tbl.rows[0].cells[0]
    set_cell_bg(tc, '1A376C')
    set_cell_borders(tc, '1A376C')
    p = tc.paragraphs[0]
    r = p.add_run(f'  {title}')
    r.font.bold  = True
    r.font.color.rgb = WHITE
    r.font.size  = Pt(11)
    # body row
    tc2 = tbl.rows[1].cells[0]
    set_cell_bg(tc2, bg)
    set_cell_borders(tc2, 'AAAAAA')
    p2 = tc2.paragraphs[0]
    r2 = p2.add_run(text)
    r2.font.size = Pt(10)
    doc.add_paragraph()
    return tbl


def flow_box(label, bg_hex='007A8A', fg=WHITE):
    """Single-cell table styled as a flowchart box."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.rows[0].cells[0]
    set_cell_bg(cell, bg_hex)
    set_cell_borders(cell, bg_hex)
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(label)
    r.font.bold  = True
    r.font.color.rgb = fg
    r.font.size  = Pt(10)
    return tbl


def arrow():
    p = doc.add_paragraph('                              ▼')
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.runs[0].font.size  = Pt(14)
    p.runs[0].font.color.rgb = TEAL


def hline():
    p = doc.add_paragraph('─' * 80)
    p.runs[0].font.size  = Pt(8)
    p.runs[0].font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)


def two_col_table(headers, rows, header_bg='1A376C'):
    cols = len(headers)
    tbl  = doc.add_table(rows=1 + len(rows), cols=cols)
    tbl.style = 'Table Grid'
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    # header
    for i, h in enumerate(headers):
        cell = tbl.rows[0].cells[i]
        set_cell_bg(cell, header_bg)
        p = cell.paragraphs[0]
        r = p.add_run(h)
        r.font.bold = True
        r.font.color.rgb = WHITE
        r.font.size = Pt(10)
    # data rows
    for ri, row in enumerate(rows):
        bg = 'F2F2F2' if ri % 2 == 0 else 'FFFFFF'
        for ci, val in enumerate(row):
            cell = tbl.rows[ri + 1].cells[ci]
            set_cell_bg(cell, bg)
            p = cell.paragraphs[0]
            r = p.add_run(str(val))
            r.font.size = Pt(9)
    doc.add_paragraph()
    return tbl


# ════════════════════════════════════════════════════════════════════════════
# COVER PAGE
# ════════════════════════════════════════════════════════════════════════════

# Top colour band
tbl = doc.add_table(rows=1, cols=1)
tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
cell = tbl.rows[0].cells[0]
set_cell_bg(cell, '1A376C')
p = cell.paragraphs[0]
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('\n\n  🏠  HOME LOAN MORTGAGE ENGINE  \n\n')
r.font.size  = Pt(22)
r.font.bold  = True
r.font.color.rgb = WHITE

doc.add_paragraph()

# Sub-title
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('T026-PS-021 · Construction-Linked Disbursement Tranches & Pre-EMI')
r.font.size  = Pt(14)
r.font.bold  = True
r.font.color.rgb = TEAL

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('Complete Project Documentation')
r.font.size  = Pt(12)
r.font.italic = True
r.font.color.rgb = DGRAY

doc.add_paragraph()

# Team info box
tbl2 = doc.add_table(rows=5, cols=2)
tbl2.alignment = WD_TABLE_ALIGNMENT.CENTER
info = [
    ('Team ID',    'T026'),
    ('Member 1',   'Nethraj T M  —  1AT24CD052'),
    ('Member 2',   'Niranjan      —  1AT24CD053'),
    ('Member 3',   'Palak Raj     —  1AT24CD054'),
    ('Section',    'CSDS A  |  Language: Python 3.10+'),
]
for ri, (k, v) in enumerate(info):
    c0 = tbl2.rows[ri].cells[0]
    c1 = tbl2.rows[ri].cells[1]
    set_cell_bg(c0, '1A376C')
    set_cell_bg(c1, 'E8F4FD')
    r0 = c0.paragraphs[0].add_run(f'  {k}')
    r0.font.bold  = True
    r0.font.color.rgb = WHITE
    r0.font.size  = Pt(10)
    r1 = c1.paragraphs[0].add_run(f'  {v}')
    r1.font.size  = Pt(10)

doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('Repository: https://github.com/Nethrajtm/ten_sce-1.0-')
r.font.size  = Pt(10)
r.font.color.rgb = TEAL
r.font.underline = True

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 1. WHAT IS THIS PROJECT?
# ════════════════════════════════════════════════════════════════════════════
heading('1. What Is This Project?', 1)
para(
    'This is a mortgage-servicing backend built for a housing finance company. '
    'When someone buys an under-construction flat, they do not get the full loan at once — '
    'the bank releases money in parts ("tranches") as the builder completes each floor or stage. '
    'This system automates that entire process from loan approval to final repayment.',
    size=11
)
doc.add_paragraph()

info_box(
    '💡 Real-World Analogy',
    '  Imagine you are buying a flat worth ₹55 lakhs that is still being built.\n'
    '  The bank approves ₹44 lakhs but does not hand it all over.\n'
    '  Instead it releases ₹8.8L after the foundation, ₹8.8L after the slab,\n'
    '  ₹6.6L after brickwork, and so on. You pay only interest on what has been\n'
    '  released — not on the full ₹44L. This is "Pre-EMI". Once the flat is ready\n'
    '  and all money is released, you switch to full EMI repayment.',
    bg='FFF8E1'
)

# ── Key Facts ───
heading('Key Facts at a Glance', 2, TEAL)
two_col_table(
    ['Item', 'Detail'],
    [
        ('Language',       'Python 3.10+  (standard library only, no external APIs)'),
        ('Interface',      'Command-line (CLI) — no UI, no web server'),
        ('Arithmetic',     'Python Decimal with ROUND_HALF_UP — never float'),
        ('Business Rules', '26 rules tagged BR-01 → BR-26'),
        ('Tests',          '104 automated unit tests (46 Phase 1 + 58 Phase 2)'),
        ('Domain',         'BFSI — Housing Finance / Mortgage Servicing'),
        ('Difficulty',     'High (multi-stage state machine with financial calculations)'),
    ]
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 2. HOW THE WHOLE SYSTEM WORKS — BIG PICTURE
# ════════════════════════════════════════════════════════════════════════════
heading('2. How the Whole System Works — Big Picture', 1)
para(
    'The diagram below shows the full journey of a home loan through this system, '
    'from the moment a borrower applies to the final repayment.',
    size=11
)
doc.add_paragraph()

# Big flowchart using boxes + arrows
stages = [
    ('📋  STEP 1: Register Borrower & Property',       '007A8A'),
    ('📊  STEP 2: Sanction — Eligibility & LTV Check', '1A376C'),
    ('🏗️   STEP 3: Builder Demands + Valuer Certifies', '1B813E'),
    ('💸  STEP 4: Tranche Released (or Rejected)',      '007A8A'),
    ('📅  STEP 5: Monthly Pre-EMI Interest Billing',   '1A376C'),
    ('🔄  STEP 6: Conversion to Full EMI',              '1B813E'),
    ('💳  STEP 7: EMI Repayment + Prepayments',         '007A8A'),
    ('📄  STEP 8: Reports — Ledger, Schedule, Cert',   '1A376C'),
]
for label, bg in stages:
    flow_box(label, bg)
    arrow()

doc.add_paragraph()
para('Each step is explained in detail in the sections below.', italic=True, color=DGRAY)
doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 3. SYSTEM ARCHITECTURE
# ════════════════════════════════════════════════════════════════════════════
heading('3. System Architecture — How the Code Is Organised', 1)
para(
    'The code is split into clean layers. Each layer has one job and calls '
    'only the layer below it. This makes the code easy to test and modify.',
    size=11
)
doc.add_paragraph()

# Architecture table
tbl = doc.add_table(rows=7, cols=3)
tbl.style = 'Table Grid'
tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
arch = [
    ('Layer',        'Folder / File',               'What it does'),
    ('CLI',          'main.py',                      'Entry point. Reads arguments, loads files, calls everything else.'),
    ('Parsers',      'src/parsers/input_parser.py',  'Reads JSON input files → Python objects'),
    ('Models',       'src/models/',                  'Data classes: Borrower, Property, LoanAccount, EmiRecord …'),
    ('Rules',        'src/rules/business_rules.py',  'All 26 BR-xx validators (stateless, return pass/fail + reason)'),
    ('Calculations', 'src/calculations/',             'Pure math functions: LTV, PMT, pre-EMI accrual, rate reset …'),
    ('Engine',       'src/engine/loan_engine.py',    'Stateful event dispatcher — processes each command in order'),
    # ('Output',       'src/output/',                  'Formats and writes text reports to disk'),
]
header_done = False
for ri, (a, b, c) in enumerate(arch):
    row = tbl.rows[ri]
    bg = '1A376C' if ri == 0 else ('E8F4FD' if ri % 2 == 1 else 'F8FBFE')
    for ci, val in enumerate([a, b, c]):
        cell = row.cells[ci]
        set_cell_bg(cell, bg)
        p = cell.paragraphs[0]
        r = p.add_run(val)
        r.font.size = Pt(9)
        if ri == 0:
            r.font.bold = True
            r.font.color.rgb = WHITE

doc.add_paragraph()

# ASCII architecture diagram in code block
code_block(
"""  INPUT FILES             LAYERS                       OUTPUTS
  ─────────────           ──────────────────────────   ──────────────────
  borrowers.json  ──┐
  properties.json ──┤──► Parsers ──► Models         ──► Sanction Letter
  commands.json   ──┘       │           │
                            │        Rules            ──► Disbursement
                            │           │                 Ledger
                            └──► Calculations        ──► Amortisation
                                    │                    Schedule
                                    ▼
                               LoanEngine            ──► Interest Cert
                                    │
                                    └──► Output      ──► Event Log
"""
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 4. DATA FLOW — FROM FILES TO REPORTS
# ════════════════════════════════════════════════════════════════════════════
heading('4. Data Flow — From Input Files to Output Reports', 1)

para('There are 3 input files and 5 output files per loan. Here is exactly how data moves:', size=11)
doc.add_paragraph()

heading('4.1 Input Files', 2, TEAL)
two_col_table(
    ['File', 'Contains', 'Key Fields'],
    [
        ('borrowers.json',       'One record per borrower',         'borrower_id, name, dob, gender, income, credit_score, coapplicant'),
        ('properties.json',      'One record per property',         'property_id, agreement_value, builder_name, stages[]'),
        ('commands.json',        'Ordered list of events to process','benchmark_rate, command, date, borrower_id, loan_id …'),
    ]
)

heading('4.2 Command Types', 2, TEAL)
two_col_table(
    ['Command', 'Who sends it', 'What happens'],
    [
        ('SANCTION',          'Bank officer',    'Calculates LTV, eligibility, rate, creates LoanAccount'),
        ('OWN_CONTRIBUTION',  'Borrower',        'Records that borrower paid their share — unlocks first tranche'),
        ('STAGE_CERTIFIED',   'Valuer/Engineer', 'Records that X% of construction is complete'),
        ('DEMAND',            'Builder',         'Requests a tranche payment — checked against 5 rules before release'),
        ('BENCHMARK_CHANGE',  'RBI/Market',      'Updates the base interest rate (effective 1st of next month)'),
        ('MONTHLY_JOB',       'Scheduler',       'Bills pre-EMI interest OR converts to full EMI after moratorium'),
        ('RECORD_EMI',        'Borrower',        'Records that an EMI was paid'),
        ('PREPAYMENT_PART',   'Borrower',        'Pays extra ≥ ₹50,000 to reduce tenure or EMI'),
        ('PREPAYMENT_FULL',   'Borrower',        'Pays off entire outstanding balance — loan closed'),
    ]
)

heading('4.3 Output Files', 2, TEAL)
two_col_table(
    ['Output File', 'What it shows'],
    [
        ('{loan_id}_sanction_letter.txt',   'Approved loan amount, rate, tenure, processing fee'),
        ('{loan_id}_disbursement_ledger.txt','Every tranche: date, amount, stage, RELEASED or REJECTED + rule IDs'),
        ('{loan_id}_amortisation_schedule.txt','Pre-EMI bills + full post-conversion EMI table'),
        ('{loan_id}_interest_cert_FY{YYYY}.txt','FY-wise: pre-EMI interest, EMI interest, principal repaid'),
        ('{loan_id}_event_log.txt/.json',   'Every event with outcome, reason and applicable BR-xx IDs'),
    ]
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 5. STEP-BY-STEP WORKFLOW
# ════════════════════════════════════════════════════════════════════════════
heading('5. Step-By-Step Workflow (Detailed)', 1)

# ── Step 1: Sanction ────────────────────────────────────────────────────────
heading('Step 1: Loan Sanction', 2, GREEN)
para('When a SANCTION command is processed, the system runs these checks in order:', size=11)
doc.add_paragraph()

two_col_table(
    ['Check', 'Rule', 'Formula / Limit'],
    [
        ('LTV (Loan-to-Value)',       'BR-01', '≤₹30L → 90%  |  ₹30-75L → 80%  |  >₹75L → 75%  of agreement value'),
        ('Income Eligibility',        'BR-02', 'EMI/NMI ≤ 55% (if income ≤₹1L/mo) or 60% (if income >₹1L/mo)'),
        ('Co-applicant income',       'BR-02', 'Spouse = 100% added  |  Other = 50% added'),
        ('Maximum loan amount',       'BR-04', 'min(LTV amount, eligibility amount)'),
        ('Age-70 tenure cap',         'BR-03', 'Tenure ≤ months until primary applicant turns 70; max 360 months'),
        ('Interest Rate',             'BR-05', 'Benchmark + spread (0.5/0.9/1.4% by credit score) − 0.05% women'),
        ('Processing Fee',            'BR-08', '0.5% of sanction, clamped ₹10K–₹25K, +18% GST; split 50/50'),
        ('Sanction Validity',         'BR-09', '6 months from sanction date'),
    ]
)

info_box(
    '📌 Example Sanction Calculation',
    '  Borrower: Meera Iyer  |  Agreement Value: ₹30,00,000  |  Income: ₹60,000/mo\n'
    '  Credit Score: 750  |  Gender: Female\n\n'
    '  LTV:  ₹30L × 90% = ₹27,00,000  (exactly ₹30L → 90% bracket, BR-01)\n'
    '  Rate: 8.5% benchmark + 0.90% spread (score 725-774) − 0.05% = 9.35%\n'
    '  Max EMI: ₹60,000 × 55% = ₹33,000  → eligible loan at 9.35%, 360mo = ₹34.9L\n'
    '  Sanctioned: min(₹27L, ₹34.9L) = ₹27,00,000\n'
    '  Fee: 0.5% × ₹27L = ₹13,500  (within ₹10K-₹25K range) + GST = ₹15,930',
    bg='E8FDF0'
)

doc.add_paragraph()

# ── Step 2: Tranche Release ─────────────────────────────────────────────────
heading('Step 2: Tranche Release (Builder Demand)', 2, GREEN)
para(
    'Every time the builder asks for money (DEMAND command), the system runs '
    '5 checks in strict order — BR-26 Precedence Chain. A failure at any step '
    'stops the process immediately and logs the reason.',
    size=11
)
doc.add_paragraph()

# BR-26 flowchart
checks = [
    ('🔵  CHECK 1 — BR-09: Is sanction still valid?',        '1A376C', '❌ REJECTED — Sanction Expired'),
    ('🟢  CHECK 2 — BR-10: Has own contribution been paid?', '1B813E', '❌ REJECTED — Own Contribution Pending'),
    ('🟡  CHECK 3 — BR-12+13: Is stage cert OK & fresh?',   'B8860B', '❌ REJECTED — Cert Insufficient / Stale (>90 days)'),
    ('🔴  CHECK 4 — BR-16: Does amount fit sanction cap?',   '8B1A1A', '⚠️  PARTIAL — Only remaining amount released'),
    ('🟣  CHECK 5 — BR-24: 3 missed EMIs freeze?',          '5B2C8A', '❌ REJECTED — Delinquency Freeze'),
]

for check_label, bg, fail_label in checks:
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    c0 = tbl.rows[0].cells[0]
    c1 = tbl.rows[0].cells[1]
    set_cell_bg(c0, bg)
    set_cell_bg(c1, 'FFF0F0')
    p0 = c0.paragraphs[0]
    r0 = p0.add_run(f'  {check_label}')
    r0.font.bold  = True
    r0.font.color.rgb = WHITE
    r0.font.size  = Pt(9)
    p1 = c1.paragraphs[0]
    r1 = p1.add_run(f'  {fail_label}')
    r1.font.size  = Pt(9)
    r1.font.color.rgb = RED
    doc.add_paragraph('                    ▼  All pass?', ).runs[0].font.size = Pt(10)

flow_box('✅  TRANCHE RELEASED — Amount disbursed to builder', '1B813E')
doc.add_paragraph()

info_box(
    '📐 Release Amount Formula (BR-15)',
    '  release_amount = demand_amount − borrower_own_contribution_share\n'
    '  own_contribution_share = demand_pct × (agreement_value − sanctioned_amount) / 100\n\n'
    '  Example: Demand 20% of ₹27L = ₹5.4L. OC share = 20% × (₹30L−₹27L) = ₹0.6L\n'
    '  → Released = ₹5.4L − ₹0.6L = ₹4.8L  (borrower already paid ₹0.6L themselves)',
    bg='FFF8E1'
)

doc.add_paragraph()

# ── Step 3: Pre-EMI ─────────────────────────────────────────────────────────
heading('Step 3: Pre-EMI Interest Billing', 2, GREEN)
para(
    'During construction (moratorium period — up to 36 months), the borrower '
    'pays only interest on the money already released, NOT on the full loan.',
    size=11
)
doc.add_paragraph()

info_box(
    '🧮 Pre-EMI Formula (BR-17)',
    '  For each released tranche:\n'
    '    daily_interest = tranche_principal × (annual_rate ÷ 100) ÷ 365\n'
    '    tranche_bill   = daily_interest × actual_days_in_billing_month\n\n'
    '  Total bill = Σ (all tranche bills for that month)\n'
    '  Billed on the 5th of each month for the previous month.\n\n'
    '  Example: ₹5,40,000 tranche released Feb 10, rate 9.35%\n'
    '    daily = ₹5,40,000 × 9.35% ÷ 365 = ₹138.25/day\n'
    '    Feb bill (19 days) = ₹138.25 × 19 = ₹2,626.75',
    bg='E8F4FD'
)

doc.add_paragraph()
two_col_table(
    ['Concept', 'Value'],
    [
        ('Day-count convention', 'Actual/365 — fixed denominator even in leap years'),
        ('Bill date',            '5th of every month (for previous month)'),
        ('Moratorium ends',      'On final disbursement  OR  after 36 months — whichever is earlier'),
        ('Undisbursed at month 36', 'Lapses — cannot be availed later (BR-25)'),
    ]
)

# ── Step 4: Conversion & EMI ────────────────────────────────────────────────
heading('Step 4: Conversion to Full EMI', 2, GREEN)
para(
    'When the final tranche is released (or month 36 is reached), the loan '
    'converts from pre-EMI to full amortising EMI. The EMI is calculated on '
    'the TOTAL DISBURSED amount (not the sanctioned amount).',
    size=11
)
doc.add_paragraph()

info_box(
    '🧮 EMI Formula — PMT (BR-22)',
    '  EMI = P × r × (1+r)ⁿ ÷ ((1+r)ⁿ − 1)\n\n'
    '  Where:\n'
    '    P = total disbursed principal\n'
    '    r = annual_rate ÷ 12 ÷ 100  (monthly rate)\n'
    '    n = remaining tenure in months\n\n'
    '  Example: P=₹27L, rate=9.35%, n=353 months → EMI ≈ ₹22,674',
    bg='E8FDF0'
)

doc.add_paragraph()

# ── Step 5: Rate Reset ───────────────────────────────────────────────────────
heading('Step 5: Benchmark Rate Change & Rate Reset', 2, GREEN)
para(
    'When RBI changes the benchmark rate, the loan rate changes too. '
    'The system adjusts tenure to keep the EMI constant (BR-21).',
    size=11
)
doc.add_paragraph()

two_col_table(
    ['Situation', 'What the system does'],
    [
        ('Benchmark changes',               'New rate = new benchmark + original spread − women discount'),
        ('Effective date',                  '1st of the NEXT month after the change (even if change is on 1st)'),
        ('Normal case',                     'Keep EMI constant → recalculate tenure using: n = ⌈−log(1−r·P/EMI) / log(1+r)⌉'),
        ('New tenure > age-70 cap',         'Cannot extend tenure → recalculate EMI for maximum allowed tenure instead'),
        ('After reset',                     'Entire remaining schedule is regenerated from scratch'),
    ]
)

# ── Step 6: Prepayment ────────────────────────────────────────────────────────
heading('Step 6: Prepayments (BR-19)', 2, GREEN)
two_col_table(
    ['Type', 'Minimum', 'Charge', 'Default effect', 'Alternative'],
    [
        ('Part Prepayment',  '₹50,000',  'None (floating rate individual)', 'Reduces tenure, keeps EMI same', 'Reduce EMI on request'),
        ('Full Prepayment',  'Full outstanding', 'None',                   'Loan closed, all EMIs marked PAID', '—'),
    ]
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 6. ALL 26 BUSINESS RULES
# ════════════════════════════════════════════════════════════════════════════
heading('6. All 26 Business Rules', 1)
para('Every rule is coded as a static method in src/rules/business_rules.py.', italic=True, size=10, color=DGRAY)
doc.add_paragraph()

rules = [
    ('BR-01', 'LTV Bands',               '≤₹30L→90%  |  ₹30-75L→80%  |  >₹75L→75%  of agreement value'),
    ('BR-02', 'Income Eligibility',       'EMI/NMI ≤ 55% (NMI≤₹1L) or 60% (NMI>₹1L); co-app 100%/50%'),
    ('BR-03', 'Age-70 Tenure Cap',        'Loan must be repaid before primary applicant turns 70; max 30 yrs'),
    ('BR-04', 'Max Loan Amount',          'min(LTV-limited amount, income-eligibility amount)'),
    ('BR-05', 'Interest Rate',            'Benchmark + spread (0.5/0.9/1.4%) − 0.05% for women borrower'),
    ('BR-06', 'Sanction Approval',        'Sanction proceeds only if eligible amount > 0 and tenure valid'),
    ('BR-07', 'Loan ID Generation',       'Sequential: LN{YYYY}{NNN} — e.g. LN2024001'),
    ('BR-08', 'Processing Fee',           '0.5% of sanction, clamp ₹10K-₹25K, +18% GST; 50/50 split'),
    ('BR-09', 'Sanction Validity',        '6 months from sanction date; expired → no tranche released'),
    ('BR-10', 'Own Contribution Gate',    'First tranche blocked until OWN_CONTRIBUTION event recorded'),
    ('BR-11', 'Own Contribution Record',  'OWN_CONTRIBUTION event records date + amount paid'),
    ('BR-12', 'Stage Cert vs Demand',     'cumul_certified_pct ≥ cumul_demanded_pct + new_demand_pct'),
    ('BR-13', 'Cert Freshness (90 days)', '(release_date − cert_date).days ≤ 90; exactly 90 = fresh'),
    ('BR-14', 'Seven-Day Release',        'Release within 7 calendar days of max(demand_date, cert_date)'),
    ('BR-15', 'Release Amount Formula',   'release = demand_amount − (demand_pct × own_contribution)'),
    ('BR-16', 'Sanction Cap',             'Cumulative released cannot exceed sanctioned amount; capped release'),
    ('BR-17', 'Pre-EMI Billing',          'interest = Σ(tranche × rate/365 × days); bill on 5th monthly'),
    ('BR-18', 'Moratorium / Conversion',  'Ends at final disbursement or month 36; full EMI from next month'),
    ('BR-19', 'Prepayment',               'Min ₹50K, no charge; default reduce tenure; full prepay closes loan'),
    ('BR-20', 'Benchmark Change',         'New rate = new_bench + spread; effective 1st of next month'),
    ('BR-21', 'Rate Reset (const EMI)',   'n = ⌈−log(1−r·P/EMI)/log(1+r)⌉; if n>age-cap → recompute EMI'),
    ('BR-22', 'EMI Formula (PMT)',        'EMI = P×r×(1+r)ⁿ / ((1+r)ⁿ−1); on total disbursed'),
    ('BR-23', 'Penal Interest',           '2%/mo simple on overdue EMI after 15-day grace period'),
    ('BR-24', 'Delinquency Freeze',       '3 consecutive missed EMIs → freeze all future tranche releases'),
    ('BR-25', 'Month-36 Lapse',           'Undisbursed balance lapses; loan converts on disbursed amount'),
    ('BR-26', 'Tranche Precedence',       'Check order: BR-09 → BR-10 → BR-12/13 → BR-16 → BR-24'),
]

two_col_table(
    ['Rule ID', 'Name', 'Description'],
    rules,
    header_bg='007A8A'
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 7. EDGE CASES
# ════════════════════════════════════════════════════════════════════════════
heading('7. Edge Cases & How They Are Handled', 1)
para('All 8 required edge cases have automated tests in tests/test_phase2.py.', italic=True, size=10)
doc.add_paragraph()

two_col_table(
    ['Edge Case', 'What makes it tricky', 'How we handle it'],
    [
        ('Agreement value = ₹30L exactly',
         'Boundary of LTV band',
         '≤ check: 90% bracket applies. Test: asserting LTV=90% at exactly 30L'),
        ('Agreement value = ₹75L exactly',
         'Upper boundary of 80% band',
         '> 30L and ≤ 75L → 80%. Test confirms exactly 75L gives 80%'),
        ('Demand 20% (cert=20%), then demand 10% (no new cert)',
         'Second demand with no new certification',
         'First demand: cumul_cert(20) ≥ 0+20 ✓. Second: 20 < 20+10 → REJECTED BR-12'),
        ('Benchmark change on 1st of month',
         'Does it apply immediately or next month?',
         'Always effective 1st of NEXT month. Even if change is on 1st, current month unchanged'),
        ('Final tranche on last day of month 36',
         'Moratorium end + conversion happen simultaneously',
         'Month-36 job triggers lapse (undisbursed) and conversion (disbursed) in same run'),
        ('Prepayment on tranche release date',
         'Two events same date — order matters',
         'Commands processed in file order. Prepayment reduces principal; next pre-EMI uses reduced balance'),
        ('Rate reset extends tenure past age 70',
         'Cannot extend tenure over the cap',
         'n capped; EMI recomputed for capped tenure using PMT formula'),
        ('Sanction expires on a holiday',
         'No holiday calendar provided',
         'Statutory date used as-is; event log records expiry date clearly'),
        ('Certification exactly 90 days old',
         'Inclusive vs exclusive boundary',
         '≤ 90 check: exactly 90 days = FRESH. Test verifies cert at exactly 90 days passes'),
    ]
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 8. CODE STRUCTURE — FILE BY FILE
# ════════════════════════════════════════════════════════════════════════════
heading('8. Code Structure — File By File', 1)

code_block(
"""T026-PS-021/
│
├── main.py                         ← CLI entry point (argparse)
│
├── data/sample/
│   ├── borrowers.json              ← Sample borrower data
│   ├── properties.json             ← Sample property + stage plans
│   ├── commands.json               ← Phase 1: SANCTION commands
│   └── commands_phase2.json        ← Phase 2: Full lifecycle events
│
├── src/
│   ├── models/
│   │   ├── borrower.py             ← Borrower, CoApplicant dataclasses
│   │   ├── property.py             ← Property, StageItem dataclasses
│   │   └── loan.py                 ← LoanAccount, DisburseRecord,
│   │                                  PreEmiBill, EmiRecord, EventLog
│   │
│   ├── rules/
│   │   └── business_rules.py       ← BR-01 to BR-26 (static validators)
│   │
│   ├── calculations/
│   │   ├── eligibility.py          ← LTV, tenure, rate, eligibility
│   │   ├── fees.py                 ← Processing fee + GST
│   │   ├── sanction.py             ← process_sanction() orchestrator
│   │   ├── disbursement.py         ← check_tranche_release() — BR-26 chain
│   │   ├── pre_emi.py              ← Daily accrual, monthly billing
│   │   └── emi_schedule.py         ← PMT, generate_schedule(),
│   │                                  apply_rate_reset(), prepayment
│   │
│   ├── engine/
│   │   └── loan_engine.py          ← LoanEngine: stateful event dispatcher
│   │
│   ├── parsers/
│   │   └── input_parser.py         ← JSON → Python objects
│   │
│   └── output/
│       ├── sanction_letter.py      ← Sanction letter formatter
│       ├── report_writer.py        ← JSON + text output writer
│       └── ledger_writer.py        ← Ledger, amortisation, cert, log
│
├── tests/
│   ├── test_phase1.py              ← 46 Phase 1 unit tests
│   └── test_phase2.py              ← 58 Phase 2 unit tests
│
└── design/
    ├── design_document.md          ← Full design doc (this file → PDF)
    ├── decision_log.md             ← 17 ambiguity resolutions
    └── demo_instructions.md        ← 5-minute demo script
"""
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 9. KEY DESIGN DECISIONS
# ════════════════════════════════════════════════════════════════════════════
heading('9. Key Design Decisions', 1)

heading('Why Decimal and not float?', 2, TEAL)
para(
    'Python float uses IEEE-754 binary floating point. It cannot represent '
    '₹8,80,000.00 exactly — tiny errors accumulate over 360 EMIs, giving wrong '
    'totals. Python\'s Decimal is base-10 exact arithmetic. All money, rates and '
    'percentages in this system use Decimal(ROUND_HALF_UP).',
    size=11
)

info_box(
    '🐍 Why this matters',
    '  float:   0.1 + 0.2  =  0.30000000000000004   ← WRONG\n'
    '  Decimal: Decimal("0.1") + Decimal("0.2")  =  0.3  ← CORRECT\n\n'
    '  Over 360 EMIs, a float error of even 0.001 per month → ₹360 wrong at end.',
    bg='FFF0F0'
)

heading('Why the Event-Log Pattern?', 2, TEAL)
para(
    'Every event (demand, billing, prepayment, reset) is recorded as an immutable '
    'EventLog entry with: date, event type, outcome (RELEASED/REJECTED/BILLED), '
    'reason in plain English, and the rule IDs that applied. This means:',
    size=11
)
doc.add_paragraph()
for point in [
    '✅ The assessors can verify every decision against the rules',
    '✅ The interest certificate is generated by summing events (no recomputation)',
    '✅ Any bug can be traced to the exact event that caused it',
    '✅ The viva reviewer can query "why was this tranche rejected?" and get a precise answer',
]:
    p = doc.add_paragraph(style='List Bullet')
    r = p.add_run(point)
    r.font.size = Pt(10)

heading('Why Standard Library Only?', 2, TEAL)
para(
    'No pip install. The project runs on any Python 3.10+ machine with zero '
    'setup beyond installing Python. This makes evaluation, portability and '
    'viva demonstration simple.',
    size=11
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 10. HOW TO RUN
# ════════════════════════════════════════════════════════════════════════════
heading('10. How to Run the Project', 1)

heading('Prerequisites', 2, TEAL)
para('Python 3.10 or higher. No other installation required.', size=11)
doc.add_paragraph()

heading('Step 1: Enter the project folder', 2, TEAL)
code_block('cd "C:\\Users\\nethr\\OneDrive\\Desktop\\study\\one second\\T026-PS-021"')

heading('Step 2: Run all 104 tests', 2, TEAL)
code_block('py -m unittest tests/test_phase1.py tests/test_phase2.py -v')
para('Expected output: Ran 104 tests in ~0.04s — OK', italic=True, size=10, color=GREEN)
doc.add_paragraph()

heading('Step 3: Run Phase 1 (Sanction Letters)', 2, TEAL)
code_block(
    'py main.py \\\n'
    '  --borrowers  data/sample/borrowers.json \\\n'
    '  --properties data/sample/properties.json \\\n'
    '  --commands   data/sample/commands.json \\\n'
    '  --output     output_files/'
)

heading('Step 4: Run Phase 2 (Full Lifecycle + FY Certificate)', 2, TEAL)
code_block(
    'py main.py \\\n'
    '  --borrowers  data/sample/borrowers.json \\\n'
    '  --properties data/sample/properties.json \\\n'
    '  --commands   data/sample/commands_phase2.json \\\n'
    '  --output     output_files/ \\\n'
    '  --fy-year    2024'
)

heading('Step 5: View Outputs', 2, TEAL)
code_block(
    '# Disbursement Ledger\n'
    'type output_files\\LN2024001_disbursement_ledger.txt\n\n'
    '# Amortisation Schedule\n'
    'type output_files\\LN2024001_amortisation_schedule.txt\n\n'
    '# Interest Certificate\n'
    'type output_files\\LN2024001_interest_cert_FY2024.txt\n\n'
    '# Event Log\n'
    'type output_files\\LN2024001_event_log.txt'
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 11. TEST COVERAGE
# ════════════════════════════════════════════════════════════════════════════
heading('11. Test Coverage Summary', 1)
para('Total: 104 tests — all pass.', bold=True, size=12, color=GREEN)
doc.add_paragraph()

two_col_table(
    ['Test Class', 'Tests', 'What is tested'],
    [
        ('TestLTVCalculation',      '5',  'BR-01: all three LTV bands + both boundaries (₹30L, ₹75L)'),
        ('TestEligibility',         '6',  'BR-02: income caps, co-applicant spouse vs other, combined NMI'),
        ('TestRateCalculation',     '4',  'BR-05: all three credit score bands + women discount'),
        ('TestTenureCap',           '3',  'BR-03: age-70 cap, max 360 months, minimum of both'),
        ('TestProcessingFee',       '4',  'BR-08: min clamp, max clamp, normal, GST'),
        ('TestSanctionProcess',     '10', 'Full sanction, insufficient income, LTV-limited, tenure-capped'),
        ('TestBusinessRules',       '8',  'Individual BR validators for BR-09 to BR-16'),
        ('TestParsers',             '6',  'JSON parsing, malformed input, missing fields'),
        ('TestPreEmiAccrual',       '6',  'BR-17: daily rate, multi-tranche, boundary months'),
        ('TestEmiSchedule',         '8',  'BR-22: PMT formula, schedule generation, amortisation identity'),
        ('TestRateReset',           '5',  'BR-21: constant EMI, age-cap override, benchmark on 1st'),
        ('TestPrepayment',          '6',  'BR-19: part (reduce tenure/EMI), full, during pre-EMI'),
        ('TestTrancheRelease',      '10', 'BR-26: all 5 checks, partial release, 90-day boundary'),
        ('TestEdgeCases',           '8',  'All 8 specified edge cases'),
        ('TestDelinquency',         '5',  'BR-23/24: grace period, penal calc, 3-missed freeze'),
        ('TestIntegration',         '10', 'Full lifecycle, cert totals, event log audit trail'),
    ]
)

doc.add_page_break()

# ════════════════════════════════════════════════════════════════════════════
# 12. GLOSSARY
# ════════════════════════════════════════════════════════════════════════════
heading('12. Glossary', 1)
two_col_table(
    ['Term', 'Meaning'],
    [
        ('Tranche',        'A portion of the loan released at one time as construction progresses'),
        ('Pre-EMI',        'Interest-only payment during moratorium (before full EMI begins)'),
        ('Moratorium',     'The construction period; up to 36 months; only interest is charged'),
        ('LTV',            'Loan-To-Value ratio — limits how much % of property value can be loaned'),
        ('EMI',            'Equated Monthly Instalment — fixed monthly repayment (principal + interest)'),
        ('Benchmark Rate', 'Base interest rate set by RBI/market (e.g. repo rate)'),
        ('Spread',         'Additional % added to benchmark based on borrower\'s credit score'),
        ('CIBIL / Credit Score', 'A score 300–900 measuring borrower creditworthiness'),
        ('NMI',            'Net Monthly Income — take-home salary after deductions'),
        ('PMT',            'Payment function: calculates fixed EMI for given principal, rate, tenure'),
        ('ACT/365',        'Day-count convention: actual days elapsed / 365'),
        ('FY',             'Financial Year (India: April 1 – March 31)'),
        ('Delinquency',    'State of being overdue on loan payments'),
        ('Penal Interest', 'Extra interest charged on overdue amounts as a penalty'),
    ]
)

doc.add_paragraph()
hline()
doc.add_paragraph()

# Footer note
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('T026-PS-021  ·  Team T026  ·  CSDS A  ·  10 SECONDS Capstone 2024')
r.font.size  = Pt(9)
r.font.italic = True
r.font.color.rgb = DGRAY

p2 = doc.add_paragraph()
p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
r2 = p2.add_run('GitHub: https://github.com/Nethrajtm/ten_sce-1.0-')
r2.font.size  = Pt(9)
r2.font.color.rgb = TEAL
r2.font.underline = True

# ── Save ─────────────────────────────────────────────────────────────────────
output_path = r"c:\Users\nethr\OneDrive\Desktop\study\one second\T026-PS-021\design\T026_PS021_Project_Document.docx"
doc.save(output_path)
print(f"[OK]  Saved: {output_path}")
