import { Component } from "react";
import { AlertCircleIcon, RefreshIcon } from "./icons.jsx";

// React error boundary может быть только классом — хуков для этого не
// предусмотрено (getDerivedStateFromError/componentDidCatch не имеют
// хук-аналога). Без него необработанная ошибка рендера в ЛЮБОЙ странице
// размонтирует всё дерево React целиком — в десктоп-приложении (pywebview,
// без адресной строки/консоли под рукой у пользователя) это пустой белый
// экран без единой подсказки, как вернуться к работе, кроме полного
// перезапуска программы.
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Необработанная ошибка в интерфейсе:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel" style={{ maxWidth: 520, margin: "40px auto", textAlign: "center" }}>
          <AlertCircleIcon style={{ width: 32, height: 32, color: "var(--danger, #e5484d)" }} />
          <div className="section-title" style={{ marginTop: 12 }}>
            Что-то пошло не так
          </div>
          <p className="text-muted" style={{ fontSize: 13 }}>
            Эта страница столкнулась с непредвиденной ошибкой. Остальная часть программы продолжает работать —
            попробуйте обновить страницу или перейти в другой раздел через меню слева.
          </p>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            <RefreshIcon /> Обновить страницу
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
