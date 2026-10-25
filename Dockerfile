# Metadata-only CityLink monitor.  No public GTFS-RT endpoints are created.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY cloudrun/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY collector/citylink_gtfsrt_bridge.py collector/publish_citylink_gtfsrt_snapshot.py collector/service_windows.py /app/collector/
COPY cloudrun/citylink_monitor.py /app/cloudrun/citylink_monitor.py
ENV PYTHONPATH=/app/collector
USER 65532:65532
CMD ["python", "/app/cloudrun/citylink_monitor.py"]
