"""Generate the living technical/research PDF from its reviewed Markdown source."""

from html import escape
from pathlib import Path
import re
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_DOCS = Path(__file__).resolve().parents[1] / 'docs'
if (REPOSITORY_DOCS / 'SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md').exists():
    ROOT = REPOSITORY_DOCS
SOURCE = ROOT / 'SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.md'
OUTPUT = ROOT / 'SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.pdf'
TEMP_OUTPUT = ROOT / 'SYSTEM_TECHNICAL_DOCUMENTATION_AND_RESEARCH_REVIEWER.pdf.tmp'
REQUIRED_MARKERS = (
    '# SYSTEM TECHNICAL DOCUMENTATION AND RESEARCH REVIEWER',
    '## 11. Complete Feature Operating Manual',
    '## 12. Role and Permission Guide',
    '## 13. Data Model and Record-Separation Guide',
    '## 16. Mandatory Living-Documentation Procedure',
    '## 17. Verification Record',
    '## 18. System Revision History',
)


def paragraph_text(value):
    value = escape(value.strip())
    value = re.sub(r'`([^`]+)`', r'<font name="Courier">\1</font>', value)
    value = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', value)
    return value


def parse_table(lines, styles):
    parsed = [[cell.strip() for cell in line.strip().strip('|').split('|')] for line in lines]
    if len(parsed) > 1 and all(re.fullmatch(r':?-{3,}:?', cell) for cell in parsed[1]):
        parsed.pop(1)
    width = 184 * mm
    columns = max(len(row) for row in parsed)
    weights = []
    for index in range(columns):
        longest = max((len(row[index]) if index < len(row) else 0 for row in parsed), default=1)
        weights.append(max(8, min(longest, 48)))
    total_weight = sum(weights)
    column_widths = [width * weight / total_weight for weight in weights]
    data = []
    for row in parsed:
        padded = row + [''] * (columns - len(row))
        data.append([Paragraph(paragraph_text(cell), styles['TableCell']) for cell in padded])
    table = Table(data, colWidths=column_widths, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A6B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), .35, colors.HexColor('#94A3B8')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return table


def build_story(markdown):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='DocumentTitle', parent=styles['Title'], fontName='Helvetica-Bold',
        fontSize=18, leading=22, textColor=colors.HexColor('#0F2347'), alignment=TA_CENTER,
        spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        name='Section', parent=styles['Heading1'], fontSize=14, leading=17,
        textColor=colors.HexColor('#1B3A6B'), spaceBefore=10, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name='Subsection', parent=styles['Heading2'], fontSize=11, leading=14,
        textColor=colors.HexColor('#2563EB'), spaceBefore=8, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name='MinorHeading', parent=styles['Heading3'], fontSize=9.5, leading=12,
        textColor=colors.HexColor('#334155'), spaceBefore=6, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name='BodyCompact', parent=styles['BodyText'], fontSize=8.5, leading=11,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name='TableCell', parent=styles['BodyText'], fontSize=6.6, leading=8,
    ))
    styles.add(ParagraphStyle(
        name='BulletCompact', parent=styles['BodyText'], fontSize=8.5, leading=11,
        leftIndent=12, firstLineIndent=-6, bulletIndent=3, spaceAfter=2,
    ))
    story, lines, index = [], markdown.splitlines(), 0
    code_lines = []
    in_code = False
    while index < len(lines):
        line = lines[index]
        if line.startswith('```'):
            if in_code:
                story.append(Preformatted('\n'.join(code_lines), ParagraphStyle(
                    'Code', fontName='Courier', fontSize=7, leading=9,
                    leftIndent=8, rightIndent=8, backColor=colors.HexColor('#F1F5F9'),
                    borderPadding=6, spaceAfter=6,
                )))
                code_lines = []
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if line.startswith('|'):
            table_lines = []
            while index < len(lines) and lines[index].startswith('|'):
                table_lines.append(lines[index])
                index += 1
            story.extend([parse_table(table_lines, styles), Spacer(1, 4*mm)])
            continue
        if line.startswith('# '):
            if story:
                story.append(PageBreak())
            story.append(Paragraph(paragraph_text(line[2:]), styles['DocumentTitle']))
        elif line.startswith('## '):
            story.append(Paragraph(paragraph_text(line[3:]), styles['Section']))
        elif line.startswith('### '):
            story.append(Paragraph(paragraph_text(line[4:]), styles['Subsection']))
        elif line.startswith('#### '):
            story.append(Paragraph(paragraph_text(line[5:]), styles['MinorHeading']))
        elif re.match(r'^-\s+', line):
            story.append(Paragraph(paragraph_text(re.sub(r'^-\s+', '', line)), styles['BulletCompact'], bulletText='•'))
        elif re.match(r'^\d+\.\s+', line):
            number, value = line.split('.', 1)
            story.append(Paragraph(paragraph_text(value), styles['BulletCompact'], bulletText=f'{number}.'))
        elif line.strip() == '---':
            story.append(Spacer(1, 2*mm))
        elif line.strip():
            story.append(Paragraph(paragraph_text(line), styles['BodyCompact']))
        else:
            story.append(Spacer(1, 1.5*mm))
        index += 1
    return story


def footer(canvas, document):
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(colors.HexColor('#64748B'))
    canvas.drawString(13*mm, 8*mm, 'ISU Cauayan Procurement Management System — Living Technical Documentation')
    canvas.drawRightString(198*mm, 8*mm, f'Page {document.page}')
    canvas.restoreState()


def main():
    markdown = SOURCE.read_text(encoding='utf-8')
    missing = [marker for marker in REQUIRED_MARKERS if marker not in markdown]
    if missing:
        raise RuntimeError(f'Documentation source is incomplete; missing: {missing}')
    document = SimpleDocTemplate(
        str(TEMP_OUTPUT), pagesize=A4, rightMargin=13*mm, leftMargin=13*mm,
        topMargin=13*mm, bottomMargin=15*mm,
        title='System Technical Documentation and Research Reviewer',
        author='ISU Cauayan Procurement Management System',
        subject='Living feature, workflow, role, database, security, operations, and revision manual',
        keywords='PPMP APP procurement system documentation workflow MariaDB Flask',
    )
    try:
        document.build(build_story(markdown), onFirstPage=footer, onLaterPages=footer)
        if not TEMP_OUTPUT.exists() or TEMP_OUTPUT.stat().st_size == 0:
            raise RuntimeError('PDF generation produced no output.')
        TEMP_OUTPUT.replace(OUTPUT)
    finally:
        if TEMP_OUTPUT.exists():
            TEMP_OUTPUT.unlink()
    print(f'Generated {OUTPUT}')


if __name__ == '__main__':
    main()
