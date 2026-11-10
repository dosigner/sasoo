from pathlib import Path
import json
import os
import subprocess
import sys

RUN = Path(__file__).resolve().parent
WORKSPACE = Path('/Users/dongj/dev/논문_사수_개발중')
PYTHON = WORKSPACE / 'sasoo/backend/.venv/bin/python'

def main():
    tree, action = sys.argv[1:3]
    backend = RUN / tree / 'sasoo/backend'
    state = RUN / 'state' / f'{tree}-{action}'
    for part in ['home', 'app-data', 'tmp', 'java-tmp']:
        (state / part).mkdir(parents=True, exist_ok=True)
    env = {
        'PATH': f'{backend}/java-runtime/bin:{PYTHON.parent}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
        'HOME': str(state / 'home'),
        'TMPDIR': str(state / 'tmp'),
        'SASOO_APP_DATA_ROOT': str(state / 'app-data'),
        'JAVA_HOME': str(backend / 'java-runtime'),
        'SASOO_JAVA_HOME': str(backend / 'java-runtime'),
        'JAVA_TOOL_OPTIONS': f'-Djava.awt.headless=true -Djava.io.tmpdir={state / "java-tmp"}',
        'MPLCONFIGDIR': str(state / 'home/matplotlib'),
        'PYTHONNOUSERSITE': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
        'LANG': 'en_US.UTF-8',
    }
    assert not (backend / '.env').exists()
    if action == 'probe':
        code = '''import errno, socket, pathlib
with socket.socket() as s:
    s.settimeout(1)
    result = s.connect_ex(('192.0.2.1', 443))
    assert result in (errno.EPERM, errno.EACCES), result
    print('OS external connection denied:', result)
with socket.socket() as server:
    server.bind(('127.0.0.1', 0)); server.listen()
    with socket.socket() as client:
        client.connect(server.getsockname())
        connection, _ = server.accept(); connection.close()
    print('OS loopback allowed')
path = 'probe.sock'
with socket.socket(socket.AF_UNIX) as server:
    server.bind(path); server.listen()
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(path)
        connection, _ = server.accept(); connection.close()
pathlib.Path(path).unlink()
print('OS Unix socket allowed')
try:
    pathlib.Path('/private/tmp/sasoo-r1-write-probe-denied').write_text('probe')
except PermissionError:
    print('OS write outside task root denied')
else:
    raise AssertionError('Outside write unexpectedly allowed')
import platform, fastapi, pydantic
print('Versions:', platform.python_version(), fastapi.__version__, pydantic.__version__)
'''
        args = ['-c', code]
    elif action == 'focused':
        args = ['-m', 'pytest', 'api/test_report_bytes_contract.py', 'api/test_report_service.py', 'api/test_analysis_routes.py', 'api/test_openapi_contract_snapshot.py', '--disable-warnings', '-q']
    elif action == 'full':
        args = ['-m', 'pytest', 'services', 'api', 'models', 'tools', '--disable-warnings', '-q']
    elif action == 'compile':
        args = ['-m', 'py_compile', 'main.py', 'api/analysis_routes.py', 'api/report_service.py']
    else:
        raise ValueError(action)
    command = ['/usr/bin/sandbox-exec', '-f', str(RUN / 'sandbox.sb'), str(PYTHON), *args]
    log = RUN / f'{tree}-{action}.log'
    print('Running', tree, action, 'log:', log, flush=True)
    with log.open('w') as output:
        result = subprocess.run(command, cwd=backend, env=env, stdout=output, stderr=subprocess.STDOUT)
    print(log.read_text()[-9000:], flush=True)
    raise SystemExit(result.returncode)

if __name__ == '__main__':
    main()
