# Author: Systronaut
# Web UI: SYSTRONAUT-styled console for end users (operator) and admins.
# Same look & feel as the original webapp, extended into a real deploy flow.

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, current_app, abort)

from ..auth import authenticate, login_required, current_actor, ROLE_ADMIN
from ..models import DeploymentSpec
from ..validators import ValidationError
from .. import catalog, security, providers, answer_files

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
