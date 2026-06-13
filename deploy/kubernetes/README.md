# Axon Kubernetes Deployment

Deploy the Axon platform on Kubernetes using the included Helm chart.

## Prerequisites

- `kubectl` >= 1.24
- `helm` >= 3.0
- A running Kubernetes cluster (local: kind, minikube; cloud: EKS, GKE, AKS)
- A default StorageClass configured in your cluster (for PVC provisioning)

## Quick Install

```bash
helm install axon ./deploy/kubernetes/helm/axon
```

This deploys with default values: 2 backend replicas, 1 dashboard replica, PostgreSQL and Redis PVCs enabled, ingress disabled.

## Values Customization

Override any value with `--set` or a custom `values.yaml`:

```bash
# Override image tags for a specific release
helm install axon ./deploy/kubernetes/helm/axon \
  --set backend.image=ghcr.io/aarohim24/axon-backend:0.4.1 \
  --set dashboard.image=ghcr.io/aarohim24/axon-dashboard:0.4.1

# Enable ingress with a hostname
helm install axon ./deploy/kubernetes/helm/axon \
  --set ingress.enabled=true \
  --set ingress.host=axon.example.com

# Use a custom values file
helm install axon ./deploy/kubernetes/helm/axon -f my-values.yaml
```

### Key values

| Key | Default | Description |
|---|---|---|
| `backend.replicaCount` | `2` | Number of backend pod replicas |
| `backend.image` | `ghcr.io/aarohim24/axon-backend:latest` | Backend container image |
| `dashboard.replicaCount` | `1` | Number of dashboard pod replicas |
| `dashboard.image` | `ghcr.io/aarohim24/axon-dashboard:latest` | Dashboard container image |
| `postgres.enabled` | `true` | Create a PostgreSQL PVC |
| `postgres.storageSize` | `20Gi` | PostgreSQL PVC size |
| `redis.enabled` | `true` | Create a Redis PVC |
| `redis.storageSize` | `2Gi` | Redis PVC size |
| `ingress.enabled` | `false` | Enable the Ingress resource |
| `ingress.host` | `""` | Hostname for the Ingress rule |
| `config.API_KEY` | `change-me-in-production` | Axon API key (change before deploying) |
| `config.DATABASE_URL` | `postgresql+asyncpg://axon:axon@postgres:5432/axon` | Database connection string |
| `config.REDIS_URL` | `redis://redis:6379/0` | Redis connection string |

**Important:** Always override `config.API_KEY` with a strong secret before deploying to any non-local environment.

## Upgrade Procedure

```bash
helm upgrade axon ./deploy/kubernetes/helm/axon
```

To upgrade with new image tags:

```bash
helm upgrade axon ./deploy/kubernetes/helm/axon \
  --set backend.image=ghcr.io/aarohim24/axon-backend:0.4.2 \
  --set dashboard.image=ghcr.io/aarohim24/axon-dashboard:0.4.2
```

Check rollout status after upgrading:

```bash
kubectl rollout status deployment/axon-backend
kubectl rollout status deployment/axon-dashboard
```

## Uninstall

```bash
helm uninstall axon
```

Note: PVCs are not deleted automatically. Remove them manually if needed:

```bash
kubectl delete pvc axon-postgres-pvc axon-redis-pvc
```

## Resource Requirements

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---|---|---|---|---|
| backend (per pod) | 250m | 500m | 512Mi | 1Gi |
| backend (2 replicas) | 500m | 1000m | 1Gi | 2Gi |
| dashboard | 100m | 200m | 128Mi | 256Mi |
| **Total** | **600m** | **1200m** | **1.1Gi** | **2.25Gi** |

A cluster with at least 2 vCPU and 3Gi allocatable memory is recommended.

## Health Checks

The backend deployment includes readiness and liveness probes against `GET /health` on port 8000:

- **Readiness**: starts checking after 5s, every 10s, fails after 3 consecutive failures
- **Liveness**: starts checking after 15s, every 20s, fails after 3 consecutive failures

The dashboard serves a static React SPA — no health probe is configured for it.
