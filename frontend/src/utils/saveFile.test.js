import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveFile, XLSX_FILE_TYPES, CSV_FILE_TYPES } from "./saveFile.js";

describe("saveFile", () => {
  afterEach(() => {
    delete window.pywebview;
    vi.restoreAllMocks();
  });

  describe("вне окна приложения (window.pywebview отсутствует)", () => {
    beforeEach(() => {
      window.URL.createObjectURL = vi.fn(() => "blob:fake-url");
      window.URL.revokeObjectURL = vi.fn();
    });

    it("скачивает через обычный <a download> и сообщает native: false", async () => {
      const clickSpy = vi.fn();
      const anchor = { click: clickSpy, href: "", download: "" };
      vi.spyOn(document, "createElement").mockReturnValue(anchor);

      const blob = new Blob(["hello"], { type: "text/plain" });
      const result = await saveFile(blob, "report.csv", CSV_FILE_TYPES);

      expect(result).toEqual({ ok: true, native: false });
      expect(anchor.download).toBe("report.csv");
      expect(clickSpy).toHaveBeenCalledOnce();
      expect(window.URL.revokeObjectURL).toHaveBeenCalledWith("blob:fake-url");
    });
  });

  describe("внутри окна приложения (window.pywebview.api.save_file_dialog доступен)", () => {
    it("кодирует blob в base64 и передаёт его вместе с именем и фильтрами в нативный диалог", async () => {
      const saveFileDialog = vi.fn().mockResolvedValue({ ok: true, path: "/home/user/report.xlsx" });
      window.pywebview = { api: { save_file_dialog: saveFileDialog } };

      const blob = new Blob(["hello world"], { type: "application/octet-stream" });
      const result = await saveFile(blob, "report.xlsx", XLSX_FILE_TYPES);

      expect(saveFileDialog).toHaveBeenCalledOnce();
      const [fileName, base64, fileTypes] = saveFileDialog.mock.calls[0];
      expect(fileName).toBe("report.xlsx");
      expect(fileTypes).toEqual(XLSX_FILE_TYPES);
      expect(atob(base64)).toBe("hello world");

      expect(result).toEqual({ ok: true, path: "/home/user/report.xlsx", native: true });
    });

    it("пробрасывает canceled: true, когда пользователь закрыл системный диалог", async () => {
      const saveFileDialog = vi.fn().mockResolvedValue({ ok: false, canceled: true });
      window.pywebview = { api: { save_file_dialog: saveFileDialog } };

      const result = await saveFile(new Blob(["x"]), "x.xlsx");

      expect(result).toEqual({ ok: false, canceled: true, native: true });
    });

    it("пробрасывает error, когда бэкенд не смог записать файл", async () => {
      const saveFileDialog = vi.fn().mockResolvedValue({ ok: false, error: "диск переполнен" });
      window.pywebview = { api: { save_file_dialog: saveFileDialog } };

      const result = await saveFile(new Blob(["x"]), "x.xlsx");

      expect(result).toEqual({ ok: false, error: "диск переполнен", native: true });
    });

    it("работает и без переданных file_types (необязательный параметр)", async () => {
      const saveFileDialog = vi.fn().mockResolvedValue({ ok: true, path: "/tmp/x" });
      window.pywebview = { api: { save_file_dialog: saveFileDialog } };

      await saveFile(new Blob(["x"]), "x.xlsx");

      expect(saveFileDialog.mock.calls[0][2]).toEqual([]);
    });
  });
});

describe("XLSX_FILE_TYPES / CSV_FILE_TYPES", () => {
  // Регрессия: реальная причина "файлы is not a valid file filter" — дефис
  // в описании фильтра ("Excel-файлы"), который pywebview не принимает
  // (см. backend/native_app.py: SaveDialogApi — валидирует тем же regex,
  // см. webview.util.parse_file_type: r'^([\w ]+)\((\*...)\)$'). Python's
  // \w — Unicode-aware, поэтому здесь используем \p{L}\p{N}_, а не \w
  // (в JS \w — только ASCII, кириллица бы не совпала).
  const VALID_FILTER = /^[\p{L}\p{N}_ ]+\(\*\.(?:[\p{L}\p{N}_]+|\*)\)$/u;

  it.each([...XLSX_FILE_TYPES, ...CSV_FILE_TYPES])("%s соответствует формату фильтра pywebview", (entry) => {
    expect(entry).toMatch(VALID_FILTER);
  });
});
