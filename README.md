# Kubernetes MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that lets AI assistants (Claude, etc.) inspect and manage Kubernetes clusters using natural language.

Ask Claude things like *"Why is my pod crashing?"* or *"Scale nginx to 5 replicas"* — it calls the right Kubernetes API under the hood.

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Available Tools](#available-tools)
- [User Guide & Example Prompts](#user-guide--example-prompts)
- [Security Notes](#security-notes)

---

## Overview

```
Claude Desktop / Claude Code
        │
        │  MCP (stdio)
        ▼
 kubernetes-mcp server
        │
        │  kubernetes Python client
        ▼
  ~/.kube/config → your cluster
```

The server exposes **26 tools** across every major Kubernetes resource type. It reads your existing `~/.kube/config`, so no extra credentials are needed.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.12 |
| [uv](https://docs.astral.sh/uv/) | any recent |
| kubectl + kubeconfig | cluster access configured |
| Claude Desktop | for MCP integration |

---

## Installation

```bash
git clone https://github.com/roheetmeister/kubernetes-mcp-server.git
cd kubernetes-mcp-server
uv sync
```

Verify it works:

```bash
uv run python -c "from kubernetes_mcp import mcp; print('OK')"
```

---

## Configuration

### Claude Desktop

Add the following to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "kubernetes": {
      "command": "/path/to/uv",
      "args": [
        "--directory",
        "/path/to/kubernetes-mcp-server",
        "run",
        "main.py"
      ]
    }
  }
}
```

Replace `/path/to/uv` with the output of `which uv` and `/path/to/kubernetes-mcp-server` with the cloned repo path. Restart Claude Desktop after saving.

### Claude Code (CLI)

```bash
claude mcp add kubernetes -- uv --directory /path/to/kubernetes-mcp-server run main.py
```

### Run manually (stdio)

```bash
uv run main.py
```

---

## Available Tools

### Cluster & Namespaces
| Tool | Description |
|---|---|
| `get_cluster_info` | Server version, platform, Go version |
| `list_namespaces` | All namespaces and their phase |

### Nodes
| Tool | Description |
|---|---|
| `list_nodes` | All nodes with status, roles, CPU, memory |
| `get_node` | Full node detail: conditions, taints, labels, capacity |

### Pods
| Tool | Description |
|---|---|
| `list_pods` | Pods in a namespace (or all); status, restarts, node |
| `get_pod` | Full pod detail: containers, states, resource limits |
| `get_pod_logs` | Tail container logs; supports previous container |

### Deployments
| Tool | Description |
|---|---|
| `list_deployments` | Replica status for all deployments |
| `get_deployment` | Strategy, conditions, container images |
| `scale_deployment` | Change replica count |
| `restart_deployment` | Rolling restart (sets `restartedAt` annotation) |

### Services
| Tool | Description |
|---|---|
| `list_services` | Type, ClusterIP, ports |
| `get_service` | Selector, port mappings, external IPs |

### Workloads
| Tool | Description |
|---|---|
| `list_statefulsets` | Ready replicas, headless service |
| `list_daemonsets` | Desired vs current vs ready per node |
| `list_jobs` | Completion status |
| `list_cronjobs` | Schedule, suspend flag, last run time |

### Config & Secrets
| Tool | Description |
|---|---|
| `list_configmaps` | Names and key count |
| `get_configmap` | Full key/value contents |
| `list_secrets` | Names and types only — **values are never returned** |

### Networking & Storage
| Tool | Description |
|---|---|
| `list_ingresses` | Hosts, address, TLS |
| `list_persistent_volumes` | Capacity, access modes, reclaim policy |
| `list_persistent_volume_claims` | Status, bound volume, storage class |

### Events
| Tool | Description |
|---|---|
| `get_events` | Recent events; filter by object name |

### Resource Management
| Tool | Description |
|---|---|
| `apply_manifest` | Create resources from a YAML string |
| `delete_resource` | Delete by kind + name (Pod, Deployment, Service, etc.) |

---

## User Guide & Example Prompts

### 1. Cluster Health Check

> "Give me a health overview of my cluster"

Claude will call `get_cluster_info`, `list_nodes`, and `list_namespaces` to give you a full picture.

---

### 2. Find and Diagnose a Broken Pod

> "Why is my pod crash-loop-demo crashing?"

Claude calls:
1. `get_pod("crash-loop-demo")` — sees CrashLoopBackOff, 35 restarts
2. `get_pod_logs("crash-loop-demo")` — checks what the container printed before dying
3. `get_events(involved_object="crash-loop-demo")` — shows the BackOff warning timeline

---

### 3. Scale a Deployment

> "Scale the nginx deployment to 5 replicas"

```
scale_deployment("nginx", replicas=5)
```

---

### 4. Rolling Restart After a Config Change

> "Restart the api-server deployment"

```
restart_deployment("api-server")
```

This patches the pod template annotation with a timestamp, triggering a rolling restart without downtime.

---

### 5. View Logs from a Specific Container

> "Show me the last 50 lines of logs from the payment-service pod"

```
get_pod_logs("payment-service", tail_lines=50)
```

For multi-container pods:

> "Show logs from the sidecar container in payment-service"

```
get_pod_logs("payment-service", container="sidecar", tail_lines=50)
```

---

### 6. Audit All Pods Across Every Namespace

> "List all pods in all namespaces and their status"

```
list_pods(namespace="all")
```

---

### 7. Check Node Capacity

> "How much CPU and memory does each node have?"

```
list_nodes()
```

For a specific node:

```
get_node("kind-worker")
```

---

### 8. Apply a Manifest

> "Deploy this YAML to the cluster"

Paste your YAML directly into the prompt. Claude extracts it and calls:

```
apply_manifest(yaml_content="<your yaml>")
```

Supports multi-document YAML (separated by `---`).

---

### 9. Check Ingress Routing

> "What ingresses are configured and what hosts do they serve?"

```
list_ingresses(namespace="all")
```

---

### 10. Storage Audit

> "List all PVCs and whether they are bound"

```
list_persistent_volume_claims(namespace="default")
```

PVC status meanings:
- **Pending** — waiting for a matching PV or dynamic provisioner
- **Bound** — attached to a PV and ready to use
- **Lost** — backing PV was deleted; data may be gone

---

### 11. Delete a Resource

> "Delete the pod named old-worker in the staging namespace"

```
delete_resource(kind="Pod", name="old-worker", namespace="staging")
```

Supported kinds: `Pod`, `Deployment`, `Service`, `ConfigMap`, `Secret`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `Ingress`, `Namespace`.

---

## Security Notes

- **Secret values are never returned.** `list_secrets` shows only names and types.
- The server uses your local `~/.kube/config` — it inherits whatever RBAC permissions your current context has.
- `delete_resource` and `scale_deployment` are write operations. Grant the kubeconfig user only the permissions your use case requires.
- For read-only use, bind the `view` ClusterRole to your kubeconfig user.
