import { InfoIcon, ChevronRightIcon } from "./icons.jsx";

export default function HowToUse({ steps }) {
  return (
    <details className="how-to-use">
      <summary>
        <InfoIcon />
        <span>Как пользоваться этим разделом</span>
        <ChevronRightIcon className="how-to-use-chevron" />
      </summary>
      <ol>
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </details>
  );
}
