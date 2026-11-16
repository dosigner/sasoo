"""Compare a real Rust listener with the Python read-only list contract."""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

for name in list(os.environ):
    if any(part in name.upper() for part in ("API_KEY", "API_TOKEN", "SECRET", "PASSWORD")):
        os.environ.pop(name, None)
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
RUST, WORK = Path(sys.argv[1]), Path(sys.argv[2])
BACKEND = Path(__file__).resolve().parents[2] / "backend"
os.environ["SASOO_APP_DATA_ROOT"] = str(WORK / "oracle-app-data")
sys.path.insert(0, str(BACKEND))

import aiosqlite
from fastapi import FastAPI
import httpx
from api import papers
from models import database
from services import artifact_status, odl_parser

COUNTERS = {"refresh": 0, "write": 0, "external_socket": 0}
ORIGINAL_CONNECT = socket.socket.connect

def guarded_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "localhost", "::1"):
        COUNTERS["external_socket"] += 1
        raise AssertionError("External network is outside this synthetic HTTP gate")
    return ORIGINAL_CONNECT(sock, address)
socket.socket.connect = guarded_connect

def tripwire(kind):
    async def forbidden(*args, **kwargs):
        COUNTERS[kind] += 1
        raise AssertionError(f"Unexpected {kind}")
    return forbidden
papers.schedule_paper_artifacts_refresh = tripwire("refresh")
odl_parser.schedule_paper_artifacts_refresh = tripwire("refresh")
artifact_status.schedule_paper_artifacts_refresh = tripwire("refresh")
papers.execute_insert = tripwire("write")
papers.execute_update = tripwire("write")

def inventory(root):
    result = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            p = Path(parent) / name
            rel = str(p.relative_to(root))
            if p.is_symlink():
                result[rel] = {"symlink": os.readlink(p)}
            elif p.is_file():
                result[rel] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            else:
                result[rel] = {"directory": True}
    return result


def minimal_pdf():
    stream=b"BT /F1 12 Tf 60 720 Td (Synthetic fixture paper) Tj ET"
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"\nendstream"]
    output=bytearray(b"%PDF-1.4\n");offsets=[0]
    for number,body in enumerate(objects,1):
        offsets.append(len(output));output.extend(f"{number} 0 obj\n".encode()+body+b"\nendobj\n")
    xref=len(output);output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode());return bytes(output)


def seed(root, *, trap=False):
    root.mkdir(parents=True)
    (root / "library").mkdir()
    (root / ".sasoo-rust-isolated-fixture").write_text("synthetic-only\n")
    conn = sqlite3.connect(root / "sasoo.db")
    conn.executescript((Path(__file__).parent / "fixtures/legacy/schema.sql").read_text())
    conn.executescript("DROP TABLE settings; CREATE VIEW settings AS SELECT 'tripwire' AS key, no_settings_read_allowed() AS value;")
    mapping = json.loads((BACKEND / "agents/openalex_subfields.json").read_text())["subfields"]
    subfield = int(next(iter(mapping)))
    for number in range(1, 9):
        folder = root / "library" / f"paper-{number}"
        folder.mkdir()
        title = {2: "--- Page 1 ---", 4: "", 7: "short", 8: "https://example.invalid/file"}.get(number, f"Meaningful Fixture Paper {number}")
        conn.execute("INSERT INTO papers(id,title,authors,folder_name,status,domain,year,notes,tags,created_at,openalex_subfield_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (number,title,"Author needle" if number==1 else None,folder.name,"completed" if number%2 else "pending","optics" if number%2 else "general",2020+number,"note needle" if number==2 else None,"fixture tag needle" if number==3 else "fixture",f"2026-01-{number:02d}",subfield if number==1 else None))
        pdf = folder / ("Recovered_Title.pdf" if number==2 else f"Fixture_Source_{number}.pdf")
        if number == 4:
            continue
        pdf.write_bytes(minimal_pdf())
        stat = pdf.stat()
        signature = {"pdf_mtime_ns": stat.st_mtime_ns, "pdf_size": stat.st_size}
        manifest = {**signature,"requested_mode":"java","parser_version":"odl-v3","extraction_pipeline_version":"resolver_v1","resolver_version":"resolver-v1","full_text":"Synthetic fixture text","visual_artifacts_ready":True,"figures":[{"file_path":"figure.bin"}],"tables":[{"csv_path":"table.csv","html_path":"table.html"}],"pages":[{"raster_path":"page.bin"}],"markdown_file":"paper.md","json_file":"paper.json"}
        if number == 5:
            manifest["pdf_size"] += 1
        if number == 7:
            manifest.pop("visual_artifacts_ready")
        (folder / ".odl_manifest.json").write_text("{broken" if number==3 else json.dumps(manifest))
        (folder / ".text_cache.meta.json").write_text(json.dumps(signature))
        if number != 6:
            (folder / ".text_cache.txt").write_text("Synthetic fixture text")
        for name in ["figure.bin","table.csv","table.html","page.bin","paper.md","paper.json"]:
            if not (number==2 and name=="figure.bin"):
                (folder / name).write_bytes(b"synthetic artifact bytes")
        conn.execute("INSERT INTO figures(paper_id,figure_num,extraction_status) VALUES(?, '1', 'resolved')", (number,))
        conn.execute("INSERT INTO tables(paper_id,table_num,extraction_status) VALUES(?, '1', 'resolved')", (number,))
    if trap:
        outside = root.parent / (root.name + "-outside")
        outside.mkdir()
        (outside / "private.bin").write_bytes(b"must not be observed")
        (root / "library/trap").symlink_to(outside, target_is_directory=True)
        conn.execute("INSERT INTO papers(id,title,folder_name,status,domain,created_at) VALUES(99,'Trap outside page','trap','pending','trap','2099-01-01')")
    conn.commit()
    conn.close()


async def python_results(root, queries):
    database._db_connection = await aiosqlite.connect(f"file:{root / 'sasoo.db'}?mode=ro", uri=True)
    database._db_connection.row_factory = aiosqlite.Row
    database.get_library_root = lambda: root / "library"
    database.get_library_search_roots = lambda: (root / "library",)
    statements = []
    await database._db_connection.set_trace_callback(statements.append)
    app = FastAPI()
    app.include_router(papers.router)
    result = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False), base_url="http://oracle") as client:
        for query in queries:
            response = await client.get("/api/papers" + query)
            result.append((response.status_code, response.json() if response.headers.get("content-type","").startswith("application/json") else response.text))
    await database.close_db()
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for s in statements), statements
    assert not any("settings" in s.lower() for s in statements), statements
    return result, statements


def request(port, method, path, *, auth=True, headers=None):
    h = dict(headers or {})
    if auth:
        h["authorization"] = "Bearer synthetic-contract-token"
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    c.request(method, path, headers=h)
    r = c.getresponse()
    body = r.read()
    result = (r.status, dict(r.getheaders()), body)
    c.close()
    return result


def start(root, *, blocked=False):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, SASOO_RUST_ISOLATED_ROOT=str(root), SASOO_API_TOKEN="synthetic-contract-token", SASOO_ENV="production", SASOO_RUST_PDF_CANDIDATE="0")
    p = subprocess.Popen([str(RUST), "--host", "127.0.0.1", "--port", str(port)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    until = time.monotonic() + 8
    while time.monotonic() < until:
        if p.poll() is not None:
            out, err = p.communicate()
            if blocked:
                assert p.returncode != 0
                return None, {"exit":p.returncode,"message":err.decode()}
            raise AssertionError(f"Rust listener exited: {err.decode()}")
        try:
            if request(port,"GET","/health",auth=False)[0] == 200:
                if blocked:
                    p.terminate();p.communicate(timeout=3)
                    raise AssertionError("Unsupported root unexpectedly opened a listener")
                return (p,port), {"ready":True}
        except (OSError, http.client.HTTPException):
            time.sleep(0.03)
    p.terminate()
    p.communicate(timeout=3)
    raise AssertionError("Rust listener did not reach its bounded startup state")


def stop(handle):
    p, _ = handle
    p.terminate()
    p.communicate(timeout=5)


def run():
    WORK.mkdir(parents=True, exist_ok=True)
    normal = WORK / "normal"
    seed(normal)
    queries = ["","?page=2&page_size=3","?status=completed","?domain=general","?search=needle","?sort_by=bad&sort_order=sideways","?sort_by=title&sort_order=ASC","?sort_by=year&sort_order=asc","?page=99&page_size=2","?page=1.0&page_size=1_0","?page=%20%2B2%20&page_size=2","?page=1&page=2&page_size=2","?page=0&page_size=101","?page=9223372036854775807&page_size=100","?page=9223372036854775808","?page=9223372036854775808&page_size=1","?page=18446744073709551615&page_size=1","?page=18446744073709551616&page_size=1","?page=-9223372036854775809","?page=no","?page_size=1.2","?page=","?page=1.0_0","?page=1_0.0","?page=1.000_000","?page=%D9%A0%D9%A1","?page=%EF%BC%91","?page=1e0","?page=%091%0A","?page="+("9"*4301)]
    before = inventory(normal)
    expected, sql = asyncio.run(python_results(normal, queries))
    assert inventory(normal) == before, "Python read-only oracle changed the corpus"
    handle, startup = start(normal)
    opening = inventory(normal)
    assert opening == before, "Opening the Rust service changed files"
    checks = []
    route_checks = []
    try:
        for query, (status, body) in zip(queries, expected):
            got, _, raw = request(handle[1],"GET","/api/papers"+query)
            actual = json.loads(raw) if raw.startswith(b"{") else raw.decode()
            assert (got,actual) == (status,body), f"{query}: Rust {(got,actual)} != Python {(status,body)}"
            checks.append({"query":query,"status":got,"python_body":body,"rust_body":actual,"equal":True})
        for method,path,want in [("HEAD","/api/papers",405),("POST","/api/papers",405),("GET","/api/papers/1",501),("GET","/api/settings",501),("PUT","/api/settings",501),("GET","/api/analysis/1/figures",501),("POST","/api/analysis/1/figures/7/explain",501),("GET","/api/papers/1/pdf",501),("GET","/static/library/paper-1/figure.bin",501),("POST","/api/analysis/1/run",501),("POST","/api/analysis/1/chat",501)]:
            got,_,_=request(handle[1],method,path)
            assert got==want,(method,path,got,want)
            route_checks.append({"method":method,"path":path,"status":got})
        assert request(handle[1],"GET","/api/papers",auth=False)[0]==401
        got,headers,_=request(handle[1],"GET","/api/papers?page_size=1",headers={"Origin":"null"})
        assert got==200 and headers.get("access-control-allow-origin")=="null"
        got,headers,_=request(handle[1],"OPTIONS","/api/papers",auth=False,headers={"Origin":"null","Access-Control-Request-Method":"GET"})
        assert got==200 and headers.get("access-control-allow-origin")=="null"
        live=inventory(normal)
        assert live==before,"Live Rust requests changed files"
    finally:
        stop(handle)
    assert inventory(normal)==before,"Closing Rust changed files"
    record={"routes":route_checks,"auth_cors":{"unauthorized":401,"get_origin_null":200,"preflight":200,"head":405},"normal":{"queries":checks,"python_sql":sql,"opening":opening,"live":live,"after":inventory(normal),"before":before},"counters":COUNTERS.copy(),"blocked":[]}
    trap=WORK/"page-trap"
    seed(trap,trap=True)
    before=inventory(trap)
    handle,_=start(trap)
    try:
        got,_,raw=request(handle[1],"GET","/api/papers?sort_by=created_at&sort_order=asc&page_size=1")
        assert got==200,(got,raw)
        assert json.loads(raw)["total"]==9
        got,_,_=request(handle[1],"GET","/api/papers?domain=trap")
        assert got==403,got
        assert inventory(trap)==before
    finally:
        stop(handle)
    assert inventory(trap)==before
    for kind in ["folder-escape","absolute-artifact","symlink-artifact","missing-artifact"]:
        root=WORK/kind;seed(root);outside=WORK/(kind+"-outside");outside.mkdir();external=outside/"private.bin";external.write_bytes(b"outside bytes must remain unread")
        if kind=="folder-escape":
            conn=sqlite3.connect(root/"sasoo.db");conn.execute("UPDATE papers SET folder_name=? WHERE id=1",(str(outside),));conn.commit();conn.close()
        else:
            folder=root/"library/paper-1";manifest=json.loads((folder/".odl_manifest.json").read_text())
            if kind=="absolute-artifact":manifest["figures"][0]["file_path"]=str(external)
            elif kind=="symlink-artifact":(folder/"escape.bin").symlink_to(external);manifest["figures"][0]["file_path"]="escape.bin"
            else:manifest["figures"][0]["file_path"]="missing.bin"
            (folder/".odl_manifest.json").write_text(json.dumps(manifest))
        before=inventory(root);outside_before=inventory(outside);handle,_=start(root)
        try:
            got,_,raw=request(handle[1],"GET","/api/papers?sort_order=asc&page_size=1")
            assert got==(200 if kind=="missing-artifact" else 403),(kind,got,raw)
            if kind=="missing-artifact":assert json.loads(raw)["papers"][0]["visual_state"]=="partial"
        finally:stop(handle)
        assert inventory(root)==before and inventory(outside)==outside_before
        record.setdefault("containment",[]).append({"kind":kind,"status":got,"before":before,"after":inventory(root),"outside_before":outside_before,"outside_after":inventory(outside)})
    for kind in ["active","queued","history","wal-closed","wal-committed","rollback-sidecar","canonical-db-sidecar"]:
        root=WORK/kind
        seed(root)
        c=sqlite3.connect(root/"sasoo.db")
        if kind=="active": c.execute("UPDATE papers SET status='analyzing' WHERE id=1")
        elif kind=="queued": c.execute("INSERT INTO analysis_runs(paper_id,status) VALUES(1,'queued')")
        elif kind=="history": c.executescript("CREATE TABLE runtime_executions(execution_id TEXT); INSERT INTO runtime_executions VALUES('historical')")
        elif kind.startswith("wal"):
            c.commit();c.execute("PRAGMA journal_mode=WAL")
            if kind=="wal-committed":c.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE,True)
            c.execute("UPDATE papers SET notes='committed WAL row' WHERE id=1")
        c.commit()
        active_writer=kind=="wal-committed"
        if not active_writer:c.close()
        if kind=="rollback-sidecar": (root/"sasoo.db-journal").write_bytes(b"synthetic hot journal must not be opened")
        if kind=="canonical-db-sidecar":
            (root/"sasoo.db").rename(root/"canonical.db");(root/"sasoo.db").symlink_to("canonical.db");(root/"canonical.db-journal").write_bytes(b"synthetic recovery sidecar must not be ignored")
        before=inventory(root)
        if kind.startswith("wal") or kind in ("rollback-sidecar","canonical-db-sidecar"):
            _,result=start(root,blocked=True)
        else:
            handle,result=start(root)
            try:assert request(handle[1],"GET","/api/papers")[0]==501
            finally:stop(handle)
        assert inventory(root)==before,(kind,"changed corpus")
        record["blocked"].append({"kind":kind,"startup":result,"before":before,"after":inventory(root)})
        if active_writer:
            c.close();assert inventory(root)==before,"Fixture close must retain committed WAL evidence"
    for name,value in [("roman-title","Ⅷ"*8),("combining-title","\u0345"*8),("hangul-title","정상적인 한글 논문 제목")]+[(f"separator-{n:04x}",f"Meaningful{chr(n)}Fixture Title") for n in range(0x1c,0x20)]:
        root=WORK/name;seed(root);conn=sqlite3.connect(root/"sasoo.db");conn.execute("UPDATE papers SET title=? WHERE id=1",(value,));conn.commit();conn.close();before=inventory(root);expected,_=asyncio.run(python_results(root,["?sort_by=created_at&sort_order=asc&page_size=1"]));handle,_=start(root)
        try:
            got,_,raw=request(handle[1],"GET","/api/papers?sort_by=created_at&sort_order=asc&page_size=1");actual=json.loads(raw);assert (got,actual)==expected[0],(name,(got,actual),expected[0])
        finally:stop(handle)
        assert inventory(root)==before
        record.setdefault("title_cases",[]).append({"case":name,"input":value,"title":actual["papers"][0]["title"],"equal":True,"before":before,"after":inventory(root)})
    for kind in ["manifest-array","manifest-string","cachemeta-array","cachemeta-null","cachemeta-empty-array","numeric-contract-path","numeric-json-path","numeric-figure-path","numeric-table-path","numeric-page-path","boolean-contract-path","float-contract-path","array-contract-path","manifest-invalid-utf8","cachemeta-invalid-utf8"]:
        root=WORK/kind;seed(root);folder=root/"library/paper-1"
        if "-path" in kind:
            manifest=json.loads((folder/".odl_manifest.json").read_text());value={"boolean-contract-path":True,"float-contract-path":0.00001,"array-contract-path":["a'b"]}.get(kind,123)
            if kind=="numeric-json-path":manifest["json_file"]=value
            elif kind=="numeric-figure-path":manifest["figures"][0]["file_path"]=value
            elif kind=="numeric-table-path":manifest["tables"][0]["csv_path"]=value
            elif kind=="numeric-page-path":manifest["pages"][0]["raster_path"]=value
            else:manifest["markdown_file"]=value
            (folder/str(value)).write_text("existing artifact");(folder/".odl_manifest.json").write_text(json.dumps(manifest))
        elif kind.endswith("invalid-utf8"):
            (folder/(".text_cache.meta.json" if kind.startswith("cachemeta") else ".odl_manifest.json")).write_bytes(b"\xff")
        else:
            value="wrong shape" if kind=="manifest-string" else (None if kind=="cachemeta-null" else ([] if kind=="cachemeta-empty-array" else [1]))
            (folder/(".text_cache.meta.json" if kind.startswith("cachemeta") else ".odl_manifest.json")).write_text(json.dumps(value))
        before=inventory(root);expected,_=asyncio.run(python_results(root,["?sort_order=asc&page_size=1"]));handle,_=start(root)
        try:
            got,_,raw=request(handle[1],"GET","/api/papers?sort_order=asc&page_size=1");actual=json.loads(raw) if raw.startswith(b"{") else raw.decode();assert (got,actual)==expected[0],(kind,(got,actual),expected[0])
        finally:stop(handle)
        assert inventory(root)==before
        record.setdefault("malformed_shape",[]).append({"kind":kind,"status":got,"equal":True,"before":before,"after":inventory(root)})
    for kind in ["unmarked-empty","invalid-marker-empty","symlink-marker-empty"]:
        root=WORK/kind;root.mkdir()
        if kind=="invalid-marker-empty":(root/".sasoo-rust-isolated-fixture").write_text("invalid\n")
        if kind=="symlink-marker-empty":
            target=WORK/"external-marker";target.write_text("synthetic-only\n");(root/".sasoo-rust-isolated-fixture").symlink_to(target)
        before=inventory(root);_,result=start(root,blocked=True);assert inventory(root)==before
        record.setdefault("marker_startup",[]).append({"kind":kind,"result":result,"before":before,"after":inventory(root)})
    shell=WORK/"empty-shell";shell.mkdir();(shell/".sasoo-rust-isolated-fixture").write_text("synthetic-only\n");before=inventory(shell);handle,_=start(shell)
    try:assert request(handle[1],"GET","/api/papers")[0]==501
    finally:stop(handle)
    assert inventory(shell)==before
    record["empty_shell"]={"status":501,"before":before,"after":inventory(shell)}
    import importlib.metadata
    record["runtime"]={"python":sys.version,"sqlite":sqlite3.sqlite_version,"rust_binary_sha256":hashlib.sha256(RUST.read_bytes()).hexdigest(),"packages":{name:importlib.metadata.version(name) for name in ["fastapi","pydantic","httpx","aiosqlite","PyMuPDF"]}}
    record["source_sha256"]={str(p.relative_to(BACKEND.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [BACKEND/"api/papers.py",BACKEND/"models/schemas.py",BACKEND/"services/odl_parser.py",BACKEND/"services/artifact_status.py",BACKEND/"services/openalex.py",BACKEND/"agents/openalex_subfields.json"]}
    assert COUNTERS=={"refresh":0,"write":0,"external_socket":0},COUNTERS
    record["counters"]=COUNTERS.copy()
    path=WORK/"receipt.json"
    path.write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n")
    print(f"PHASE17_RECEIPT={path}")
    print(f"Python/Rust real HTTP parity {len(queries)} queries; guards{len(record["blocked"])}; writes0; external sockets0")

if __name__ == "__main__":run()
