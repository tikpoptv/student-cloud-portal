FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.runtime.txt ./
RUN pip install --no-cache-dir -r requirements.runtime.txt && useradd --uid 10001 --create-home portal
COPY app.py activation.py live_provision.py admin_dashboard.py membership.py database.py localization.py repo_review.py wsgi.py entrypoint.sh ./
COPY locales ./locales
COPY templates ./templates
COPY static ./static
COPY reference-kit ./reference-kit
COPY project-kit ./project-kit
RUN mkdir private && chown portal:portal private
USER portal
CMD ["sh", "entrypoint.sh"]
