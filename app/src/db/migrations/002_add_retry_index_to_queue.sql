CREATE INDEX IF NOT EXISTS idx_ingress_queueu_status_created
ON incident_ingress_queue (status, created_at)
WHERE status = 'pending';