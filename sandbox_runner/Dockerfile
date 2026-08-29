FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 1000 --create-home sandboxuser

COPY runner.py excel_ops.py pdf_ops.py docx_ops.py ./

USER 1000:1000

ENTRYPOINT ["python", "runner.py"]