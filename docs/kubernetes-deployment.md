# Kubernetes Deployment Guide

Axon ships a Helm chart located at `deploy/kubernetes/helm/axon`. This guide covers
prerequisites, installation, production customization, upgrades, and resource requirements.

---

## Prerequisites

| Tool | Minimum Version | Notes |
|---|---|---|
| `kubectl` | 1.24 | Required to apply manifests and inspect resources |
| `helm` | 3.0 | Required to install and upgrade the chart |
| Kubernetes cluster | 1.24 | GKE, EKS, AKS, k3s, or any conformant cluster |
| `pgvector` extension | 0.5.0+ | Must be available in your Postgres instance if using managed DB |
| Persistent volume provisioner | — | Required if `postgres.enabled=true` or `redis.enabled=true` |

Verify your tools:

```bash
kubectl version --client
helm version
```

---

## Quick Install

Add the chart and install with default values:

```bash
# Clone the repo (chart is not yet published to a Helm registry)
git clone https://github.com/aarohimathur/axon
cd axon

# Install into the 'axon' namespace (creates it if absent)
helm install axon deploy/kubernetes/helm/axon \
  --namespace axon \
  --create-namespace \
  --set backend.image.tag=0.4.0 \
  --set dashboard.image.tag=0.4.0
```

After installation, check pod status:

```bash
kubectl get pods -n axon
```

Expected output once healthy:

```
NAME                                READY   STATUS    RESTARTS   AGE
axon-backend-7d4f8b9c6-xxxxx        1/1     Running   0          2m
axon-backend-7d4f8b9c6-yyyyy        1/1     Running   0          2m
axon-dashboard-5c8b9d4f7-zzzzz      1/1     Running   0          2m
```

Access the backend API:

```bash
kubectl port-forward svc/axon-backend 8000:8000 -n axon
curl http://localhost:8000/health
```

Access the dashboard:

```bash
kubectl port-forward svc/axon-dashboard 5173:80 -n axon
# Open http://localhost:5173 in your browser
```

---

## Production Values Customization

Override values by passing `--values production.yaml` or individual `--set` flags.

### Recommended production values file

Create `production.yaml`:

```yaml
backend:
  replicaCount: 3
  image:
    repository: ghcr.io/aarohimathur/axon-backend
    tag: "0.4.0"
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: "500m"
      memory: "512Mi"
    limits:
      cpu: "2000m"
      memory: "2Gi"
  env:
    DATABASE_URL: ""   # Set via secret — see Secrets section below
    REDIS_URL: ""      # Set via secret
    AXON_API_KEY: ""   # Set via secret

dashboard:
  replicaCount: 2
  image:
    repository: ghcr.io/aarohimathur/axon-dashboard
    tag: "0.4.0"
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: "100m"
      memory: "64Mi"
    limits:
      cpu: "500m"
      memory: "256Mi"

# Disable bundled Postgres/Redis if using managed services (recommended for production)
postgres:
  enabled: false

redis:
  enabled: false

ingress:
  enabled: true
  host: "axon.internal.example.com"
  annotations:
    kubernetes.io/ingress.class: "nginx"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  tls:
    - secretName: axon-tls
      hosts:
        - axon.internal.example.com
```

Install with your production values:

```bash
helm install axon deploy/kubernetes/helm/axon \
  --namespace axon \
  --create-namespace \
  --values production.yaml
```

### Secrets management

The chart creates a Kubernetes Secret (`axon-secrets`) for `DATABASE_URL`, `REDIS_URL`, and
`AXON_API_KEY`. For production, provide these via an external secrets operator
(e.g., External Secrets Operator, Sealed Secrets, or Vault Agent Injector) rather than
inline values:

```bash
# Example: create the secret manually (not recommended for GitOps — use ESO instead)
kubectl create secret generic axon-secrets \
  --namespace axon \
  --from-literal=DATABASE_URL="postgresql+asyncpg://axon:password@postgres.internal:5432/axon" \
  --from-literal=REDIS_URL="redis://redis.internal:6379/0" \
  --from-literal=AXON_API_KEY="axon_live_your_admin_key"
```

### Using a managed Postgres and Redis

Set `postgres.enabled=false` and `redis.enabled=false` in your values file, and provide the
connection strings via the `axon-secrets` Secret. The bundled Postgres and Redis are suitable
for development and staging only — they use single-instance deployments with no HA or backups.

---

## Upgrade Procedure

### Standard upgrade

```bash
helm upgrade axon deploy/kubernetes/helm/axon \
  --namespace axon \
  --values production.yaml \
  --set backend.image.tag=0.4.1
```

Helm performs a rolling update on the backend and dashboard deployments. The backend health
check (`GET /health`) is used as the readiness probe, so traffic is only shifted to new pods
once they are healthy.

### Database migrations

Alembic migrations must be run before upgrading the backend pods. Run the migration as a
pre-upgrade Helm hook or manually:

```bash
# Manual migration (run before helm upgrade)
kubectl run axon-migrate \
  --namespace axon \
  --image=ghcr.io/aarohimathur/axon-backend:0.4.1 \
  --restart=Never \
  --env="DATABASE_URL=$(kubectl get secret axon-secrets -n axon -o jsonpath='{.data.DATABASE_URL}' | base64 -d)" \
  --command -- alembic upgrade head

# Wait for migration to complete
kubectl wait --for=condition=complete pod/axon-migrate --namespace axon --timeout=120s
kubectl delete pod axon-migrate --namespace axon
```

### Rollback

```bash
helm rollback axon 0 --namespace axon
# '0' rolls back to the previous release; specify a revision number for a specific version
```

List release history:

```bash
helm history axon --namespace axon
```

---

## Resource Requirements per Service

These are the default `values.yaml` resource settings and recommended production minimums.

### Backend (`axon-backend`)

| | Default (values.yaml) | Production minimum | Notes |
|---|---|---|---|
| Replicas | 2 | 2 | 3+ recommended for HA |
| CPU request | 250m | 500m | Spikes during batch jobs |
| CPU limit | 1000m | 2000m | |
| Memory request | 256Mi | 512Mi | Alembic migrations need ~300Mi |
| Memory limit | 1Gi | 2Gi | pgvector queries can be memory-intensive |

The backend readiness probe (`GET /health`, periodSeconds 10, failureThreshold 3) gates all
traffic routing. The liveness probe (periodSeconds 20, failureThreshold 3) restarts stuck pods.

### Dashboard (`axon-dashboard`)

| | Default (values.yaml) | Production minimum | Notes |
|---|---|---|---|
| Replicas | 1 | 2 | Static nginx — very lightweight |
| CPU request | 50m | 100m | |
| CPU limit | 200m | 500m | |
| Memory request | 32Mi | 64Mi | |
| Memory limit | 128Mi | 256Mi | |

The dashboard is a static nginx container serving a compiled React bundle. CPU and memory
requirements are minimal.

### Bundled Postgres (development only)

| | Default |
|---|---|
| Storage | 20Gi (ReadWriteOnce PVC) |
| Memory limit | 512Mi |
| CPU limit | 500m |

**Not recommended for production.** Use a managed PostgreSQL service (RDS, Cloud SQL, Azure
Database for PostgreSQL) with the `pgvector` extension enabled.

### Bundled Redis (development only)

| | Default |
|---|---|
| Storage | 2Gi (ReadWriteOnce PVC) |
| Memory limit | 256Mi |
| CPU limit | 250m |

**Not recommended for production.** Use a managed Redis service (ElastiCache, Cloud Memorystore,
Azure Cache for Redis) or a Redis operator with persistence and replication.
