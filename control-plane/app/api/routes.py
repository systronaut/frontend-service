# Author: Systronaut
# REST API (v1). Bearer-token auth; all input validated via models/validators.
# Mirrors the web UI so automation has parity with the console.

from flask import Blueprint, jsonify, request, current_app

from ..auth import api_auth, current_actor, ROLE_ADMIN
from ..models import DeploymentSpec
from ..validators import ValidationError
from .. import catalog, security, providers, version

api_bp = Blueprint("api", __name__)


@api_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@api_bp.get("/version")
@api_auth()
def get_version():
    return jsonify(version.check())


@api_bp.get("/catalog")
@api_auth()
def get_catalog():
    return jsonify({"images": [
        {"key": i.key, "label": i.label, "family": i.family, "distro": i.distro,
         "version": i.version, "firmware": i.firmware, "notes": i.notes}
        for i in catalog.all_images()
    ]})


@api_bp.get("/profiles")
@api_auth()
def get_profiles():
    return jsonify({"profiles": [
        {"name": p.name, "label": p.label, "description": p.description,
         "standards": list(p.standards),
         "controls": [{"id": c.id, "title": c.title,
                       "iso27001": list(c.iso27001), "nis2": list(c.nis2)}
                      for c in p.controls()]}
        for p in security.all_profiles()
    ]})


@api_bp.get("/providers")
@api_auth()
def get_providers():
    return jsonify({"providers": [
        {"name": name, "implemented": p.implemented}
        for name, p in providers.available().items()
    ]})


@api_bp.post("/deployments")
@api_auth()
def create_deployment():
    form = request.get_json(silent=True) or request.form
    try:
        spec = DeploymentSpec.from_form(form, requested_by=current_actor())
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    dep = current_app.deploy_service.create(spec, current_actor())
    return jsonify(dep.to_dict()), 201


@api_bp.get("/deployments")
@api_auth()
def list_deployments():
    deps = current_app.store.list()
    return jsonify({"deployments": [d.to_dict() for d in deps]})


@api_bp.get("/deployments/<dep_id>")
@api_auth()
def get_deployment(dep_id):
    dep = current_app.store.get(dep_id)
    if not dep:
        return jsonify({"error": "not found"}), 404
    dep = current_app.deploy_service.refresh_status(dep)
    return jsonify(dep.to_dict())


@api_bp.get("/deployments/<dep_id>/compliance")
@api_auth()
def deployment_compliance(dep_id):
    dep = current_app.store.get(dep_id)
    if not dep:
        return jsonify({"error": "not found"}), 404
    return jsonify(dep.compliance_evidence)


@api_bp.delete("/deployments/<dep_id>")
@api_auth(ROLE_ADMIN)
def destroy_deployment(dep_id):
    dep = current_app.store.get(dep_id)
    if not dep:
        return jsonify({"error": "not found"}), 404
    dep = current_app.deploy_service.destroy(dep, current_actor())
    return jsonify(dep.to_dict())


@api_bp.get("/audit")
@api_auth(ROLE_ADMIN)
def audit():
    return jsonify({"entries": current_app.store.audit_entries()})
