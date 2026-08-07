"""Генерация итогового заказ-наряда (xlsx) с подставленными ценами
из проверенных сопоставлений PartMatch и LaborLine."""

from __future__ import annotations

import os

import openpyxl
from openpyxl.styles import Font

from app.models import LaborLine, PartMatch, RepairOrder, ReviewStatus


def generate_repair_order_document(repair_order: RepairOrder) -> str:
    part_matches = (
        PartMatch.query.filter_by(repair_order_id=repair_order.id)
        .filter(PartMatch.review_status == ReviewStatus.APPROVED)
        .order_by(PartMatch.id)
        .all()
    )
    labor_lines = (
        LaborLine.query.filter_by(repair_order_id=repair_order.id)
        .filter(LaborLine.review_status == ReviewStatus.APPROVED)
        .order_by(LaborLine.id)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Заказ-наряд"

    bold = Font(bold=True)

    ws.append([f"Заказ-наряд №{repair_order.id}"])
    ws["A1"].font = bold
    if repair_order.vehicle_make or repair_order.vehicle_model:
        ws.append([f"Автомобиль: {repair_order.vehicle_make or ''} {repair_order.vehicle_model or ''}".strip()])
    if repair_order.vehicle_vin:
        ws.append([f"VIN: {repair_order.vehicle_vin}"])
    if repair_order.contragent:
        ws.append([f"Контрагент: {repair_order.contragent.name}"])
    ws.append([])

    ws.append(["Запчасти"])
    ws[f"A{ws.max_row}"].font = bold
    ws.append(["Артикул (договор)", "Наименование (договор)", "Сопоставлено с", "Цена", "Уверенность"])

    parts_total = 0.0
    for match in part_matches:
        price = float(match.matched_price) if match.matched_price is not None else 0.0
        parts_total += price
        ws.append(
            [
                match.contract_article or "",
                match.contract_name or "",
                match.matched_name or "",
                price or "",
                match.confidence_level.value,
            ]
        )
    ws.append(["", "", "", "Итого запчасти:", parts_total])
    ws[f"D{ws.max_row}"].font = bold
    ws.append([])

    ws.append(["Работы"])
    ws[f"A{ws.max_row}"].font = bold
    ws.append(["Описание", "Операция", "Нормо-часы", "Ставка, ч.", "Сумма"])

    labor_total = 0.0
    for line in labor_lines:
        cost = float(line.total_cost) if line.total_cost is not None else 0.0
        labor_total += cost
        ws.append(
            [
                line.description,
                line.matched_operation_name or "",
                float(line.norm_hours) if line.norm_hours is not None else "",
                float(line.hourly_rate) if line.hourly_rate is not None else "",
                cost or "",
            ]
        )
    ws.append(["", "", "", "Итого работы:", labor_total])
    ws[f"D{ws.max_row}"].font = bold
    ws.append([])

    ws.append(["", "", "", "ИТОГО:", parts_total + labor_total])
    ws[f"D{ws.max_row}"].font = bold
    ws[f"E{ws.max_row}"].font = bold

    output_dir = os.path.dirname(repair_order.storage_path)
    output_path = os.path.join(output_dir, f"repair_order_{repair_order.id}_final.xlsx")
    wb.save(output_path)
    return output_path
