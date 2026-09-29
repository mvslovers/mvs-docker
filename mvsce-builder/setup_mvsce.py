#!/usr/bin/env python3
"""Refresh UFSD, HTTPD and mvsMF on MVS/CE 3.x and enable their autostart.

MVS/CE 3.0.0 already installs UFSD, HTTPD and mvsMF through MVP, but does
not start them. The MVP install provides everything this image needs apart
from the load modules themselves:

  MVSLOVER.UFSD.LOADLIB        UFSD load library (STEPLIB of the UFSD procs)
  HTTPD.LINKLIB                HTTPD load library, mvsMF lives in it too
  SYS2.PROCLIB(UFSD,UFSDCLNP)  STC procedures
  SYS2.PROCLIB(HTTPD)          STC procedure, incl. HASPCKPT/HASPACE1
  SYS2.PARMLIB(UFSDPRM0)       mounts /, /www, /tmp and the user homes
  UFSD.ROOT, HTTPD.WEBROOT,
  UFSD.SCRATCH, *.UFSHOME      the UFS disks

This script:

  1. RECEIVEs the release XMITs from /tmp and IEBCOPYs their members, with
     replace, into the existing load libraries.
  2. Writes SYS2.PARMLIB(HTTPPRM0) in the form mvsMF documents.
  3. Adds S UFSD / S HTTPD to SYS1.PARMLIB(COMMND00).
  4. Starts both and checks what is actually running: the UFSD000I and
     HTTPD000I banners against UFSD_VERSION / HTTPD_VERSION, and
     /zosmf/test?fn=version against MVSMF_VERSION.
     A build that installed nothing therefore fails instead of publishing
     the previous level.
  5. Purges the spool and shuts MVS down with MVS/CE's own SHUTFAST.

Run from /MVSCE with the DASDs at DASD/*.
"""
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

EBCDIC_PORT = 3506
ASCII_PORT = 3505
HTTP_PORT = 8080
HERCULES_TIMEOUT = 300  # seconds to wait for MVS IPL
JOB_TIMEOUT = 180       # seconds to wait for a single job
START_TIMEOUT = 120     # seconds to wait for an STC banner
SHUTDOWN_TIMEOUT = 300  # seconds for SHUTFAST to quit Hercules

USER = 'IBMUSER'
PASSWORD = 'SYS1'

LOGFILE = '/tmp/hercules-build.log'

# (xmit file, job name, target load library)
MODULES = [
    ('/tmp/ufsd.xmit',  'UFSDRCV',  'MVSLOVER.UFSD.LOADLIB'),
    ('/tmp/httpd.xmit', 'HTTPDRCV', 'HTTPD.LINKLIB'),
    ('/tmp/mvsmf.xmit', 'MVSMFRCV', 'HTTPD.LINKLIB'),
]

# The z/OSMF routes as mvsMF 1.1.0 documents them: the two endpoints that
# resolve the caller themselves are public, everything else needs a login
# and answers a bare 401 (no browser dialog) without one.
HTTPPRM0 = """\
# HTTPPRM0 - written by mvsce-builder (mvslovers/mvs-docker)
PORT=8080
DOCROOT=/www
MOD=MVSMF /zosmf/info                    AUTH=NONE
MOD=MVSMF /zosmf/services/authenticate   AUTH=NONE
MOD=MVSMF /zosmf/*                       AUTH=TOKEN
"""

JOBCARD = """//{name:<8} JOB (TSO),'{title}',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER={user},PASSWORD={pw}"""

# BREXX, the way MVS/CE's own MVP procedure runs it
BREXX_DDS = """//TSOLIB   DD DSN=BREXX.CURRENT.RXLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.CURRENT.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY"""


def log(msg):
    elapsed = time.time() - START_TIME
    print(f'[setup {elapsed:6.1f}s] {msg}', flush=True)


def jobcard(name, title):
    return JOBCARD.format(name=name, title=title[:20], user=USER, pw=PASSWORD)


def wait_for_port(port, timeout=60):
    """Wait until a TCP port is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def read_log():
    try:
        with open(LOGFILE, 'r', errors='replace') as f:
            return f.read()
    except FileNotFoundError:
        return ''


def wait_for_string(target, timeout=HERCULES_TIMEOUT, since=0):
    """Wait for a string to appear in the Hercules log after offset since."""
    start = time.time()
    while time.time() - start < timeout:
        if target in read_log()[since:]:
            return True
        time.sleep(2)
    return False


def dump_log_tail(lines=20):
    content = read_log().splitlines()
    log(f'  log tail ({len(content)} lines total):')
    for l in content[-lines:]:
        print(f'    | {l}', flush=True)


def fail(herc, msg):
    log(f'ERROR: {msg}')
    dump_log_tail()
    herc.kill()
    sys.exit(1)


def cards(text):
    """JCL text as 80-byte EBCDIC card images."""
    return b''.join('{:80}'.format(l).encode('cp500')
                    for l in text.strip('\n').splitlines())


def pick_delimiter(data):
    """A DLM= value that does not start any 80-byte card of the payload."""
    heads = {data[i:i + 2] for i in range(0, len(data), 80)}
    for dlm in ('$$', '##', '@@', '%%', '++'):
        if dlm.encode('cp500') not in heads:
            return dlm
    raise RuntimeError('no usable in-stream delimiter for the XMIT')


def submit_ascii(jcl):
    """Submit JCL via the ASCII card reader."""
    with socket.create_connection(('127.0.0.1', ASCII_PORT)) as sock:
        sock.sendall(jcl.encode())


def submit_ebcdic(data):
    """Submit card images via the EBCDIC card reader (binary safe)."""
    with socket.create_connection(('127.0.0.1', EBCDIC_PORT)) as sock:
        sock.sendall(data)


def run_job(herc, name, submit):
    """Submit a job and wait for its $HASP395."""
    since = len(read_log())
    submit()
    if not wait_for_string(f'$HASP395 {name}', JOB_TIMEOUT, since):
        fail(herc, f'job {name} did not complete')
    log(f'  {name} ended')
    time.sleep(2)


def brexx_job(name, title, rexx):
    return f"""{jobcard(name, title)}
//REXX     EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
{rexx.strip()}
##
{BREXX_DDS}
"""


def install_modules(herc, xmit, name, target):
    """RECEIVE an XMIT into a temporary library, copy it over target."""
    with open(xmit, 'rb') as f:
        data = f.read()
    if len(data) == 0 or len(data) % 80:
        fail(herc, f'{xmit}: {len(data)} bytes is not a card-image XMIT')
    dlm = pick_delimiter(data)
    log(f'Installing {os.path.basename(xmit)} ({len(data)} bytes) '
        f'into {target}...')

    head = f"""{jobcard(name, 'RECV ' + name[:-3])}
//RECV     EXEC PGM=RECV370,REGION=6144K
//STEPLIB  DD DSN=SYSC.LINKLIB,DISP=SHR
//RECVLOG  DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=&&SYSUT1,UNIT=SYSALLDA,VOL=SER=PUB001,
//            SPACE=(TRK,(250,250)),DISP=(NEW,DELETE,DELETE)
//SYSUT2   DD DSN=&&LOAD,UNIT=SYSALLDA,VOL=SER=PUB001,
//            SPACE=(TRK,(100,50,20)),DISP=(NEW,PASS,DELETE)
//XMITIN   DD DATA,DLM={dlm}
"""
    tail = f"""{dlm}
//COPY     EXEC PGM=IEBCOPY,COND=(0,NE)
//SYSPRINT DD SYSOUT=*
//IN       DD DSN=&&LOAD,DISP=(OLD,DELETE)
//OUT      DD DSN={target},DISP=OLD
//SYSUT3   DD UNIT=SYSALLDA,SPACE=(80,(60,45))
//SYSUT4   DD UNIT=SYSALLDA,SPACE=(256,(15,1)),DCB=KEYLEN=8
//SYSIN    DD *
  COPY OUTDD=OUT,INDD=((IN,R))
/*
"""
    run_job(herc, name, lambda: submit_ebcdic(cards(head) + data + cards(tail)))


def write_httpprm0(herc):
    log('Writing SYS2.PARMLIB(HTTPPRM0)...')
    jcl = f"""{jobcard('HTTPPRM', 'HTTPPRM0')}
//WRITE    EXEC PGM=IEBGENER
//SYSUT1   DD DATA,DLM=@@
{HTTPPRM0.strip()}
@@
//SYSUT2   DD DISP=SHR,DSN=SYS2.PARMLIB(HTTPPRM0)
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
"""
    run_job(herc, 'HTTPPRM', lambda: submit_ascii(jcl))


def add_autostart(herc):
    log('Adding S UFSD / S HTTPD to SYS1.PARMLIB(COMMND00)...')
    rexx = """
/* REXX - append UFSD and HTTPD autostart to COMMND00 */
ADDRESS TSO
"ALLOC F(CFG) DA('SYS1.PARMLIB(COMMND00)') SHR REUSE"
"EXECIO * DISKR CFG (STEM LINE. FINIS"
have_ufsd = 0
have_httpd = 0
DO i = 1 TO line.0
  IF POS('S UFSD', line.i) > 0 THEN have_ufsd = 1
  IF POS('S HTTPD', line.i) > 0 THEN have_httpd = 1
END
IF have_ufsd = 0 THEN DO
  n = line.0 + 1; line.n = "COM='S UFSD'"; line.0 = n
END
IF have_httpd = 0 THEN DO
  n = line.0 + 1; line.n = "COM='S HTTPD'"; line.0 = n
END
"EXECIO" line.0 "DISKW CFG (STEM LINE. FINIS"
"FREE F(CFG)"
EXIT 0
"""
    run_job(herc, 'AUTOSTRT',
            lambda: submit_ascii(brexx_job('AUTOSTRT', 'AUTOSTART', rexx)))


def console(herc, name, *commands):
    rexx = 'ADDRESS CONSOLE\n' + '\n'.join(f"'{c}'" for c in commands)
    run_job(herc, name, lambda: submit_ascii(brexx_job(name, name, rexx)))


def start_stc(herc, name, msgid, expected):
    """Start an STC, wait for its banner and check the version it names.

    Both banners read '<msgid> <name> <version> (<commit>) STARTING', with
    the version in upper case.
    """
    since = len(read_log())
    console(herc, 'START' + name[:3], f'S {name}')
    if not wait_for_string(f'{msgid} {name} ', START_TIMEOUT, since):
        fail(herc, f'{name} did not start ({msgid} not seen)')
    line = next(l for l in read_log()[since:].splitlines() if msgid in l)
    log(f'  {line.strip()}')
    if expected and f'{msgid} {name} {expected.upper()} ' not in line:
        fail(herc, f'{name} is not at level {expected}')


def check_mvsmf(herc, expected):
    log('Checking the running mvsMF level (/zosmf/test?fn=version)...')
    if not wait_for_port(HTTP_PORT, timeout=60):
        fail(herc, f'HTTPD is not listening on port {HTTP_PORT}')
    req = urllib.request.Request(
        f'http://127.0.0.1:{HTTP_PORT}/zosmf/test?fn=version')
    cred = base64.b64encode(f'{USER}:{PASSWORD}'.encode()).decode()
    req.add_header('Authorization', f'Basic {cred}')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            info = json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001 - any failure fails the build
        fail(herc, f'mvsMF version probe failed: {e}')
    log(f'  mvsMF {info.get("version")} build {info.get("build")}')
    if expected and info.get('version', '').upper() != expected.upper():
        fail(herc, f'mvsMF reports {info.get("version")}, expected {expected}')


def main():
    global START_TIME
    START_TIME = time.time()

    for xmit, _, _ in MODULES:
        if not os.path.exists(xmit):
            log(f'ERROR: {xmit} not found')
            sys.exit(1)

    log('Starting Hercules...')
    herc = subprocess.Popen(
        ['hercules', '-f', 'conf/local.cnf', '-r', 'conf/mvsce.rc', '--daemon'],
        stdout=open(LOGFILE, 'w'), stderr=subprocess.STDOUT, cwd='/MVSCE')

    log('Waiting for MVS IPL ($HASP426)...')
    if not wait_for_string('$HASP426'):
        fail(herc, 'MVS IPL timeout')
    for port in (ASCII_PORT, EBCDIC_PORT):
        if not wait_for_port(port):
            fail(herc, f'card reader port {port} not available')
    if not wait_for_string('INIT'):
        fail(herc, 'JES2 initiators not ready')
    log('MVS is up')
    time.sleep(5)

    # UFSD and HTTPD are installed but not started, so the libraries are
    # free for DISP=OLD.
    for xmit, name, target in MODULES:
        install_modules(herc, xmit, name, target)

    write_httpprm0(herc)
    add_autostart(herc)

    start_stc(herc, 'UFSD', 'UFSD000I', os.environ.get('UFSD_VERSION'))
    start_stc(herc, 'HTTPD', 'HTTPD000I', os.environ.get('HTTPD_VERSION'))
    check_mvsmf(herc, os.environ.get('MVSMF_VERSION'))

    log('Stopping HTTPD and UFSD, purging the spool...')
    console(herc, 'STOPSTC', 'P HTTPD', 'P UFSD')
    time.sleep(10)
    console(herc, 'PURGESPL', '$PS1-9999', '$PT1-9999', '$PJ1-9999')
    time.sleep(5)

    # MVS/CE's own shutdown (SYS2.JCLLIB(SHUTFAST)): stops JES2, runs
    # Z EOD and QUIESCE, then quits Hercules, so the DASDs baked into the
    # layer are consistent.
    log('Shutting down MVS (SHUTFAST)...')
    submit_ascii(f"""{jobcard('SHUTFAST', 'SHUTFAST')}
//SHUTFAST EXEC SHUTDOWN,TYPE='SHUTFAST'
""")
    try:
        herc.wait(timeout=SHUTDOWN_TIMEOUT)
        log('Hercules has quit')
    except subprocess.TimeoutExpired:
        log('WARNING: MVS did not shut down in time, stopping Hercules')
        dump_log_tail()
        herc.terminate()
        try:
            herc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            herc.kill()

    log('Done: UFSD, HTTPD and mvsMF refreshed and set to autostart.')


if __name__ == '__main__':
    main()
