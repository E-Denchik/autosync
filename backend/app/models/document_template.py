from datetime import datetime

from app.extensions import db


class DocumentTemplate(db.Model):
    __tablename__ = "document_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False)
    original_filename = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(1024), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<DocumentTemplate {self.name}>"
