# SIN VERIFICAR: escrito pero no construido en la sesión de desarrollo (no había Docker).
FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1
# Los datos viven en /app/data (móntalo como volumen para no perderlos al reiniciar).
VOLUME ["/app/data"]
EXPOSE 8787
CMD ["python", "-m", "radar", "record"]
