import json
import math
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from rules import judge

SECRET = os.environ.get("JWT_SECRET", "herb-process-dev-secret")
DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54393/herb")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "processor": {"role": "writer", "password_hash": pwd.hash("herb123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class StepIn(BaseModel):
    name: str
    temp_c: float
    minutes: float


class BatchIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    steps: list[StepIn]


class TargetIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    target_minutes: int = Field(ge=0, le=1440)


class SoakStartIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅炮制员可写入记录")
    return user


app = FastAPI(title="饮片炮制记录台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batches (
                id serial PRIMARY KEY,
                herb text NOT NULL,
                doc jsonb NOT NULL,
                verdict text NOT NULL,
                reason text NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS soak_targets (
                herb text PRIMARY KEY,
                target_minutes integer NOT NULL,
                updated_by text NOT NULL,
                updated_at timestamptz NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS soaks (
                id serial PRIMARY KEY,
                herb text NOT NULL,
                target_minutes integer NOT NULL,
                started_at timestamptz NOT NULL,
                started_by text NOT NULL,
                used_at timestamptz
            )"""
        )
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("甘草", {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
            ]
            for herb, doc in samples:
                verdict, reason = judge(doc)
                conn.execute(
                    """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
                       VALUES (%s, %s::jsonb, %s, %s, %s, %s)""",
                    (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, "processor", now),
                )
        conn.commit()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "herb-process-record"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/batches")
def list_batches(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute("SELECT id, herb, doc, verdict, reason, created_by FROM batches ORDER BY id DESC").fetchall()
    return rows


def soak_status(row: dict, now: datetime) -> dict:
    elapsed_seconds = max(0.0, (now - row["started_at"]).total_seconds())
    remaining = math.ceil((row["target_minutes"] * 60 - elapsed_seconds) / 60)
    remaining = max(0, remaining)
    return {
        **row,
        "elapsed_minutes": int(elapsed_seconds // 60),
        "remaining_minutes": remaining,
        "ready": remaining == 0,
    }


def active_soak(conn, herb: str) -> dict | None:
    return conn.execute(
        "SELECT id, herb, target_minutes, started_at, started_by FROM soaks WHERE herb = %s AND used_at IS NULL ORDER BY id DESC LIMIT 1",
        (herb,),
    ).fetchone()


@app.get("/api/soaks")
def list_soaks(_user: dict = Depends(current_user)):
    now = datetime.now(timezone.utc)
    with connect() as conn:
        targets = conn.execute(
            "SELECT herb, target_minutes, updated_by, updated_at FROM soak_targets ORDER BY herb"
        ).fetchall()
        rows = conn.execute(
            "SELECT id, herb, target_minutes, started_at, started_by FROM soaks WHERE used_at IS NULL ORDER BY id DESC"
        ).fetchall()
    return {
        "server_now": now,
        "targets": targets,
        "active": [soak_status(r, now) for r in rows],
    }


@app.put("/api/soaks/targets")
def set_soak_target(body: TargetIn, user: dict = Depends(require_writer)):
    herb = body.herb.strip()
    with connect() as conn:
        conn.execute(
            """INSERT INTO soak_targets (herb, target_minutes, updated_by, updated_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (herb) DO UPDATE SET
                   target_minutes = EXCLUDED.target_minutes,
                   updated_by = EXCLUDED.updated_by,
                   updated_at = EXCLUDED.updated_at""",
            (herb, body.target_minutes, user["username"], datetime.now(timezone.utc)),
        )
        conn.commit()
    return {"herb": herb, "target_minutes": body.target_minutes}


@app.post("/api/soaks/start", status_code=201)
def start_soak(body: SoakStartIn, user: dict = Depends(require_writer)):
    herb = body.herb.strip()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        target = conn.execute("SELECT target_minutes FROM soak_targets WHERE herb = %s", (herb,)).fetchone()
        if target is None:
            raise HTTPException(status_code=409, detail="请先在浸泡台为该味设置浸泡目标分钟")
        if active_soak(conn, herb) is not None:
            raise HTTPException(status_code=409, detail="该味已有进行中的浸泡")
        row = conn.execute(
            """INSERT INTO soaks (herb, target_minutes, started_at, started_by)
               VALUES (%s, %s, %s, %s)
               RETURNING id, herb, target_minutes, started_at, started_by""",
            (herb, target["target_minutes"], now, user["username"]),
        ).fetchone()
        conn.commit()
    return soak_status(row, now)


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, user: dict = Depends(require_writer)):
    doc = {"steps": [s.model_dump() for s in body.steps]}
    herb = body.herb.strip()
    now = datetime.now(timezone.utc)
    soak = None
    with connect() as conn:
        if any(s.name == "清炒" for s in body.steps):
            soak = active_soak(conn, herb)
            if soak is None:
                raise HTTPException(status_code=409, detail="该味尚未登记浸泡，请先在浸泡台开始浸泡")
            remaining = math.ceil((soak["target_minutes"] * 60 - (now - soak["started_at"]).total_seconds()) / 60)
            if remaining > 0:
                raise HTTPException(status_code=409, detail=f"浸泡未满，还差 {remaining} 分钟")
        verdict, reason = judge(doc)
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, created_by""",
            (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, user["username"], now),
        ).fetchone()
        if soak is not None:
            conn.execute("UPDATE soaks SET used_at = %s WHERE id = %s", (now, soak["id"]))
        conn.commit()
    return row
