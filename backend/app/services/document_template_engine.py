from __future__ import annotations

import re
from copy import copy

import openpyxl
from openpyxl.styles import Font

TOKEN_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
FULL_TOKEN_RE = re.compile(r"^\{\{\s*([\w.]+)\s*\}\}$")
LEFTOVER_TOKEN_RE = re.compile(r"\{\{[^{}]*\}\}")


class DocumentTemplateError(RuntimeError):
    pass


def _substitute_cell(cell, values: dict) -> None:
    text = cell.value
    full_match = FULL_TOKEN_RE.match(text)
    if full_match:
        cell.value = values.get(full_match.group(1))
        return

    def repl(m: re.Match) -> str:
        value = values.get(m.group(1))
        return "" if value is None else str(value)

    cell.value = TOKEN_RE.sub(repl, text)


def _find_row(ws, prefix: str) -> int | None:
    marker = "{{" + prefix + "."
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and marker in cell.value:
                return cell.row
    return None


def _copy_row(ws, src_row: int, dst_row: int) -> None:
    for col in range(1, ws.max_column + 1):
        src = ws.cell(row=src_row, column=col)
        dst = ws.cell(row=dst_row, column=col)
        dst.value = src.value
        dst.font = copy(src.font)
        dst.border = copy(src.border)
        dst.fill = copy(src.fill)
        dst.number_format = src.number_format
        dst.alignment = copy(src.alignment)


def _expand_rows(ws, prefix: str, items: list[dict]) -> None:
    template_row = _find_row(ws, prefix)
    if template_row is None:
        return
    if not items:
        ws.delete_rows(template_row, 1)
        return

    extra = len(items) - 1
    if extra > 0:
        ws.insert_rows(template_row + 1, extra)
        for i in range(extra):
            _copy_row(ws, template_row, template_row + 1 + i)

    for i, item in enumerate(items):
        row_idx = template_row + i
        values = {f"{prefix}.{k}": v for k, v in item.items()}
        values[f"{prefix}.n"] = i + 1
        for col in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col)
            if isinstance(cell.value, str):
                _substitute_cell(cell, values)


def render_template(
    template_path: str,
    output_path: str,
    context: dict,
    part_items: list[dict],
    labor_items: list[dict],
) -> tuple[str, list[str]]:
    try:
        wb = openpyxl.load_workbook(template_path)
    except Exception as exc:
        raise DocumentTemplateError(f"Не удалось открыть файл шаблона: {exc}") from exc

    ws = wb.active
    _expand_rows(ws, "part", part_items)
    _expand_rows(ws, "labor", labor_items)

    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and "{{" in cell.value:
                _substitute_cell(cell, context)

    unresolved = set()
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                unresolved.update(LEFTOVER_TOKEN_RE.findall(cell.value))

    wb.save(output_path)
    return output_path, sorted(unresolved)


def build_starter_template(output_path: str) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Заказ-наряд"
    bold = Font(bold=True)

    def row(*values):
        ws.append(list(values))

    row("{{company_name}}")
    ws["A1"].font = bold
    row("ИНН {{company_inn}}   Адрес: {{company_address}}   Тел: {{company_phone}}")
    row()
    row("Заказ-наряд № {{order_number}} от {{order_date}}")
    row()
    row("Заказчик: {{client_name}}")
    row("Автомобиль: {{vehicle_make}} {{vehicle_model}}   VIN: {{vehicle_vin}}   {{vehicle_year}} г.")
    row()

    row("Выполненные работы")
    ws[f"A{ws.max_row}"].font = bold
    row("№", "Работа", "Норма, ч", "Цена н/ч", "Сумма")
    row("{{labor.n}}", "{{labor.description}}", "{{labor.norm_hours}}", "{{labor.hourly_rate}}", "{{labor.total}}")
    row()
    row("", "", "", "Итого работы:", "{{labor_total}}")
    ws[f"D{ws.max_row}"].font = bold
    row()

    row("Запчасти и материалы")
    ws[f"A{ws.max_row}"].font = bold
    row("№", "Артикул", "№ кат.", "Наименование", "Производитель", "Ед.", "Цена", "Склад")
    row(
        "{{part.n}}",
        "{{part.article}}",
        "{{part.cat_number}}",
        "{{part.name}}",
        "{{part.manufacturer}}",
        "{{part.unit}}",
        "{{part.price}}",
        "{{part.warehouse}}",
    )
    row()
    row("", "", "", "", "", "", "Итого запчасти:", "{{parts_total}}")
    ws[f"G{ws.max_row}"].font = bold
    row()

    row("", "", "", "", "", "", "ИТОГО:", "{{grand_total}}")
    ws[f"G{ws.max_row}"].font = bold
    ws[f"H{ws.max_row}"].font = bold

    for col_letter, width in {"A": 14, "B": 22, "C": 14, "D": 30, "E": 20, "F": 10, "G": 16, "H": 14}.items():
        ws.column_dimensions[col_letter].width = width

    wb.save(output_path)
    return output_path
