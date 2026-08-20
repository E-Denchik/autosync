// Сохранение файла на диск через системный диалог "Сохранить как" (выбор
// папки, имени и расширения) вместо скрытого <a download>, которое молча
// роняло файл в системную папку загрузок без возможности выбрать место —
// см. window.pywebview.api.save_file_dialog в backend/native_app.py
// (SaveDialogApi). Открыть настоящий диалог ОС может только сам
// pywebview-процесс, поэтому вызов идёт через js_api-мост, а не средствами
// браузера.

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error || new Error("Не удалось прочитать файл"));
    reader.readAsDataURL(blob);
  });
}

function browserDownloadFallback(blob, fileName) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  window.URL.revokeObjectURL(url);
}

/**
 * @param {Blob} blob
 * @param {string} fileName - предложенное имя файла (пользователь может изменить в диалоге)
 * @param {string[]} [fileTypes] - фильтры формата, например ["Excel-файлы (*.xlsx)", "Все файлы (*.*)"]
 * @returns {Promise<{ok: boolean, canceled?: boolean, native: boolean, path?: string, error?: string}>}
 */
export async function saveFile(blob, fileName, fileTypes = []) {
  const nativeApi = window.pywebview?.api;

  if (!nativeApi?.save_file_dialog) {
    // Не внутри окна приложения (например, `npm run dev` в обычном браузере
    // при разработке) — системного диалога нет, обычное скачивание браузера.
    browserDownloadFallback(blob, fileName);
    return { ok: true, native: false };
  }

  const base64 = await blobToBase64(blob);
  const result = await nativeApi.save_file_dialog(fileName, base64, fileTypes);
  return { ...result, native: true };
}

// Формат строго фиксирован pywebview: "описание (*.ext)", где описание —
// только буквы/цифры/пробелы (regex в webview.util.parse_file_type) — ни
// дефис, ни любая другая пунктуация в описании не допускаются, иначе
// create_file_dialog падает ДО открытия диалога (см. backend/native_app.py:
// SaveDialogApi.save_file_dialog — там же добавлена защита на случай, если
// сюда снова попадёт некорректная строка).
export const XLSX_FILE_TYPES = ["Excel файлы (*.xlsx)", "Все файлы (*.*)"];
export const CSV_FILE_TYPES = ["CSV файлы (*.csv)", "Все файлы (*.*)"];
