"""Генерация итогового заказ-наряда (xlsx) с подставленными ценами
из проверенных сопоставлений PartMatch."""

from __future__ import annotations

import os

import openpyxl

from app.models import PartMatch, RepairOrder, ReviewStatus


def generate_repair_order_document(repair_order: RepairOrder) -> str:
    matches = (
        PartMatch.query.filter_by(repair_order_id=repair_order.id)
        .filter(PartMatch.review_status == ReviewStatus.APPROVED)
        .order_by(PartMatch.id)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Заказ-наряд"
    ws.append(["Артикул (договор)", "Наименование (договор)", "Сопоставлено с", "Цена", "Уверенность"])

    for match in matches:
        ws.append(
            [
                match.contract_article or "",
                match.contract_name or "",
                match.matched_name or "",
                float(match.matched_price) if match.matched_price is not None else "",
                match.confidence_level.value,
            ]
        )

    output_dir = os.path.dirname(repair_order.storage_path)
    output_path = os.path.join(output_dir, f"repair_order_{repair_order.id}_final.xlsx")
    wb.save(output_path)
    return output_path
