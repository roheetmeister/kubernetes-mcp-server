"""Kubernetes MCP server — tools for inspecting and managing K8s clusters."""

from __future__ import annotations

import json
from typing import Any

import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kubernetes")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_kube_config() -> None:
    """Load kubeconfig from default location (~/.kube/config) or in-cluster."""
    try:
        config.load_kube_config()
    except config.ConfigException:
        config.load_incluster_config()


def _safe_call(fn):
    """Decorator: catch ApiException and return a readable error string."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiException as exc:
            return f"Kubernetes API error {exc.status}: {exc.reason}\n{exc.body}"
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"

    return wrapper


# ---------------------------------------------------------------------------
# Cluster / Namespace
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def get_cluster_info() -> str:
    """Return Kubernetes server version and API server URL."""
    _load_kube_config()
    v = client.VersionApi().get_code()
    _, active_context = config.list_kube_config_contexts()
    server = active_context["context"].get("cluster", "unknown")
    return (
        f"Cluster : {server}\n"
        f"Version : {v.git_version}\n"
        f"Platform: {v.platform}\n"
        f"Go      : {v.go_version}"
    )


@mcp.tool()
@_safe_call
def list_namespaces() -> str:
    """List all namespaces in the cluster with their status."""
    _load_kube_config()
    ns_list = client.CoreV1Api().list_namespace()
    lines = ["NAME                     STATUS   AGE"]
    for ns in ns_list.items:
        name = ns.metadata.name
        status = ns.status.phase or "Unknown"
        lines.append(f"{name:<25}{status}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_nodes() -> str:
    """List all nodes with their status, roles, and resource capacity."""
    _load_kube_config()
    nodes = client.CoreV1Api().list_node()
    rows = ["NAME                        STATUS   ROLES                CPU   MEMORY"]
    for node in nodes.items:
        name = node.metadata.name
        roles = ",".join(
            k.replace("node-role.kubernetes.io/", "")
            for k in (node.metadata.labels or {})
            if k.startswith("node-role.kubernetes.io/")
        ) or "worker"
        ready = next(
            (c.status for c in node.status.conditions if c.type == "Ready"), "Unknown"
        )
        status = "Ready" if ready == "True" else "NotReady"
        cpu = node.status.capacity.get("cpu", "n/a")
        mem = node.status.capacity.get("memory", "n/a")
        rows.append(f"{name:<28}{status:<9}{roles:<21}{cpu:<6}{mem}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def get_node(node_name: str) -> str:
    """Get detailed info for a specific node.

    Args:
        node_name: Name of the node
    """
    _load_kube_config()
    node = client.CoreV1Api().read_node(node_name)
    labels = node.metadata.labels or {}
    taints = node.spec.taints or []
    conditions = {c.type: c.status for c in node.status.conditions}
    capacity = node.status.capacity or {}
    allocatable = node.status.allocatable or {}

    taint_strs = [f"  {t.key}={t.value}:{t.effect}" for t in taints] or ["  (none)"]
    return (
        f"Node        : {node.metadata.name}\n"
        f"Created     : {node.metadata.creation_timestamp}\n"
        f"OS Image    : {node.status.node_info.os_image}\n"
        f"Kernel      : {node.status.node_info.kernel_version}\n"
        f"Runtime     : {node.status.node_info.container_runtime_version}\n"
        f"Kubelet     : {node.status.node_info.kubelet_version}\n"
        f"Capacity\n"
        f"  CPU       : {capacity.get('cpu', 'n/a')}\n"
        f"  Memory    : {capacity.get('memory', 'n/a')}\n"
        f"  Pods      : {capacity.get('pods', 'n/a')}\n"
        f"Allocatable\n"
        f"  CPU       : {allocatable.get('cpu', 'n/a')}\n"
        f"  Memory    : {allocatable.get('memory', 'n/a')}\n"
        f"  Pods      : {allocatable.get('pods', 'n/a')}\n"
        f"Conditions  : {json.dumps(conditions, indent=2)}\n"
        f"Taints      :\n" + "\n".join(taint_strs) + "\n"
        f"Labels      : {json.dumps(labels, indent=2)}"
    )


# ---------------------------------------------------------------------------
# Pods
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_pods(namespace: str = "default") -> str:
    """List pods in a namespace with status, restarts, and node placement.

    Args:
        namespace: Kubernetes namespace (default: "default"). Use "all" for all namespaces.
    """
    _load_kube_config()
    v1 = client.CoreV1Api()
    if namespace == "all":
        pods = v1.list_pod_for_all_namespaces()
        items = pods.items
    else:
        pods = v1.list_namespaced_pod(namespace)
        items = pods.items

    rows = ["NAMESPACE            NAME                                    READY  STATUS            RESTARTS  NODE"]
    for pod in items:
        ns = pod.metadata.namespace
        name = pod.metadata.name
        phase = pod.status.phase or "Unknown"

        containers = pod.spec.containers or []
        statuses = pod.status.container_statuses or []
        ready_count = sum(1 for s in statuses if s.ready)
        total_count = len(containers)
        restarts = sum(s.restart_count for s in statuses)
        node = pod.spec.node_name or "<pending>"

        # Refine status from container states
        for cs in statuses:
            if cs.state.waiting:
                phase = cs.state.waiting.reason or phase
            elif cs.state.terminated and cs.state.terminated.exit_code != 0:
                phase = cs.state.terminated.reason or "Error"

        rows.append(
            f"{ns:<21}{name:<40}{ready_count}/{total_count:<5}{phase:<18}{restarts:<10}{node}"
        )
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def get_pod(pod_name: str, namespace: str = "default") -> str:
    """Get detailed information about a specific pod.

    Args:
        pod_name: Name of the pod
        namespace: Namespace where the pod lives (default: "default")
    """
    _load_kube_config()
    pod = client.CoreV1Api().read_namespaced_pod(pod_name, namespace)
    meta = pod.metadata
    spec = pod.spec
    status = pod.status

    container_info = []
    for c in spec.containers:
        cs = next((s for s in (status.container_statuses or []) if s.name == c.name), None)
        state = "Unknown"
        if cs:
            if cs.state.running:
                state = f"Running (started {cs.state.running.started_at})"
            elif cs.state.waiting:
                state = f"Waiting/{cs.state.waiting.reason}"
            elif cs.state.terminated:
                state = f"Terminated/{cs.state.terminated.reason} (exit {cs.state.terminated.exit_code})"
        limits = c.resources.limits or {} if c.resources else {}
        requests = c.resources.requests or {} if c.resources else {}
        container_info.append(
            f"  [{c.name}]\n"
            f"    Image   : {c.image}\n"
            f"    State   : {state}\n"
            f"    Requests: cpu={requests.get('cpu', 'n/a')}, memory={requests.get('memory', 'n/a')}\n"
            f"    Limits  : cpu={limits.get('cpu', 'n/a')}, memory={limits.get('memory', 'n/a')}\n"
            f"    Restarts: {cs.restart_count if cs else 'n/a'}"
        )

    conditions = {c.type: c.status for c in (status.conditions or [])}
    return (
        f"Pod         : {meta.name}\n"
        f"Namespace   : {meta.namespace}\n"
        f"Node        : {spec.node_name or '<pending>'}\n"
        f"Created     : {meta.creation_timestamp}\n"
        f"Phase       : {status.phase}\n"
        f"Pod IP      : {status.pod_ip or 'n/a'}\n"
        f"Conditions  : {json.dumps(conditions)}\n"
        f"Containers  :\n" + "\n".join(container_info) + "\n"
        f"Labels      : {json.dumps(meta.labels or {}, indent=2)}"
    )


@mcp.tool()
@_safe_call
def get_pod_logs(
    pod_name: str,
    namespace: str = "default",
    container: str | None = None,
    tail_lines: int = 100,
    previous: bool = False,
) -> str:
    """Fetch logs from a pod container.

    Args:
        pod_name   : Name of the pod
        namespace  : Namespace (default: "default")
        container  : Container name (optional; needed only for multi-container pods)
        tail_lines : Number of log lines to return from the end (default: 100)
        previous   : Return logs from the previously terminated container (default: False)
    """
    _load_kube_config()
    kwargs: dict[str, Any] = {
        "tail_lines": tail_lines,
        "previous": previous,
    }
    if container:
        kwargs["container"] = container
    logs = client.CoreV1Api().read_namespaced_pod_log(pod_name, namespace, **kwargs)
    return logs or "(no logs)"


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_deployments(namespace: str = "default") -> str:
    """List deployments in a namespace with replica status.

    Args:
        namespace: Kubernetes namespace (default: "default"). Use "all" for all namespaces.
    """
    _load_kube_config()
    apps = client.AppsV1Api()
    if namespace == "all":
        deploys = apps.list_deployment_for_all_namespaces()
        items = deploys.items
    else:
        deploys = apps.list_namespaced_deployment(namespace)
        items = deploys.items

    rows = ["NAMESPACE            NAME                               READY    UP-TO-DATE  AVAILABLE  AGE"]
    for d in items:
        ns = d.metadata.namespace
        name = d.metadata.name
        desired = d.spec.replicas or 0
        ready = d.status.ready_replicas or 0
        updated = d.status.updated_replicas or 0
        available = d.status.available_replicas or 0
        age = str(d.metadata.creation_timestamp)[:10]
        rows.append(f"{ns:<21}{name:<35}{ready}/{desired:<9}{updated:<12}{available:<11}{age}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def get_deployment(deployment_name: str, namespace: str = "default") -> str:
    """Get detailed information about a deployment.

    Args:
        deployment_name: Name of the deployment
        namespace      : Namespace (default: "default")
    """
    _load_kube_config()
    d = client.AppsV1Api().read_namespaced_deployment(deployment_name, namespace)
    strategy = d.spec.strategy.type if d.spec.strategy else "n/a"
    containers = [
        f"  {c.name}: {c.image}" for c in (d.spec.template.spec.containers or [])
    ]
    conditions = {c.type: c.status for c in (d.status.conditions or [])}
    return (
        f"Deployment    : {d.metadata.name}\n"
        f"Namespace     : {d.metadata.namespace}\n"
        f"Created       : {d.metadata.creation_timestamp}\n"
        f"Strategy      : {strategy}\n"
        f"Replicas      : desired={d.spec.replicas} ready={d.status.ready_replicas or 0} "
        f"available={d.status.available_replicas or 0} updated={d.status.updated_replicas or 0}\n"
        f"Selector      : {json.dumps(d.spec.selector.match_labels or {})}\n"
        f"Containers    :\n" + "\n".join(containers) + "\n"
        f"Conditions    : {json.dumps(conditions, indent=2)}\n"
        f"Labels        : {json.dumps(d.metadata.labels or {}, indent=2)}"
    )


@mcp.tool()
@_safe_call
def scale_deployment(deployment_name: str, replicas: int, namespace: str = "default") -> str:
    """Scale a deployment to the specified number of replicas.

    Args:
        deployment_name: Name of the deployment
        replicas       : Desired number of replicas
        namespace      : Namespace (default: "default")
    """
    _load_kube_config()
    body = {"spec": {"replicas": replicas}}
    client.AppsV1Api().patch_namespaced_deployment_scale(
        deployment_name, namespace, body
    )
    return f"Deployment '{deployment_name}' in namespace '{namespace}' scaled to {replicas} replica(s)."


@mcp.tool()
@_safe_call
def restart_deployment(deployment_name: str, namespace: str = "default") -> str:
    """Trigger a rolling restart of a deployment (equivalent to kubectl rollout restart).

    Args:
        deployment_name: Name of the deployment
        namespace      : Namespace (default: "default")
    """
    import datetime

    _load_kube_config()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                }
            }
        }
    }
    client.AppsV1Api().patch_namespaced_deployment(deployment_name, namespace, body)
    return f"Rolling restart triggered for deployment '{deployment_name}' in namespace '{namespace}'."


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_services(namespace: str = "default") -> str:
    """List services in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default"). Use "all" for all namespaces.
    """
    _load_kube_config()
    v1 = client.CoreV1Api()
    if namespace == "all":
        svcs = v1.list_service_for_all_namespaces()
        items = svcs.items
    else:
        svcs = v1.list_namespaced_service(namespace)
        items = svcs.items

    rows = ["NAMESPACE            NAME                          TYPE           CLUSTER-IP       PORT(S)"]
    for svc in items:
        ns = svc.metadata.namespace
        name = svc.metadata.name
        svc_type = svc.spec.type or "ClusterIP"
        cluster_ip = svc.spec.cluster_ip or "None"
        ports = ",".join(
            f"{p.port}/{p.protocol}" + (f":{p.node_port}" if p.node_port else "")
            for p in (svc.spec.ports or [])
        )
        rows.append(f"{ns:<21}{name:<30}{svc_type:<15}{cluster_ip:<17}{ports}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def get_service(service_name: str, namespace: str = "default") -> str:
    """Get detailed information about a service.

    Args:
        service_name: Name of the service
        namespace   : Namespace (default: "default")
    """
    _load_kube_config()
    svc = client.CoreV1Api().read_namespaced_service(service_name, namespace)
    ports = [
        f"  {p.name or ''}: {p.port}/{p.protocol} → target {p.target_port}"
        + (f" nodePort={p.node_port}" if p.node_port else "")
        for p in (svc.spec.ports or [])
    ]
    ingress = svc.status.load_balancer.ingress or [] if svc.status.load_balancer else []
    ext_ips = [i.ip or i.hostname for i in ingress] if ingress else ["n/a"]
    return (
        f"Service       : {svc.metadata.name}\n"
        f"Namespace     : {svc.metadata.namespace}\n"
        f"Type          : {svc.spec.type}\n"
        f"ClusterIP     : {svc.spec.cluster_ip}\n"
        f"ExternalIPs   : {', '.join(ext_ips)}\n"
        f"Selector      : {json.dumps(svc.spec.selector or {})}\n"
        f"Ports         :\n" + "\n".join(ports) + "\n"
        f"Labels        : {json.dumps(svc.metadata.labels or {}, indent=2)}"
    )


# ---------------------------------------------------------------------------
# ConfigMaps & Secrets
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_configmaps(namespace: str = "default") -> str:
    """List ConfigMaps in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    cms = client.CoreV1Api().list_namespaced_config_map(namespace)
    rows = ["NAME                                    KEYS   AGE"]
    for cm in cms.items:
        keys = len(cm.data or {}) + len(cm.binary_data or {})
        age = str(cm.metadata.creation_timestamp)[:10]
        rows.append(f"{cm.metadata.name:<40}{keys:<7}{age}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def get_configmap(configmap_name: str, namespace: str = "default") -> str:
    """Get the contents of a ConfigMap.

    Args:
        configmap_name: Name of the ConfigMap
        namespace     : Namespace (default: "default")
    """
    _load_kube_config()
    cm = client.CoreV1Api().read_namespaced_config_map(configmap_name, namespace)
    data_section = json.dumps(cm.data or {}, indent=2)
    return (
        f"ConfigMap   : {cm.metadata.name}\n"
        f"Namespace   : {cm.metadata.namespace}\n"
        f"Created     : {cm.metadata.creation_timestamp}\n"
        f"Data        :\n{data_section}"
    )


@mcp.tool()
@_safe_call
def list_secrets(namespace: str = "default") -> str:
    """List Secret names and types in a namespace (values are NOT returned).

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    secrets = client.CoreV1Api().list_namespaced_secret(namespace)
    rows = ["NAME                                    TYPE                                  KEYS   AGE"]
    for s in secrets.items:
        keys = len(s.data or {})
        age = str(s.metadata.creation_timestamp)[:10]
        rows.append(f"{s.metadata.name:<40}{s.type:<38}{keys:<7}{age}")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def get_events(namespace: str = "default", involved_object: str | None = None) -> str:
    """Get Kubernetes events, optionally filtered by involved object name.

    Args:
        namespace        : Namespace (default: "default"). Use "all" for all namespaces.
        involved_object  : Filter events for a specific resource name (optional)
    """
    _load_kube_config()
    v1 = client.CoreV1Api()
    if namespace == "all":
        events = v1.list_event_for_all_namespaces()
        items = events.items
    else:
        events = v1.list_namespaced_event(namespace)
        items = events.items

    if involved_object:
        items = [e for e in items if e.involved_object.name == involved_object]

    # Sort by last timestamp
    items.sort(key=lambda e: (e.last_timestamp or e.event_time or ""), reverse=True)

    rows = ["LAST SEEN             TYPE      REASON               OBJECT                         MESSAGE"]
    for e in items[:50]:
        ts = str(e.last_timestamp or e.event_time or "")[:19]
        kind = e.type or "Normal"
        reason = e.reason or ""
        obj = f"{e.involved_object.kind}/{e.involved_object.name}"
        msg = (e.message or "").replace("\n", " ")[:80]
        rows.append(f"{ts:<22}{kind:<10}{reason:<21}{obj:<31}{msg}")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Generic resource apply / delete
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def apply_manifest(yaml_content: str) -> str:
    """Apply a Kubernetes manifest from a YAML string (create or update).

    Args:
        yaml_content: Full YAML manifest text (supports single or multi-document YAML)
    """
    from kubernetes import utils

    _load_kube_config()
    k8s_client = client.ApiClient()
    docs = list(yaml.safe_load_all(yaml_content))
    results = []
    for doc in docs:
        if not doc:
            continue
        kind = doc.get("kind", "Unknown")
        name = doc.get("metadata", {}).get("name", "unknown")
        try:
            utils.create_from_dict(k8s_client, doc)
            results.append(f"Created {kind}/{name}")
        except ApiException as exc:
            if exc.status == 409:
                # Already exists — patch it
                results.append(f"Already exists {kind}/{name} (not patched)")
            else:
                results.append(f"Error {kind}/{name}: {exc.status} {exc.reason}")
    return "\n".join(results) if results else "No documents found in manifest."


@mcp.tool()
@_safe_call
def delete_resource(
    kind: str,
    name: str,
    namespace: str = "default",
) -> str:
    """Delete a Kubernetes resource by kind and name.

    Supported kinds: Pod, Deployment, Service, ConfigMap, Secret, StatefulSet,
                     DaemonSet, Job, CronJob, Ingress, Namespace.

    Args:
        kind     : Resource kind (case-insensitive)
        name     : Resource name
        namespace: Namespace (ignored for cluster-scoped resources like Namespace)
    """
    _load_kube_config()
    v1 = client.CoreV1Api()
    apps = client.AppsV1Api()
    batch = client.BatchV1Api()
    net = client.NetworkingV1Api()

    dispatch = {
        "pod": lambda: v1.delete_namespaced_pod(name, namespace),
        "service": lambda: v1.delete_namespaced_service(name, namespace),
        "configmap": lambda: v1.delete_namespaced_config_map(name, namespace),
        "secret": lambda: v1.delete_namespaced_secret(name, namespace),
        "namespace": lambda: v1.delete_namespace(name),
        "deployment": lambda: apps.delete_namespaced_deployment(name, namespace),
        "statefulset": lambda: apps.delete_namespaced_stateful_set(name, namespace),
        "daemonset": lambda: apps.delete_namespaced_daemon_set(name, namespace),
        "replicaset": lambda: apps.delete_namespaced_replica_set(name, namespace),
        "job": lambda: batch.delete_namespaced_job(name, namespace),
        "cronjob": lambda: batch.delete_namespaced_cron_job(name, namespace),
        "ingress": lambda: net.delete_namespaced_ingress(name, namespace),
    }

    key = kind.lower()
    if key not in dispatch:
        return f"Unsupported kind '{kind}'. Supported: {', '.join(sorted(dispatch))}."

    dispatch[key]()
    return f"Deleted {kind}/{name}" + (f" in namespace '{namespace}'" if key != "namespace" else "") + "."


# ---------------------------------------------------------------------------
# StatefulSets / DaemonSets (read-only)
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_statefulsets(namespace: str = "default") -> str:
    """List StatefulSets in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    ssets = client.AppsV1Api().list_namespaced_stateful_set(namespace)
    rows = ["NAME                               READY   SERVICE              AGE"]
    for s in ssets.items:
        ready = s.status.ready_replicas or 0
        desired = s.spec.replicas or 0
        svc = s.spec.service_name or "n/a"
        age = str(s.metadata.creation_timestamp)[:10]
        rows.append(f"{s.metadata.name:<35}{ready}/{desired:<8}{svc:<21}{age}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def list_daemonsets(namespace: str = "default") -> str:
    """List DaemonSets in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    dsets = client.AppsV1Api().list_namespaced_daemon_set(namespace)
    rows = ["NAME                               DESIRED  CURRENT  READY  UP-TO-DATE  AVAILABLE"]
    for d in dsets.items:
        st = d.status
        rows.append(
            f"{d.metadata.name:<35}"
            f"{st.desired_number_scheduled:<9}"
            f"{st.current_number_scheduled:<9}"
            f"{st.number_ready:<7}"
            f"{st.updated_number_scheduled or 0:<12}"
            f"{st.number_available or 0}"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Jobs / CronJobs
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_jobs(namespace: str = "default") -> str:
    """List Jobs in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    jobs = client.BatchV1Api().list_namespaced_job(namespace)
    rows = ["NAME                               COMPLETIONS  DURATION  AGE"]
    for j in jobs.items:
        completions = j.spec.completions or 1
        succeeded = j.status.succeeded or 0
        age = str(j.metadata.creation_timestamp)[:10]
        rows.append(f"{j.metadata.name:<35}{succeeded}/{completions:<13}n/a       {age}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def list_cronjobs(namespace: str = "default") -> str:
    """List CronJobs in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    cjs = client.BatchV1Api().list_namespaced_cron_job(namespace)
    rows = ["NAME                               SCHEDULE         SUSPEND  ACTIVE  LAST SCHEDULE"]
    for cj in cjs.items:
        schedule = cj.spec.schedule
        suspend = str(cj.spec.suspend or False)
        active = len(cj.status.active or [])
        last = str(cj.status.last_schedule_time or "n/a")[:19]
        rows.append(f"{cj.metadata.name:<35}{schedule:<17}{suspend:<9}{active:<8}{last}")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Ingresses / PersistentVolumes
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_call
def list_ingresses(namespace: str = "default") -> str:
    """List Ingresses in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    ingresses = client.NetworkingV1Api().list_namespaced_ingress(namespace)
    rows = ["NAME                     CLASS   HOSTS                        ADDRESS          PORTS"]
    for ing in ingresses.items:
        cls = (ing.spec.ingress_class_name or "n/a")
        hosts = ",".join(r.host or "*" for r in (ing.spec.rules or []))[:28]
        lb = ing.status.load_balancer
        addr = ",".join(
            i.ip or i.hostname for i in (lb.ingress or [])
        ) if lb and lb.ingress else "n/a"
        ports_set = set()
        for rule in (ing.spec.rules or []):
            if rule.http:
                ports_set.add("80")
        if ing.spec.tls:
            ports_set.add("443")
        ports = ",".join(sorted(ports_set)) or "80"
        rows.append(f"{ing.metadata.name:<25}{cls:<8}{hosts:<29}{addr:<17}{ports}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def list_persistent_volumes() -> str:
    """List all PersistentVolumes in the cluster."""
    _load_kube_config()
    pvs = client.CoreV1Api().list_persistent_volume()
    rows = ["NAME                     CAPACITY  ACCESS MODES  RECLAIM POLICY  STATUS      STORAGECLASS"]
    for pv in pvs.items:
        cap = pv.spec.capacity.get("storage", "n/a") if pv.spec.capacity else "n/a"
        modes = ",".join(pv.spec.access_modes or [])
        reclaim = pv.spec.persistent_volume_reclaim_policy or "n/a"
        status = pv.status.phase or "Unknown"
        sc = pv.spec.storage_class_name or "n/a"
        rows.append(f"{pv.metadata.name:<25}{cap:<10}{modes:<14}{reclaim:<16}{status:<12}{sc}")
    return "\n".join(rows)


@mcp.tool()
@_safe_call
def list_persistent_volume_claims(namespace: str = "default") -> str:
    """List PersistentVolumeClaims in a namespace.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    _load_kube_config()
    pvcs = client.CoreV1Api().list_namespaced_persistent_volume_claim(namespace)
    rows = ["NAME                     STATUS  VOLUME                     CAPACITY  ACCESS MODES  STORAGECLASS"]
    for pvc in pvcs.items:
        status = pvc.status.phase or "Unknown"
        volume = pvc.spec.volume_name or "n/a"
        cap = (pvc.status.capacity or {}).get("storage", "n/a")
        modes = ",".join(pvc.status.access_modes or [])
        sc = pvc.spec.storage_class_name or "n/a"
        rows.append(f"{pvc.metadata.name:<25}{status:<8}{volume:<27}{cap:<10}{modes:<14}{sc}")
    return "\n".join(rows)
