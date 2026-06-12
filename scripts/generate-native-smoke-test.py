from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAZAAAADICAYAAADGFbfiAAAACXBIWXMAAAsSAAALEgHS3X78"
    "AAAGC0lEQVR4nO3dS47bSBiG4S8LQm7qsp0JMv//Wag3w1FSXNTB4EkxirME4ypF0nFrT40naT6A"
    "gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAcOYtD2+fT8+fP7+3v3///v379y9f"
    "vrx9+7bfr2/fvn379u3b99fX13f79u1Hjx59+vTp06dPnz59+vTp06dPnz59+vTp06dPnz59+vTp"
    "06dPn37dW4f75+fH8+fPt27f/69evX758+fLly8ePH39/f//9998vX758+fLly8ePH39/f//9998v"
    "v2w5vX79+vXr16+fPn36+PHj5cuX79+/f/78+fPnz59///33+fPn37x58+vXr58/f/78+fPnz59/"
    "f39/f39/f3/7+fNnKqXU7Xb7/Pnz8fHx/v7+4uLi4uPj+/fv79+/v3///v3799fX17dbK8vLy8vLy"
    "9vb2+vr69vb29vb2+Pj4/v7+9fX1+fn54eHh4eHh4+Pj29vb09PT09PT29vb29vb29vb29vY2NjU1"
    "NTU1NTU1NTU1NTU1NTU1NRU7O3k8HmfX14+Pj9fX17e3t3d3d4+Pj9fX17e3t3d3d4+Pj9fX17e3t"
    "3d3d4+Pj9fX17e3t3d3d4+Pj9fX17e3t3d3d4+Pj7W2tubm5ubm5ubm5ubm5ubm5ubm5ubm5ubm5u"
    "bm5ubm5ubm5ubm5ubm5ubm5uZmbl8vl8nmc9mY+Pj7e3t7e3t7e3t7e3t7e3t7e3t7e3t7e3t7e3t"
    "7e3t7e3t7e3t7e3t7e3t7d5aP5/P53O5rNVqNfr8/Pz8/Pz8/Pz8/Pz8/Pz8/Pz8/Pz8/Pz8/Pz8"
    "Pz8/Pz8/Pz8/Pz8/Pz8/M7n87nM5nM1m82m82m82m82m82m82m82m82m82m82m82m82m82m82m8"
    "2m82m82m8zA2TjKfT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6fT6eR7g"
    "6fTq1atXr169evXq1atXr169evXq1atXr169evXq1atXr169evXq1atXr169evXq1avXr3+u3N7v3"
    "/+/Pnz58+fP39/f39/f39/f39/f39/f39/f39/f39/f39/f39/f39/f39/f39/f39/f39/f8z8"
    "cwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwHl8ARgk4/F5W0eIAAAAAElFTkSuQmCC"
)


def main() -> None:
    img = ImageReader(BytesIO(base64.b64decode(PNG_BASE64)))
    out_dir = Path("data/uploads")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "native-image-smoke-test.pdf"
    packet = canvas.Canvas(str(out_path), pagesize=letter)
    for page in range(1, 4):
        packet.setFont("Helvetica-Bold", 18)
        packet.drawString(72, 740, f"Native Image Smoke Test - Page {page}")
        packet.setFont("Helvetica", 11)
        packet.drawString(
            72,
            710,
            "This PDF embeds a chart-style image for Azure AI Search native image serving validation.",
        )
        packet.drawString(
            72,
            694,
            "Question targets: blueprint, diagram, architecture, evidence, construction workflow.",
        )
        packet.drawImage(img, 72, 380, width=420, height=220, preserveAspectRatio=True, mask="auto")
        packet.setFont("Helvetica-Bold", 12)
        packet.drawString(72, 348, "Architecture Notes")
        packet.setFont("Helvetica", 11)
        packet.drawString(
            72,
            330,
            "Source docs -> Blob -> Search skillset -> enrichment index -> canonical chunks -> native multimodal KB.",
        )
        packet.drawString(
            72,
            314,
            "This page should allow testing both app-managed chunk grounding and image-backed native retrieval.",
        )
        packet.showPage()
    packet.save()
    print(out_path)


if __name__ == "__main__":
    main()
