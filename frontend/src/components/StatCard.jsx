import { Link } from "react-router-dom";

export default function StatCard({ icon: Icon, label, value, to }) {
  const content = (
    <>
      <div className="stat-icon">
        <Icon />
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </>
  );

  if (to) {
    return (
      <Link to={to} className="stat-card">
        {content}
      </Link>
    );
  }
  return <div className="stat-card">{content}</div>;
}
