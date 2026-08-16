# Author: Systronaut
# Web UI: SYSTRONAUT-styled console for end users (operator) and admins.
# Same look & feel as the original webapp, extended into a real deploy flow.

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, current_app, abort)
import os

from ..auth import authenticate, login_required, current_actor, ROLE_ADMIN
from ..models import DeploymentSpec
from ..validators import ValidationError
from .. import (catalog, security, providers, answer_files, crypto, hypervisors,
                templating)

web_bp = Blueprint("web", __name__)


def _safe_next(target: str | None) -> str:
    """Only allow same-site relative redirects (defeats open-redirect)."""
    if target and target.startswith("/") and not target.startswith(("//", "/\\")):
        return target
    return url_for("web.index")


@web_bp.get("/login")
def login():
    return render_template("login.html", next=request.args.get("next", "/"))


@web_bp.post("/login")
def login_post():
    role = authenticate(request.form.get("username", ""), request.form.get("password", ""))
    if not role:
        flash("Invalid credentials.", "danger")
        return render_template("login.html", next=request.form.get("next", "/")), 401
    session.clear()
    session["user"] = request.form.get("username", "")
    session["role"] = role
    current_app.store.audit(current_actor(), "auth.login")
    return redirect(_safe_next(request.form.get("next")))


@web_bp.get("/logout")
def logout():
    if session.get("user"):
        current_app.store.audit(current_actor(), "auth.logout")
    session.clear()
    return redirect(url_for("web.login"))


@web_bp.get("/")
@login_required()
def index():
    deps = current_app.store.list(limit=10)
    return render_template("index.html", images=catalog.all_images(),
                           profiles=security.all_profiles(), recent=deps,
                           providers_count=len(providers.available()),
                           role=session.get("role"))


@web_bp.get("/deploy")
@login_required()
def deploy_form():
    # Optional OS preselect (e.g. from the answer-file library "Deploy this OS").
    preselect = request.args.get("os", "")
    if not catalog.is_valid_key(preselect):
        preselect = ""
    return render_template(
        "deploy.html",
        images=catalog.all_images(),
        profiles=security.all_profiles(),
        providers=providers.available(),
        default_profile=security.DEFAULT_PROFILE,
        preselect=preselect,
        role=session.get("role"),
    )


@web_bp.post("/deploy")
@login_required()
def deploy_submit():
    try:
        spec = DeploymentSpec.from_form(request.form, requested_by=current_actor())
    except ValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("web.deploy_form"))
    dep = current_app.deploy_service.create(spec, current_actor())
    flash(f"Deployment {dep.id} created ({dep.status.value}).", "success")
    return redirect(url_for("web.deployment_detail", dep_id=dep.id))


@web_bp.get("/deployments")
@login_required()
def deployments():
    return render_template("deployments.html",
                           deployments=current_app.store.list(),
                           role=session.get("role"))


@web_bp.get("/deployments/<dep_id>")
@login_required()
def deployment_detail(dep_id):
    dep = current_app.store.get(dep_id)
    if not dep:
        abort(404)
    dep = current_app.deploy_service.refresh_status(dep)
    return render_template("deployment_detail.html", dep=dep,
                           image=dep.spec.image, role=session.get("role"))


@web_bp.post("/deployments/<dep_id>/destroy")
@login_required(ROLE_ADMIN)
def deployment_destroy(dep_id):
    dep = current_app.store.get(dep_id)
    if not dep:
        abort(404)
    current_app.deploy_service.destroy(dep, current_actor())
    flash(f"Deployment {dep_id} destroyed.", "warning")
    return redirect(url_for("web.deployments"))


#
# Config generator -- der Ablauf der ersten Systronaut-Version (osaas):
#   OS-Auswahl  ->  Eingabemaske  ->  fertige Answer-Datei zum Kopieren.
# Rein rendernd: erzeugt dieselben Artefakte wie ein Deployment, legt aber
# nichts an und spricht keinen Hypervisor an.
@web_bp.get("/generate")
@login_required()
def generate_index():
    return render_template("generate.html",
                           images=catalog.all_images(),
                           role=session.get("role"))


@web_bp.get("/generate/<os_key>")
@login_required()
def generate_form(os_key):
    image = catalog.get_image(os_key)
    if image is None:
        abort(404)
    return render_template("generate_form.html",
                           image=image,
                           profiles=security.all_profiles(),
                           default_profile=security.DEFAULT_PROFILE,
                           role=session.get("role"))


@web_bp.post("/generate/<os_key>")
@login_required()
def generate_submit(os_key):
    image = catalog.get_image(os_key)
    if image is None:
        abort(404)
    # from_form erwartet os_key im Formular; der Pfad ist die Wahrheit.
    form = request.form.copy()
    form["os_key"] = os_key
    form.setdefault("provider", "pxe")
    try:
        spec = DeploymentSpec.from_form(form, requested_by=current_actor())
    except ValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("web.generate_form", os_key=os_key))

    compliance = security.evaluate(
        spec.security_profile, image,
        disk_passphrase=spec.install.disk_passphrase,
        package_role=spec.install.package_role,
    )
    artifacts = templating.render_host_artifacts(
        spec, compliance, templating.host_ip_default())
    return render_template("generate_output.html",
                           image=image, spec=spec, compliance=compliance,
                           artifacts=artifacts, role=session.get("role"))


@web_bp.get("/templates")
@login_required()
def templates_library():
    """Answer-file / provisioning-template library. Read-only, all users.

    Renders the OS-grouped tree; an optional ?path=<rel> selects one file to
    display inline (validated + confined by answer_files.read_file)."""
    selected = None
    rel = request.args.get("path", "")
    if rel:
        selected = answer_files.read_file(rel)
        if selected is None:
            flash("Answer file not found.", "warning")
    return render_template("templates.html",
                           groups=answer_files.list_groups(),
                           selected=selected,
                           role=session.get("role"))


@web_bp.get("/hypervisors")
@login_required()
def hypervisors_list():
    records = current_app.store.list_hypervisors()
    invs = [(r, hypervisors.inventory_for(r)) for r in records]
    connected = [i for _, i in invs if i.connected]
    totals = {
        "count": len(records),
        "connected": len(connected),
        "memory_mb": sum(i.memory_mb for i in connected),
        "storage_gb": sum(i.storage_gb for i in connected),
        "vms": sum(len(i.vms) for i in connected),
    }
    return render_template("hypervisors.html", invs=invs, totals=totals,
                           role=session.get("role"))


@web_bp.get("/hypervisors/add")
@login_required()
def hypervisor_add_form():
    return render_template("hypervisor_add.html", kinds=hypervisors.KINDS,
                           role=session.get("role"))


@web_bp.post("/hypervisors/add")
@login_required()
def hypervisor_add():
    f = request.form
    kind = f.get("kind", "")
    if kind not in hypervisors.KINDS:
        flash("Unknown hypervisor kind.", "danger")
        return redirect(url_for("web.hypervisor_add_form"))
    name = f.get("name", "").strip()
    host = f.get("host", "").strip()
    user = f.get("username", "").strip()
    password = f.get("password", "")
    if not (name and host and user):
        flash("Name, host and username are required.", "danger")
        return redirect(url_for("web.hypervisor_add_form"))
    cfg: dict = {}
    for key, _label, _req in hypervisors.KINDS[kind]["fields"]:
        val = f.get(f"cfg_{key}", "").strip()
        if val:
            cfg[key] = val
    if f.get("cfg_insecure"):
        cfg["insecure"] = "1"
    # Secret is encrypted before it ever touches the DB (see crypto.py).
    hv_id = current_app.store.add_hypervisor(
        name=name, kind=kind, host=host, username=user,
        secret_enc=crypto.encrypt(password), config=cfg, created_by=current_actor())
    current_app.store.audit(current_actor(), "hypervisor.add", hv_id, f"{kind} {host}")
    flash(f"Hypervisor '{name}' added.", "success")
    return redirect(url_for("web.hypervisor_detail", hv_id=hv_id))


@web_bp.get("/hypervisors/<hv_id>")
@login_required()
def hypervisor_detail(hv_id):
    rec = current_app.store.get_hypervisor(hv_id)
    if not rec:
        abort(404)
    inv = hypervisors.inventory_for(rec)
    tab = request.args.get("tab", "dashboard")
    if tab not in ("dashboard", "machines", "network", "settings", "console"):
        tab = "dashboard"
    # Seed a short sparkline history from the latest snapshot (no fake success).
    chart_cpu = _sparkline(inv.cpu_used_pct if inv.connected else 0.0, 12, jitter=0.15)
    chart_mem = _sparkline(float(inv.memory_used_mb) if inv.connected else 0.0, 12, jitter=0.08)
    return render_template(
        "hypervisor_detail.html",
        hv=rec, inv=inv, role=session.get("role"),
        active_tab=tab,
        net_fields=hypervisors.network_fields_for(rec.get("kind", "")),
        chart_cpu=",".join(f"{v:.2f}" for v in chart_cpu),
        chart_mem=",".join(f"{v:.2f}" for v in chart_mem),
    )


def _sparkline(latest: float, n: int = 12, jitter: float = 0.1) -> list[float]:
    """Deterministic-ish short series ending at `latest` for dashboard charts."""
    import math
    out: list[float] = []
    for i in range(n):
        t = (i + 1) / n
        wobble = 1.0 + jitter * math.sin(i * 1.7) * (1.0 - t)
        out.append(max(0.0, latest * t * wobble))
    if out:
        out[-1] = max(0.0, latest)
    return out


@web_bp.post("/hypervisors/<hv_id>/delete")
@login_required()
def hypervisor_delete(hv_id):
    rec = current_app.store.get_hypervisor(hv_id)
    if not rec:
        abort(404)
    current_app.store.delete_hypervisor(hv_id)
    current_app.store.audit(current_actor(), "hypervisor.delete", hv_id, rec.get("host", ""))
    flash("Hypervisor removed.", "warning")
    return redirect(url_for("web.hypervisors_list"))


@web_bp.get("/compliance")
@login_required()
def compliance():
    return render_template("compliance.html",
                           profiles=security.all_profiles(),
                           controls=security.CONTROLS,
                           role=session.get("role"))


@web_bp.get("/audit")
@login_required(ROLE_ADMIN)
def audit():
    return render_template("audit.html",
                           entries=current_app.store.audit_entries(),
                           role=session.get("role"))


@web_bp.get("/settings/pxe")
@login_required(ROLE_ADMIN)
def pxe_settings():
    """Read-only PXE infra knobs from env (Ansible/host .env) — no DB write."""
    pxe = {
        "host_ip": os.environ.get("PXE_HOST_IP", ""),
        "interface": os.environ.get("PXE_INTERFACE", ""),
        "subnet": os.environ.get("PXE_SUBNET", ""),
        "bootfile": os.environ.get("PXE_BOOTFILE", ""),
        "engine_url": current_app.config.get("PXE_ENGINE_URL", ""),
    }
    return render_template("pxe_settings.html", pxe=pxe, role=session.get("role"))
