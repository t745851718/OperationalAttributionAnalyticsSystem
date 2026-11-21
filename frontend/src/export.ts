import type { Format, Report, ReportSection } from './model'

export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

function markdownTable(section: ReportSection) {
  const escape = (value: string | number) => String(value).replaceAll('|', '\\|').replaceAll('\n', '<br>')
  const row = (values: (string | number)[]) => `| ${values.map(escape).join(' | ')} |`
  return section.headers && section.rows?.length ? [row(section.headers), row(section.headers.map(() => '---')), ...section.rows.map(row)].join('\n') : ''
}

export function markdown(title: string, sections: ReportSection[]) {
  return [`# ${title}`, ...sections.map(section => [`## ${section.title}`, ...section.paragraphs.map(paragraph => {
    const [text, ...code] = paragraph.split('\n')
    return code.length ? [text, '```sql', ...code, '```'].join('\n') : text
  }), markdownTable(section)].filter(Boolean).join('\n\n'))].join('\n\n')
}

async function spreadsheet(sections: ReportSection[]) {
  const { default: ExcelJS } = await import('exceljs')
  const workbook = new ExcelJS.Workbook()
  for (const section of sections) {
    const sheet = workbook.addWorksheet(section.title.slice(0, 31))
    sheet.columns = Array.from({ length: section.headers?.length || 1 }, (_, index) => ({ width: index === 0 ? 44 : 24 }))
    if (section.headers?.length && section.rows?.length) {
      const header = sheet.addRow(section.headers)
      header.font = { bold: true, color: { argb: 'FFFFFFFF' } }
      header.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF4F46E5' } }
      for (const row of section.rows) sheet.addRow(row)
      sheet.addRow([])
    }
    for (const paragraph of section.paragraphs) {
      const cell = sheet.addRow([paragraph]).getCell(1)
      cell.alignment = { wrapText: true, vertical: 'top' }
    }
  }
  const buffer = await workbook.xlsx.writeBuffer()
  return new Blob([new Uint8Array(buffer)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
}

async function pdf(title: string, sections: ReportSection[]) {
  const [{ jsPDF }, { default: html2canvas }] = await Promise.all([import('jspdf'), import('html2canvas')])
  const documentPdf = new jsPDF({ unit: 'mm', format: 'a4' })
  const container = document.createElement('div')
  Object.assign(container.style, { position: 'absolute', left: '-1200px', top: '0', width: '710px', background: '#ffffff', color: '#1f2740', font: '15px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif' })
  document.body.append(container)
  const blocks = [{ title, paragraphs: [] }, ...sections]
  let y = 14
  try {
    for (const [index, section] of blocks.entries()) {
      const heading = document.createElement(index === 0 ? 'h1' : 'h2')
      heading.textContent = section.title
      heading.style.cssText = 'margin:0;padding:10px 0;font-size:22px;color:#302582'
      const elements: HTMLElement[] = [heading]
      for (const paragraph of section.paragraphs) {
        const element = document.createElement('p')
        element.style.cssText = 'margin:0;padding-bottom:9px;white-space:pre-wrap;overflow-wrap:anywhere'
        element.textContent = paragraph
        elements.push(element)
      }
      if ('headers' in section && section.headers && section.rows?.length) {
        const grid = [section.headers, ...section.rows]
        for (const [rowIndex, row] of grid.entries()) {
          const element = document.createElement('div')
          element.style.cssText = `display:grid;grid-template-columns:repeat(${row.length},minmax(0,1fr));background:${rowIndex === 0 ? '#ede9ff' : '#f8f8fc'};border-bottom:1px solid #e0dff0`
          for (const value of row) {
            const cell = document.createElement('span')
            cell.style.cssText = 'padding:6px 8px;overflow-wrap:anywhere'
            cell.textContent = String(value)
            element.append(cell)
          }
          elements.push(element)
        }
      }
      for (const element of elements) {
        container.replaceChildren(element)
        const canvas = await html2canvas(container, { scale: 2, logging: false })
        const height = canvas.height * 182 / canvas.width
        if (y + height > 283 && y > 14) { documentPdf.addPage(); y = 14 }
        documentPdf.addImage(canvas, 'PNG', 14, y, 182, height)
        y += height
      }
      y += 5
    }
    return documentPdf.output('blob')
  } finally { container.remove() }
}

export async function exportLocal(report: Report, format: Format, sectionIds: string[]) {
  const sections = report.sections.filter(section => sectionIds.includes(section.id))
  if (!sections.length) throw new Error('请至少选择一个章节。')
  const title = `${report.title}-v${report.version}`
  const blob = format === 'md' ? new Blob([markdown(title, sections)], { type: 'text/markdown;charset=utf-8' }) : format === 'xlsx' ? await spreadsheet(sections) : await pdf(title, sections)
  download(blob, `${title}.${format}`)
}
