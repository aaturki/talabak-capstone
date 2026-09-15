"""Loopback demo UI. Personas are explicit fixtures, not production login."""
from __future__ import annotations
import json
import secrets
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from .domain import ROOT, Session, Store
from .llm import SDKClient
from .mock_gateway import running_gateway
from .pipeline import Application


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1,max_length=6000)


class PersonaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: str


def create_app(database=None):
    sessions = {}
    lock = threading.RLock()
    store = Store(database or ":memory:")
    context = {}

    @asynccontextmanager
    async def lifespan(app):
        with running_gateway() as url:
            config = json.loads((ROOT / "config/models.json").read_text())
            for route in config["routes"].values(): route["base_url"] = url
            context["client"] = SDKClient(config=config)
            yield
            context["client"].close()
        store.close()

    app = FastAPI(title="طلبك | Talabak", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def local_origin(request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return Response(status_code=403)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return Response(status_code=403)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return Response(status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def current(request, response):
        token = request.cookies.get("talabak_session")
        if token not in sessions:
            token = secrets.token_urlsafe(32)
            session = Session()
            sessions[token] = (session, Application(context["client"], store, audit_path=ROOT / "runtime/audit.jsonl"))
            response.set_cookie("talabak_session", token, httponly=True, samesite="strict", max_age=3600)
        return sessions[token]

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web/index.html")

    @app.get("/api/state")
    def state(request:Request, response:Response):
        with lock:
            session, _ = current(request,response)
            catalog = store.lookup_catalog(session)
            return {"mode":"simulator", "customer":session.customer_id, "can_act":session.can_act,
                    "orders":[{k:row[k] for k in ("id","sku","status")} for row in store.db.execute("SELECT * FROM orders WHERE customer_id=?",(session.customer_id,))],
                    "catalog":catalog["products"], "slots":catalog["slots"], "actions":store.count_actions()}

    @app.post("/api/chat")
    def chat(body:ChatBody,request:Request,response:Response):
        with lock:
            session, application = current(request,response)
            return application.handle_message(body.message,session).to_dict()

    @app.post("/api/persona")
    def persona(body:PersonaBody,request:Request,response:Response):
        profiles = {"customer_a":("CUST-A",True),"customer_b":("CUST-B",True),"read_only":("CUST-A",False),"guest":(None,False)}
        if body.persona not in profiles:
            raise HTTPException(400,"Unknown demo persona")
        with lock:
            old = request.cookies.get("talabak_session")
            if old in sessions: sessions.pop(old)
            token = secrets.token_urlsafe(32)
            customer, can_act = profiles[body.persona]
            session = Session(customer_id=customer,can_act=can_act)
            sessions[token] = (session,Application(context["client"],store,audit_path=ROOT / "runtime/audit.jsonl"))
            response.set_cookie("talabak_session",token,httponly=True,samesite="strict",max_age=3600)
            return {"customer":customer,"can_act":can_act}

    return app


app = create_app()
