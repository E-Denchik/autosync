import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import { useToast } from "../../context/ToastContext.jsx";

function formatBytes(value) {
  if (!value) return "нет данных";
  return `${(value / 1024 ** 3).toFixed(1)} ГБ`;
}

const TIERS = [
  {
    label: "Компактная",
    range: "до 2 млрд параметров (например, gemma3:1b)",
    speed: "очень быстрая",
    quality: "слабая для открытой генерации (текстов, инструкций) — часто общие/неточные ответы",
    when: "классификация, сопоставление по названию, короткие структурированные ответы",
  },
  {
    label: "Сбалансированная",
    range: "2–8 млрд параметров (например, llama3.2:3b)",
    speed: "быстрая",
    quality: "неплохой компромисс, но для пошаговых инструкций формулировки часто общие",
    when: "большинство задач приложения, если не критична глубина генерации",
  },
  {
    label: "Мощная",
    range: "8–20 млрд параметров (например, qwen2.5:14b)",
    speed: "средняя, требует больше RAM",
    quality: "заметно лучше держит контекст и специфику задачи",
    when: "генерация инструкций, текстов карточек — там, где важна точность формулировок",
  },
  {
    label: "Очень мощная",
    range: "более 20 млрд параметров",
    speed: "медленная на слабом железе",
    quality: "лучшее качество из локальных моделей",
    when: "то же, что «мощная», если железо позволяет",
  },
  {
    label: "Облачная (vsegpt.ru)",
    range: "не зависит от вашего компьютера",
    speed: "зависит от конкретной модели и нагрузки vsegpt.ru",
    quality: "от простых до топовых — сильно различается по конкретной модели",
    when: "когда локального железа не хватает, или нужно лучшее качество вне зависимости от него — платно за каждый запрос",
  },
];

export default function LlmModelGuide() {
  const [data, setData] = useState(null);
  const toast = useToast();

  useEffect(() => {
    api.performance().then(setData).catch((error) => toast.error(error.message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Справка по моделям</h2>
          <p>
            Как оценивать модель перед выбором в{" "}
            <Link to="/admin/llm">Администрирование → LLM-модель</Link>: что означает её размер, и
            поместится ли она в память этого компьютера.
          </p>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Уровни возможностей</h3>
        <p className="text-muted">
          Демонстрация показала это на практике: маленькая локальная модель технически отвечает на
          любой запрос, включая открытую генерацию («расписать работу») — но такие ответы часто общие
          или неточные. Для классификации и сопоставления по названию той же модели обычно достаточно.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Уровень</th>
                <th>Размер</th>
                <th>Скорость</th>
                <th>Качество генерации</th>
                <th>Когда использовать</th>
              </tr>
            </thead>
            <tbody>
              {TIERS.map((tier) => (
                <tr key={tier.label}>
                  <td><strong>{tier.label}</strong></td>
                  <td>{tier.range}</td>
                  <td>{tier.speed}</td>
                  <td>{tier.quality}</td>
                  <td>{tier.when}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Как считается «поместится ли модель в память»</h3>
        <p className="text-muted">
          Бейдж совместимости на странице выбора модели сравнивает размер модели со свободной и общей
          оперативной памятью этого компьютера: «впритык» — модель весит больше 70% того, что сейчас
          свободно (может тормозить вместе с другими программами); «скорее всего не поместится» —
          модель весит больше 85% ВСЕЙ памяти компьютера (будет работать в разы медленнее из-за
          постоянного свопирования, а не просто «медленнее»); «размер неизвестен» — у модели нет ни
          метаданных о числе параметров, ни распознаваемого размера в имени.
        </p>
        <p className="text-muted" style={{ marginBottom: 0 }}>
          Отдельно от размера: локальный раннер (Ollama/LM Studio) считает быстро, только если реально
          использует видеокарту. Если видеокарта есть, но драйвер не отвечает или не хватило видеопамяти,
          раннер молча переключается на обычный процессор — это выглядит как медленная обработка без
          явной ошибки. AutoSync не может надёжно проверить это заранее на любой системе, но замечает
          такое поведение по факту первого же медленного запроса — см. предупреждение на странице{" "}
          <Link to="/admin/llm">LLM-модель</Link>, если оно появится.
        </p>
      </div>

      {!data ? (
        <Spinner label="Оцениваем возможности компьютера…" />
      ) : (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>На этом компьютере</h3>
          <div className="llm-stats-grid">
            <div><strong>Процессоры</strong><br />{data.system.cpu_count}</div>
            <div><strong>Всего RAM</strong><br />{formatBytes(data.system.memory_total_bytes)}</div>
            <div><strong>Доступно RAM</strong><br />{formatBytes(data.system.memory_available_bytes)}</div>
          </div>
          <p className="text-muted" style={{ marginBottom: 0, marginTop: 8 }}>
            {data.cpu_only_suspected
              ? "⚠ Раннер недавно вёл себя как CPU-only — см. пояснение выше."
              : "CPU-only режим сейчас не обнаружен (но это не гарантия — детектор реагирует по факту медленного запроса, а не заранее)."}
          </p>
        </div>
      )}
    </div>
  );
}
