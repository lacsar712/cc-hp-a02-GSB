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


class SoakTargetIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    target_minutes: int = Field(ge=0, le=10080)


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
                target_minutes integer NOT NULL CHECK (target_minutes >= 0),
                updated_by text NOT NULL,
                updated_at timestamptz NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS soak_sessions (
                herb text PRIMARY KEY,
                target_minutes integer NOT NULL,
                started_by text NOT NULL,
                started_at timestamptz NOT NULL
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


def soak_progress(row: dict, now: datetime) -> dict:
    elapsed = max(0.0, (now - row["started_at"]).total_seconds())
    remaining = max(0.0, row["target_minutes"] * 60 - elapsed)
    return {
        "herb": row["herb"],
        "target_minutes": row["target_minutes"],
        "started_by": row["started_by"],
        "started_at": row["started_at"].isoformat(),
        "elapsed_seconds": int(elapsed),
        "remaining_seconds": math.ceil(remaining) if remaining > 0 else 0,
        "ready": remaining <= 0,
    }


def soak_block_reason(herb: str, session: dict | None, now: datetime) -> str | None:
    """返回阻止开炒的原因；可以开炒时返回 None。"""
    if session is None:
        return f"{herb} 未登记浸泡，清炒前须先在浸泡台开始浸泡"
    elapsed = (now - session["started_at"]).total_seconds()
    remaining = session["target_minutes"] * 60 - elapsed
    if remaining > 0:
        return f"{herb} 浸泡未满，还差 {math.ceil(remaining / 60)} 分钟"
    return None


@app.get("/api/soaks")
def list_soaks(_user: dict = Depends(current_user)):
    now = datetime.now(timezone.utc)
    with connect() as conn:
        targets = conn.execute(
            "SELECT herb, target_minutes, updated_by, updated_at FROM soak_targets ORDER BY herb"
        ).fetchall()
        sessions = conn.execute(
            "SELECT herb, target_minutes, started_by, started_at FROM soak_sessions ORDER BY started_at"
        ).fetchall()
    return {
        "server_now": now.isoformat(),
        "targets": [
            {**t, "updated_at": t["updated_at"].isoformat()} for t in targets
        ],
        "sessions": [soak_progress(s, now) for s in sessions],
    }


@app.put("/api/soaks/target")
def set_soak_target(body: SoakTargetIn, user: dict = Depends(require_writer)):
    herb = body.herb.strip()
    if not herb:
        raise HTTPException(status_code=400, detail="饮片名不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute(
            """INSERT INTO soak_targets (herb, target_minutes, updated_by, updated_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (herb) DO UPDATE SET
                   target_minutes = EXCLUDED.target_minutes,
                   updated_by = EXCLUDED.updated_by,
                   updated_at = EXCLUDED.updated_at""",
            (herb, body.target_minutes, user["username"], now),
        )
        conn.commit()
    return {"herb": herb, "target_minutes": body.target_minutes}


@app.post("/api/soaks/start", status_code=201)
def start_soak(body: SoakStartIn, user: dict = Depends(require_writer)):
    herb = body.herb.strip()
    if not herb:
        raise HTTPException(status_code=400, detail="饮片名不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        target = conn.execute(
            "SELECT target_minutes FROM soak_targets WHERE herb = %s", (herb,)
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=400, detail=f"{herb} 尚未设置浸泡目标分钟")
        existing = conn.execute(
            "SELECT herb FROM soak_sessions WHERE herb = %s", (herb,)
        ).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"{herb} 已在浸泡中")
        conn.execute(
            """INSERT INTO soak_sessions (herb, target_minutes, started_by, started_at)
               VALUES (%s, %s, %s, %s)""",
            (herb, target["target_minutes"], user["username"], now),
        )
        conn.commit()
    return {"herb": herb, "target_minutes": target["target_minutes"], "started_at": now.isoformat()}


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, user: dict = Depends(require_writer)):
    doc = {"steps": [s.model_dump() for s in body.steps]}
    verdict, reason = judge(doc)
    herb = body.herb.strip()
    now = datetime.now(timezone.utc)
    has_fry = any(s.name == "清炒" for s in body.steps)
    with connect() as conn:
        if has_fry:
            session = conn.execute(
                "SELECT herb, target_minutes, started_at FROM soak_sessions WHERE herb = %s",
                (herb,),
            ).fetchone()
            blocked = soak_block_reason(herb, session, now)
            if blocked is not None:
                raise HTTPException(status_code=400, detail=blocked)
            conn.execute("DELETE FROM soak_sessions WHERE herb = %s", (herb,))
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, created_by""",
            (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, user["username"], now),
        ).fetchone()
        conn.commit()
    return row
