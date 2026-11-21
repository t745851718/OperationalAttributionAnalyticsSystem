import html
import io
import os
import subprocess
from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

TITLES = {
    "overview": "异动背景与问题定义", "factors": "因子贡献率拆解", "drilldown": "细分维度下钻",
    "conclusion": "核心归因结论", "evidence": "统计检验与事件证据链",
    "whatif": "What-If 情景推演", "actions": "优先行动清单",
}
PERCENT_HEADERS = {"差异率", "贡献率", "置信度", "相关度"}


@dataclass
class Section:
    key: str
    headers: tuple = ()
    rows: tuple = ()
    paragraphs: tuple = ()

    @property
    def name(self):
        return TITLES[self.key]


def evidence_description(item):
    details = list(item.get("reasons", []))
    if item.get("strata_consistency") is not None:
        details.append(f"分层一致性 {item['strata_consistency']:.1%}")
    if item.get("difference") is not None:
        details.append(f"检验口径差 {item['difference']:+,.4g}")
    return "；".join(details)


def sections(payload):
    analysis = payload["analysis"]
    summary, spec = analysis["decomposition"], analysis["spec"]
    baseline = {"mom": "环比", "yoy": "同比", "target": "目标差"}[spec["baseline"]]
    metric_unit = summary["unit"]
    factor_names = {item["metric_id"]: item["name"] for item in summary["factors"]}
    return (
        Section("overview", ("指标", "单位", "基期口径", "基期值", "现期值", "差异额", "差异率"),
                ((summary.get("name", summary["metric_id"]), metric_unit, baseline, summary["baseline"], summary["current"],
                  summary["delta"], summary["delta_rate"]),),
                (f"现期 {' 至 '.join(summary['current_period'])}，基期 {' 至 '.join(summary['baseline_period'])}。",
                 f"数据版本 {analysis['data_version']}。")),
        Section("factors", ("驱动因子", "基期值", "现期值", "贡献额", "贡献率"),
                tuple((item["name"], item["baseline"], item["current"],
                       item["contribution"], item["contribution_rate"]) for item in summary["factors"]),
                (f"方法 {summary['method']}，守恒残差 {summary['residual']:.3g}。",)
                + (("乘法分解中的零值使用平滑处理。",) if summary.get("smoothed") else ())),
        Section("drilldown", ("切片", "基期值", "现期值", "贡献额", "贡献率"),
                tuple((" / ".join(item["dimensions"].values()), item["baseline"], item["current"],
                       item["contribution"], item["contribution_rate"])
                      for item in analysis["drilldown"]["rows"][:20])),
        Section("conclusion", paragraphs=(analysis["summary"],)),
        Section("evidence", ("证据", "状态", "效应量", "p 值", "置信度", "相关度", "说明"),
                tuple((item["statement"], {"supported": "成立", "excluded": "已排除",
                      "insufficient_data": "数据不足", "timeout": "超时", "error": "验证失败"}.get(item["status"]),
                       item.get("effect_size"), item.get("p_value"), item.get("confidence"), None,
                       evidence_description(item))
                      for item in analysis["hypotheses"]) + tuple(
                      (item["title"], "与证据一致" if item["supporting_hypotheses"] else "候选解释",
                       None, None, None, item["score"], item["impact_note"]) for item in analysis["events"]),
                tuple(f"假设 {item['hypothesis_id']} 审核 · {item['author']} · "
                      + ("已确认" if item["decision"] == "accepted" else "待复核")
                      + (f" · {item['note']}" if item["note"] else "") for item in payload.get("reviews", []))),
        Section("whatif", ("情景", "驱动参数", "点估计", "80% 下界", "80% 上界", "预期收益（元）"),
                tuple((item["name"], " / ".join(f"{factor_names.get(key, key)} {value:+.1%}" for key, value in item["changes"].items()),
                       item["estimate"], *item["interval_80"], item["expected_impact_cny"])
                      for item in payload["scenarios"]),
                ("区间基于历史弹性模型与 1,000 次重抽样。",) if payload["scenarios"] else ("尚未保存推演情景。",)),
        Section("actions", ("优先级", "行动", "责任岗位", "恢复周期（日）", "预计挽回（元）", "绑定因子"),
                tuple((item["priority"], item["action"], item["owner"], item["recovery_days"],
                       item["expected_recovery_cny"], factor_names.get(item["driver"], item["driver"])) for item in analysis["actions"]),
                () if analysis["actions"] else ("此分析范围内暂无满足量化条件的行动。",)),
    )


def display(value, header=""):
    if value is None:
        return "—"
    if header in PERCENT_HEADERS:
        return f"{value:.2%}"
    if isinstance(value, float):
        if header == "p 值":
            return f"{value:.3g}"
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def chosen_sections(payload, selected=None):
    items = sections(payload)
    return [item for item in items if selected is None or item.key in selected]


def markdown(title, payload, selected=None):
    def esc(text):
        return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")

    lines = [f"# {esc(title)}"]
    for section in chosen_sections(payload, selected):
        lines.extend(("", f"## {section.name}", "", *(esc(text) for text in section.paragraphs)))
        if section.rows:
            lines.extend(("", "| " + " | ".join(section.headers) + " |",
                          "| " + " | ".join("---" for _ in section.headers) + " |"))
            lines.extend("| " + " | ".join(esc(display(value, header))
                                           for value, header in zip(row, section.headers)) + " |"
                         for row in section.rows)
        if section.key == "evidence":
            for item in payload["analysis"]["hypotheses"]:
                lines.extend(("", f"### {esc(item['statement'])}", "", "    " + item["code"]["source"]))
    return "\n".join(lines) + "\n"


def excel(title, payload, selected=None):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for section in chosen_sections(payload, selected):
        sheet = workbook.create_sheet(section.name)
        sheet.sheet_view.showGridLines = False
        sheet.append([title])
        sheet["A1"].data_type = "s"
        sheet["A1"].font = Font(size=15, color="312E81", bold=True)
        for paragraph in section.paragraphs:
            sheet.append([paragraph])
            sheet.cell(sheet.max_row, 1).data_type = "s"
        if section.headers:
            sheet.append(section.headers)
            header = sheet.max_row
            sheet.freeze_panes = f"B{header + 1}"
            for cell in sheet[header]:
                cell.fill = PatternFill("solid", fgColor="3730A3")
                cell.font = Font(color="FFFFFF", bold=True)
            for index, dimension in enumerate(section.headers, 1):
                sheet.column_dimensions[sheet.cell(header, index).column_letter].width = (
                    38 if dimension in {"证据", "行动", "说明", "切片", "驱动参数"} else 21
                )
            for line in section.rows:
                sheet.append(line)
                for cell, label in zip(sheet[sheet.max_row], section.headers):
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                    elif isinstance(cell.value, (int, float)):
                        cell.number_format = "0.00%" if label in PERCENT_HEADERS else "#,##0.00##"
            sheet.auto_filter.ref = f"A{header}:{sheet.cell(sheet.max_row, len(section.headers)).coordinate}"
        else:
            sheet.column_dimensions["A"].width = 100
            for cells in sheet.iter_rows(min_row=2):
                cells[0].alignment = Alignment(wrap_text=True, vertical="top")
                sheet.row_dimensions[cells[0].row].height = max(26, (len(str(cells[0].value)) // 45 + 1) * 18)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _waterfall(data):
    marks = [("基期", 0, data["baseline"], "#4f46e5")]
    position = data["baseline"]
    for item in data["factors"]:
        contribution = item["contribution"]
        color = "#b91c1c" if contribution < 0 else "#047857"
        marks.append((item["name"], position, position + contribution, color))
        position += contribution
    marks.append(("现期", 0, data["current"], "#3730a3"))
    minimum = min(min(a, b) for _, a, b, _ in marks)
    maximum = max(max(a, b) for _, a, b, _ in marks)
    span = maximum - minimum or 1
    chart = []
    for label, start, end, color in marks:
        offset, width = 100 * (min(start, end) - minimum) / span, 100 * abs(end - start) / span
        chart.append(f'<div class="chart-row"><span>{html.escape(label)}</span>'
                     f'<div class="chart-track"><i style="left:{offset}%;width:{width}%;background:{color}"></i></div>'
                     f'<b>{display(end - start)}</b></div>')
    return "".join(chart)


def html_report(title, payload, selected=None):
    content = []
    for section in chosen_sections(payload, selected):
        paragraphs = "".join(f"<p>{html.escape(text)}</p>" for text in section.paragraphs)
        chart = _waterfall(payload["analysis"]["decomposition"]) if section.key == "factors" else ""
        table = ""
        if section.rows:
            headers = "".join(f"<th>{heading}</th>" for heading in section.headers)
            rows = "".join("<tr>" + "".join(f"<td>{html.escape(display(value, header))}</td>"
                           for value, header in zip(row, section.headers)) + "</tr>" for row in section.rows)
            widths = (19, 10, 9, 10, 10, 10, 32) if section.key == "evidence" else ()
            columns = "".join(f'<col style="width:{width}%">' for width in widths)
            columns = f"<colgroup>{columns}</colgroup>" if columns else ""
            table = f"<table>{columns}<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"
        content.append(f'<section id="{section.key}"><h2>{section.name}</h2>{paragraphs}{chart}{table}</section>')
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{html.escape(title)}</title>
    <style>
    @page {{size:A4;margin:16mm 15mm 17mm; @bottom-right {{content:counter(page) " / " counter(pages);
      color:#475569;font-size:9pt}}}}
    body {{margin:0;font:10pt "Noto Sans CJK SC","Hiragino Sans GB",sans-serif;color:#17233b;line-height:1.52}}
    h1 {{font-size:22pt;margin:0 0 17pt;padding-bottom:8pt;border-bottom:2pt solid #4f46e5;line-height:1.3}}
    h2 {{margin:14pt 0 5pt;font-size:12pt;color:#3730a3;break-after:avoid}}
    p {{margin:4pt 0}} table {{border-collapse:collapse;width:100%;margin:6pt 0;text-align:left}}
    th {{background:#eef2ff;color:#312e81}} th,td {{padding:4pt 5pt;border-bottom:1px solid #e2e8f0;
      overflow-wrap:anywhere;text-align:left;vertical-align:top}} tr {{break-inside:avoid}}
    #evidence:not(:first-of-type) {{break-before:page}}
    #evidence table {{table-layout:fixed;font-size:8.8pt}}
    #evidence :is(th, td):nth-child(n+3):nth-child(-n+6) {{white-space:nowrap}}
    #actions :is(th, td):nth-child(5) {{white-space:nowrap}}
    .chart-row {{display:grid;grid-template-columns:96pt 1fr 78pt;align-items:center;gap:5pt;
      margin:3pt 0;break-inside:avoid}}
    .chart-track {{height:8pt;background:#f1f5f9;position:relative}}
    .chart-track i {{position:absolute;height:100%;top:0}} .chart-row b {{text-align:right;font-size:8pt}}
    </style><body><h1>{html.escape(title)}</h1>{"".join(content)}</body></html>"""


def pdf(title, payload, selected=None):
    source = html_report(title, payload, selected)
    result = subprocess.run(
        ["docker", "run", "--pull=never", "--rm", "--network=none", "--cap-drop=ALL",
         "--security-opt=no-new-privileges", "--memory=512m", "-i",
         os.getenv("REPORT_IMAGE", "attribution-report:local")],
        input=source.encode(), capture_output=True, check=True, timeout=30,
    )
    if not result.stdout.startswith(b"%PDF-"):
        raise OSError("WeasyPrint did not produce a PDF")
    return result.stdout
