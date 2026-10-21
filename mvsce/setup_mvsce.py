#!/usr/bin/env python3
"""Install RAKF 2.0.0, refresh UFSD, HTTPD, mvsMF and FTPD on MVS/CE 3.x.

MVS/CE 3.0.0 ships an older RAKF under the same FMID (TRKF200) and banner
(RAKF V2R0M0) as RAKF 2.0.0 (TK5 Update 6), so only the content tells them
apart. It also installs UFSD, HTTPD, mvsMF and FTPD through MVP, but does
not start them. The MVP install provides everything this image needs apart
from the load modules themselves:

  MVSLOVER.UFSD.LOADLIB        UFSD load library (STEPLIB of the UFSD procs)
  HTTPD.LINKLIB                HTTPD load library, mvsMF lives in it too
  MVSLOVER.FTPD.LOADLIB        FTPD load library
  SYS2.PROCLIB(UFSD,UFSDCLNP)  STC procedures
  SYS2.PROCLIB(HTTPD)          STC procedure, incl. HASPCKPT/HASPACE1
  SYS2.PARMLIB(FTPDPRM0)       FTPD configuration, port 2121
  SYS2.PARMLIB(UFSDPRM0)       mounts /, /www, /tmp and the user homes
  UFSD.ROOT, HTTPD.WEBROOT,
  UFSD.SCRATCH, *.UFSHOME      the UFS disks

The build runs in two Hercules sessions, because RAKF 2.0.0 replaces
ICHSFR00 and ICHRIN00 in SYS1.LPALIB and only an IPL with CLPA loads them.

Session 1 (the IPL of the base image):

  1. Removes the old TRKF200 from the SMP inventory (UCLIN DEL on CDS and
     ACDS), RECEIVEs the TK5 package's XMIT (TK5INST.zip of RAKF v2.0.0),
     APPLYs and ACCEPTs FUNCTION TRKF200. The package lacks the macro
     IEZCTGPL, which TK5 has on the system and MVS/CE does not; it is
     added to RAKF.MACLIB first, or the RACIND assembly fails.
  2. Checks the installed modules by content, not by return code:
     ICHSFR00 in SYS1.LPALIB holds 'UNDEFINED CLASS' / 'RAKF0012', and
     ICHSEC00 in SYS1.LINKLIB (the class descriptor table) the entry
     JESSPOOL with length byte 8.
  3. Puts CLPA into SYS1.PARMLIB(IEASYS00) and shuts MVS down with SHUTFAST.

Session 2 (the CLPA IPL):

  4. Checks the storage of the running MVS: the new ICHSFR00 in the PLPA
     and the new class descriptor table, found through the CVT. Then takes
     CLPA out of IEASYS00 again: the PLPA the CLPA IPL built stays on the
     page data set, so the image's IPLs are quick starts as before.
  5. RECEIVEs the release XMITs from /tmp and IEBCOPYs their members, with
     replace, into the existing load libraries.
  6. Writes SYS2.PARMLIB(HTTPPRM0) in the form mvsMF documents, and
     SYS2.PROCLIB(FTPD) with the spool DDs FTPD's JES interface needs.
  7. Adds S UFSD / S HTTPD / S FTPD to SYS1.PARMLIB(COMMND00), and raises
     domain 1's minimum MPL in SYS1.PARMLIB(IEAIPS00) from 1 to 10.
  8. Sets up RAKF for the two servers that switch identity at startup:
     the users FTPD and HTTPD, as ftpd's docs/FTPD_RAKF_SETUP.md and
     httpd's docs/installation.md describe, and the FTPAUTH facility, which
     only ADMIN may use. RAKF 2.0.0 takes the group of a started task from
     its USERS entry, and only ADMIN and STCGROUP may use FACILITY SVC244,
     so both users are in STCGROUP (operations authority N): in group USER
     HTTPD stops with HTTPD012E and FTPD runs without APF authorization.
     It also gives IBMUSER and MVSCE01 the SPECIAL flag in USERS, which
     RAKF 2.0.0 requires for ADDUSER, PERMIT and the like.
  9. Starts all three and checks what is actually running: the UFSD000I,
     HTTPD000I and FTPD000I banners against UFSD_VERSION / HTTPD_VERSION /
     FTPD_VERSION, no RAKF0004 / HTTPD004W / FTPD004W for either server,
     no HTTPD012E and no APF SETUP FAILED, FTPD004I,
     FTPD001I READY, an FTP login, FTPAUTH refusing the FTPD user, and
     /zosmf/test?fn=version against MVSMF_VERSION.
     A build that installed nothing therefore fails instead of publishing
     the previous level.
 10. Adds P FTPD / P HTTPD / P UFSD to MVS/CE's SCRIPTS/SHUTDOWN.RC, purges
     the spool and shuts MVS down with MVS/CE's own SHUTFAST, the servers
     still running, so the build fails if the shutdown does not stop them.

The jobs print their output (MSGCLASS=A) to printers/prt00e.txt, whose
tail a failed build shows; the file is emptied at the end.

Run from /MVSCE with the DASDs at DASD/*.
"""
import base64
import ftplib
import json
import os
import re
import secrets
import socket
import string
import subprocess
import sys
import time
import urllib.request
import zipfile

EBCDIC_PORT = 3506
ASCII_PORT = 3505
HTTP_PORT = 8080
FTP_PORT = 2121
HERCULES_TIMEOUT = 300  # seconds to wait for MVS IPL
JOB_TIMEOUT = 180       # seconds to wait for a single job
START_TIMEOUT = 120     # seconds to wait for an STC banner
SHUTDOWN_TIMEOUT = 300  # seconds for SHUTFAST to quit Hercules

USER = 'IBMUSER'
PASSWORD = 'SYS1'

LOGFILE = '/tmp/hercules-build.log'    # set per Hercules session
PRINTER = '/MVSCE/printers/prt00e.txt'    # JES2 PRINTER1, class A

# (xmit file, job name, target load library)
MODULES = [
    ('/tmp/ufsd.xmit',  'UFSDRCV',  'MVSLOVER.UFSD.LOADLIB'),
    ('/tmp/httpd.xmit', 'HTTPDRCV', 'HTTPD.LINKLIB'),
    ('/tmp/mvsmf.xmit', 'MVSMFRCV', 'HTTPD.LINKLIB'),
    ('/tmp/ftpd.xmit',  'FTPDRCV',  'MVSLOVER.FTPD.LOADLIB'),
]

RAKF_ZIP = '/tmp/rakf/TK5INST.zip'
RAKF_XMIT = 'trkf200.xmi'                  # the member of RAKF_ZIP
RAKF_IEZCTGPL = '/tmp/rakf/IEZCTGPL.hlasm'
RAKF_FMID = 'TRKF200'                      # the old RAKF has it too

# The members of USERMOD.TRKF200, one DD each in RECEIVE, APPLY and ACCEPT.
RAKF_MEMBERS = [
    '$$$$$DOC', '$$$$INFO', '$$COPYRT', '$$NOTICE', '$DOC$ZIP',
    'INITTBLS', 'INITPWUP', 'INITSHAD', 'LPABACK', 'LPAREST',
    'JRACIND', 'RAKFRMV', 'RAKF2MVS', 'SPECIAL', 'VSAMLRAC',
    'VSAMSRAC', 'VTOCLRAC', 'VTOCSRAC', 'ZAPMVS38', 'ICHRIN00',
    'ICHSEC00', 'ICHSFR00', 'RACIND', 'RAKFHASH', 'RAKFPWH',
    'RAKFPSAV', 'CJYRCVT', 'CJYRUIDS', 'CJYRPROF', 'CJYRPWUP',
    'ADDUSER', 'ALTUSER', 'DELUSER', 'LISTUSER', 'CONNECT', 'ADDSD',
    'PERMIT', 'RDELETE', 'LISTP', 'IGC0013A', 'IGC0013C', 'IGC00130',
    'YREGS', 'CJYUCBLK', 'CJYRCVTD', 'CJYPCBLK', 'IEZCTGFL', 'RAKF',
    'RAKFPWUP', 'RAKFPROF', 'RAKFUSER', 'RAKFINIT',
]

# The z/OSMF routes as mvsMF 1.1.0 documents them: the two endpoints that
# resolve the caller themselves are public, everything else needs a login
# and answers a bare 401 (no browser dialog) without one.
HTTPPRM0 = """\
# HTTPPRM0 - written by mvsce (mvslovers/mvs-docker)
PORT=8080
DOCROOT=/www
MOD=MVSMF /zosmf/info                    AUTH=NONE
MOD=MVSMF /zosmf/services/authenticate   AUTH=NONE
MOD=MVSMF /zosmf/*                       AUTH=TOKEN
"""

# MVP's procedure without its comment block, plus the HASPACE1 DD that
# FTPD's JES interface needs to read the spool (without it: IEC130I
# HASPACE1 DD STATEMENT MISSING). Both spool DDs as in SYS2.PROCLIB(HTTPD).
FTPD_PROC = """\
//FTPD     PROC M=FTPDPRM0,
//            D='SYS2.PARMLIB'
//*
//* FTPD - written by mvsce (mvslovers/mvs-docker)
//*
//FTPD     EXEC PGM=FTPD,REGION=8M,TIME=1440
//STEPLIB  DD  DISP=SHR,DSN=MVSLOVER.FTPD.LOADLIB
//SYSUDUMP DD  SYSOUT=*
//STDOUT   DD  SYSOUT=*
//STDERR   DD  SYSOUT=*
//FTPDPRM  DD  DSN=&D(&M),DISP=SHR,FREE=CLOSE
//HASPCKPT DD  DISP=SHR,DSN=SYS1.HASPCKPT,UNIT=3350,VOL=SER=MVS000
//HASPACE1 DD  DISP=SHR,DSN=SYS1.HASPACE,UNIT=3350,VOL=SER=SPOOL1
"""

JOBCARD = """//{name:<8} JOB (TSO),'{title}',CLASS=A,MSGCLASS=A,
//             MSGLEVEL=(1,1),REGION={region},USER={user},PASSWORD={pw}{group}"""

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


def jobcard(name, title, group=None, region='0M'):
    """group: run connected to that RAKF group instead of the default one."""
    return JOBCARD.format(name=name, title=title[:20], user=USER, pw=PASSWORD,
                          region=region,
                          group=f',\n//             GROUP={group}' if group else '')


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


def wait_for_line(prefix, timeout=HERCULES_TIMEOUT, since=0):
    """Wait for a log line that starts (after its timestamp) with prefix.

    Unlike wait_for_string, not fooled by Hercules echoing a hao rule that
    names the same text ("HHC01603I hao tgt HHC00809I ...").
    """
    pat = re.compile(r'^\d\d:\d\d:\d\d ' + re.escape(prefix), re.M)
    start = time.time()
    while time.time() - start < timeout:
        if pat.search(read_log()[since:]):
            return True
        time.sleep(2)
    return False


def dump_log_tail(lines=20):
    content = read_log().splitlines()
    log(f'  log tail ({len(content)} lines total):')
    for l in content[-lines:]:
        print(f'    | {l}', flush=True)


def dump_printer_tail(lines=60):
    """The job output: what a condition code alone does not say."""
    time.sleep(5)   # JES2 prints a job after it has ended
    try:
        with open(PRINTER, 'r', errors='replace') as f:
            content = [l.rstrip() for l in f.read().splitlines() if l.strip()]
    except FileNotFoundError:
        return
    log(f'  printer tail ({PRINTER}):')
    for l in content[-lines:]:
        print(f'    > {l}', flush=True)


def fail(herc, msg):
    log(f'ERROR: {msg}')
    dump_log_tail()
    dump_printer_tail()
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


def run_job(herc, name, submit, steps, timeout=JOB_TIMEOUT):
    """Submit a job, wait for its $HASP395 and check every step's CC.

    $HASP395 only says the job ended. Each step that ran writes an IEFACTRT
    line ending in '/<cc>/<jobname>'; a step bypassed by COND writes none.
    So each of the given steps must appear, and each with CC 00000, or with
    one of the CCs of a ('step', '00004') entry. A step of a cataloged
    procedure is named after the procedure's step, not the EXEC statement:
    an SMP job has to be one step.
    """
    since = len(read_log())
    submit()
    if not wait_for_string(f'$HASP395 {name}', timeout, since):
        fail(herc, f'job {name} did not complete')
    time.sleep(2)
    pat = re.compile(r'IEFACTRT (\S+)\s*/[^/]*/[^/]*/[^/]*/([^/]+)/'
                     + re.escape(name) + r'\s*$')
    ccs = {}
    for line in read_log()[since:].splitlines():
        m = pat.search(line)
        if m:
            ccs[m.group(1)] = m.group(2).strip()
    shown = []
    for step in steps:
        step, ok = step if isinstance(step, tuple) else (step, ('00000',))
        if step not in ccs:
            fail(herc, f'job {name} step {step} did not run')
        if ccs[step] not in ok:
            fail(herc, f'job {name} step {step} ended CC {ccs[step]}')
        shown.append(f'{step} {ccs[step]}')
    log(f'  {name} ended, ' + ', '.join(shown))


def brexx_job(name, title, rexx, group=None):
    return f"""{jobcard(name, title, group)}
//REXX     EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
{rexx.strip()}
##
{BREXX_DDS}
"""


def check_hercules(herc, expected):
    """Check the Hercules that is running against HERCULES_REF.

    The banner reads 'HHC01413I Hercules version <v>-g<sha>'. The DASDs are
    compressed CCKD, so a build without zlib or bzip2 cannot read them;
    only the startup lists the features ('HHC01417I With    ZLIB support'),
    --version does not.
    """
    if not wait_for_string('HHC01413I', 60):
        fail(herc, 'no Hercules version banner (HHC01413I)')
    time.sleep(3)   # the feature list follows the banner
    log_text = read_log()
    banner = next(l for l in log_text.splitlines() if 'HHC01413I' in l)
    log(f'  {banner.strip()}')
    m = re.search(r'-g([0-9a-f]{7,})', banner)
    if expected and not (m and expected.startswith(m.group(1))):
        fail(herc, f'Hercules is not at {expected}')
    for feature in ('ZLIB support', 'CCKD BZIP2 support'):
        if not re.search(r'HHC01417I With\s+' + feature, log_text):
            fail(herc, f'Hercules was built without {feature}')


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
    run_job(herc, name, lambda: submit_ebcdic(cards(head) + data + cards(tail)),
            ['RECV', 'COPY'])


def rakf_sources(herc):
    """The XMIT (card images) out of TK5INST.zip, and the IEZCTGPL source."""
    try:
        with zipfile.ZipFile(RAKF_ZIP) as z:
            if z.namelist() != [RAKF_XMIT]:
                fail(herc, f'{RAKF_ZIP}: expected only {RAKF_XMIT}, '
                           f'found {z.namelist()}')
            xmit = z.read(RAKF_XMIT)
        with open(RAKF_IEZCTGPL) as f:
            macro = f.read()
    except (OSError, zipfile.BadZipFile) as e:
        fail(herc, f'RAKF sources: {e}')
    if len(xmit) == 0 or len(xmit) % 80:
        fail(herc, f'{RAKF_XMIT}: {len(xmit)} bytes is not a card-image XMIT')
    lines = macro.splitlines()
    if not lines or max(map(len, lines)) > 80 or not macro.isascii() \
            or any(l.startswith('@@') for l in lines):
        fail(herc, f'{RAKF_IEZCTGPL}: not usable as 80-column input')
    return xmit, macro


def smp_job(herc, name, title, step, control, dds='', ok='00000',
            timeout=JOB_TIMEOUT):
    """One SMP4 run (SMPAPP, SMPREC): the only step, named HMASMP by IEFACTRT."""
    jcl = f"""{jobcard(name, title, region='8192K')}
//{step:<8} EXEC {'SMPREC' if step == 'RECEIVE' else 'SMPAPP'}
{dds}//SMPCNTL  DD *
{control}
/*
"""
    run_job(herc, name, lambda: submit_ascii(jcl), [('HMASMP', (ok,))],
            timeout=timeout)


def member_dds(dsn):
    return ''.join(f'//{m:<8} DD DSN={dsn}({m}),DISP=SHR\n' for m in RAKF_MEMBERS)


def read_load_modules(herc, name, modules):
    """AMBLIST text of load modules, as bytes: [(dsn, member)] -> [bytes].

    The job prints to PRINTER; the TEXT records of each listing are the hex
    dump of the module, which is decoded and returned.
    """
    steps = ''.join(f"""//AMB{i}     EXEC PGM=AMBLIST
//SYSPRINT DD SYSOUT=*
//LIB      DD DISP=SHR,DSN={dsn}
//SYSIN    DD *
 LISTLOAD DDN=LIB,MEMBER={member},OUTPUT=MODLIST
/*
""" for i, (dsn, member) in enumerate(modules, 1))
    jcl = f"{jobcard(name, 'AMBLIST')}\n{steps}"
    try:
        offset = os.path.getsize(PRINTER)
    except FileNotFoundError:
        offset = 0
    run_job(herc, name, lambda: submit_ascii(jcl),
            [f'AMB{i}' for i in range(1, len(modules) + 1)])
    end = '*END OF LOAD MODULE LISTING'
    text = ''
    start = time.time()
    while time.time() - start < 60:     # JES2 prints a job after it has ended
        with open(PRINTER, 'r', errors='replace') as f:
            f.seek(offset)
            text = f.read()
        if text.count(end) >= len(modules):
            break
        time.sleep(2)
    else:
        fail(herc, f'{name}: AMBLIST listings not printed')
    hexline = re.compile(r'^\s*[0-9A-F]{6}\s{2,}((?:[0-9A-F]{2,8}\s*)+)$')
    out = []
    for part in re.split(r'(?m)^[\f ]*LISTLOAD .*$', text)[1:]:
        digits, in_text = '', False
        for line in part.splitlines():
            line = line.lstrip('\f')
            if line.startswith('RECORD#'):
                in_text = 'T E X T' in line
            elif in_text:
                m = hexline.match(line)
                if m:
                    digits += re.sub(r'\s', '', m.group(1))
        out.append(bytes.fromhex(digits))
    if len(out) != len(modules) or not all(out):
        log(f'  AMBLIST parts: {[len(o) for o in out]} bytes, '
            f'{text.count("LISTLOAD")} LISTLOAD, {text.count("T E X T")} TEXT')
        for l in text.splitlines()[:12]:
            log(f'  | {l!r}')
        fail(herc, f'{name}: could not read the AMBLIST listings')
    return out


def rakf_content(herc, name):
    """What the installed ICHSFR00 and ICHSEC00 contain (the old RAKF has the
    same FMID and banner, and an SMP return code says nothing about it).

    ICHSFR00 (SYS1.LPALIB) holds the message text 'RAKF0012 UNDEFINED CLASS'
    that 2.0.0 issues for a class missing from the class descriptor table.
    ICHSEC00 (SYS1.LINKLIB) is that table (CJYRCVT): the entry JESSPOOL is
    length byte 8, then the name. Returns the facts and the two lengths.
    """
    sfr, sec = read_load_modules(herc, name, [('SYS1.LPALIB', 'ICHSFR00'),
                                              ('SYS1.LINKLIB', 'ICHSEC00')])
    ebc = lambda t: t.encode('cp037')
    return {
        'ICHSFR00 has UNDEFINED CLASS': ebc('UNDEFINED CLASS') in sfr,
        'ICHSFR00 has RAKF0012': ebc('RAKF0012') in sfr,
        'ICHSEC00 has CDT entry X\'08\' JESSPOOL': b'\x08' + ebc('JESSPOOL') in sec,
    }, len(sfr), len(sec)


def install_rakf(herc):
    """FUNCTION TRKF200 of RAKF 2.0.0 by SMP4, over the older RAKF of the same FMID.

    TK5's own deck does the same on TK5. The steps, each its own job (an
    SMP step of a cataloged procedure is named after the procedure's step,
    so a job with two of them could not be told apart in the log):

      RAKFPREP  RAKF.* libraries; IEZCTGPL into RAKF.MACLIB
      RAKFUCL1  UCLIN CDS  DEL SYSMOD(TRKF200)
      RAKFUCL2  UCLIN ACDS DEL SYSMOD(TRKF200)
      RAKFXMIT  the XMIT into USERMOD.TRKF200
      RAKFRCV   RECEIVE, APPLY (RC 04: its linkedits end RC 08), ACCEPT

    The old TRKF200 has to go from the inventory first, or RECEIVE refuses
    the function. The UCLIN DEL does not need the member ids of the old
    function, which is why it works with an unknown old level; it ends RC 08
    (and the next UCLIN is skipped without RESETRC.) if TRKF200 is not there,
    i.e. if the base image is not what this expects.

    INITTBLS and INITSHAD, which replace the tables and the shadow file with
    the release's, are not run: the image keeps the users and profiles of
    MVS/CE. IEZCTGPL (CTGPL of the catalog parameter list) is not in the TK5
    package, because TK5 has it in SYS1.MACLIB; MVS/CE does not, and without
    it the RACIND assembly ends RC 12 (IFO188). Upstream's own MVS/CE deck
    carries it as a ++MAC.
    """
    log('Installing RAKF 2.0.0 (FUNCTION TRKF200)...')
    xmit, macro = rakf_sources(herc)

    def alloc(dd, dsn, space, blksize=27920):
        return f"""//{dd:<8} DD  DISP=(,CATLG),DSN={dsn},
//            UNIT=SYSALLDA,VOL=SER=PUB001,SPACE=({space}),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE={blksize})
"""
    libs = [('MAC', 'RAKF.MACLIB', 'TRK,(5,,5)'),
            ('SRC', 'RAKF.SRCLIB', 'CYL,(4,,20)'),
            ('SAMP', 'RAKF.SAMPLIB', 'CYL,(4,,20)'),
            ('AMAC', 'RAKF.AMACLIB', 'TRK,(5,,5)'),
            ('APARM', 'RAKF.APARMLIB', 'TRK,(5,,2)'),
            ('APROC', 'RAKF.APROCLIB', 'TRK,(3,,2)'),
            ('ASRC', 'RAKF.ASRCLIB', 'CYL,(4,,20)'),
            ('ASAMP', 'RAKF.ASAMPLIB', 'CYL,(4,,20)')]
    jcl = f"""{jobcard('RAKFPREP', 'RAKF PREPARE')}
//ALLOC    EXEC PGM=IEFBR14
{''.join(alloc(dd, dsn, sp, 80 if dd == 'APARM' else 27920) for dd, dsn, sp in libs)}//MACRO    EXEC PGM=IEBUPDTE,PARM=NEW
//SYSPRINT DD SYSOUT=*
//SYSUT2   DD DISP=OLD,DSN=RAKF.MACLIB
//SYSIN    DD DATA,DLM=@@
./ ADD NAME=IEZCTGPL
{macro.rstrip()}
@@
"""
    run_job(herc, 'RAKFPREP', lambda: submit_ascii(jcl), ['ALLOC', 'MACRO'])

    for name, db in (('RAKFUCL1', 'CDS'), ('RAKFUCL2', 'ACDS')):
        smp_job(herc, name, f'UCLIN {db} TRKF200', 'UCLIN',
                f' UCLIN {db} .\n DEL SYSMOD({RAKF_FMID}) .\n ENDUCL .')

    dlm = pick_delimiter(xmit)
    head = f"""{jobcard('RAKFXMIT', 'RECV TRKF200')}
//RECV     EXEC PGM=RECV370,REGION=6144K
//STEPLIB  DD DSN=SYSC.LINKLIB,DISP=SHR
//RECVLOG  DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=&&SYSUT1,UNIT=SYSALLDA,VOL=SER=PUB001,
//            SPACE=(TRK,(250,250)),DISP=(NEW,DELETE,DELETE)
//SYSUT2   DD DSN=USERMOD.TRKF200,UNIT=SYSALLDA,VOL=SER=PUB001,
//            SPACE=(TRK,(200,50,50)),DISP=(NEW,CATLG,DELETE)
//XMITIN   DD DATA,DLM={dlm}
"""
    run_job(herc, 'RAKFXMIT',
            lambda: submit_ebcdic(cards(head) + xmit + cards(f'{dlm}\n')),
            ['RECV'], timeout=600)

    members = member_dds('USERMOD.TRKF200')
    smp_job(herc, 'RAKFRCV', 'RECEIVE TRKF200', 'RECEIVE',
            f' RESETRC.\n RECEIVE SELECT({RAKF_FMID}) .',
            dds=members + '//SMPPTFIN DD DSN=USERMOD.TRKF200(@CVRLET),DISP=SHR\n',
            timeout=600)
    smp_job(herc, 'RAKFAPP', 'APPLY TRKF200', 'APPLYR',
            f' APPLY S({RAKF_FMID}) DIS(WRITE) .', ok='00004', timeout=900,
            dds="""//SYSLIB   DD  DISP=SHR,DSN=SYS1.SMPMTS,DCB=BLKSIZE=32720
//         DD  DISP=SHR,DSN=SYS1.SMPSTS
//         DD  DISP=SHR,DSN=SYS1.MACLIB
//         DD  DISP=SHR,DSN=SYS1.AMODGEN
//         DD  DISP=SHR,DSN=RAKF.MACLIB
//MACLIB   DD  DISP=SHR,DSN=RAKF.MACLIB
//SAMPLIB  DD  DISP=SHR,DSN=RAKF.SAMPLIB
//SRCLIB   DD  DISP=SHR,DSN=RAKF.SRCLIB
""" + members)
    smp_job(herc, 'RAKFACC', 'ACCEPT TRKF200', 'ACCEPTR',
            f' ACCEPT S({RAKF_FMID}) DIS(WRITE) .', timeout=900,
            dds="""//SYSLIB   DD  DISP=SHR,DSN=SYS1.MACLIB
//         DD  DISP=SHR,DSN=SYS1.AMODGEN
//         DD  DISP=SHR,DSN=RAKF.MACLIB
//AMACLIB  DD  DISP=SHR,DSN=RAKF.AMACLIB
//APARMLIB DD  DISP=SHR,DSN=RAKF.APARMLIB
//APROCLIB DD  DISP=SHR,DSN=RAKF.APROCLIB
//ASAMPLIB DD  DISP=SHR,DSN=RAKF.ASAMPLIB
//MACLIB   DD  DISP=SHR,DSN=RAKF.MACLIB
//SAMPLIB  DD  DISP=SHR,DSN=RAKF.SAMPLIB
//SRCLIB   DD  DISP=SHR,DSN=RAKF.SRCLIB
//ASRCLIB  DD  DISP=SHR,DSN=RAKF.ASRCLIB
""" + members)


def check_rakf_content(herc, name):
    facts, sfr_len, sec_len = rakf_content(herc, name)
    for what, found in facts.items():
        log(f'  {what}: {"yes" if found else "NO"}')
    if not all(facts.values()):
        fail(herc, 'RAKF 2.0.0 is not what is installed (content check)')
    return sfr_len, sec_len


def check_running_rakf(herc, name, sfr_len, sec_len):
    """What the running MVS has in storage: RAKF 2.0.0 is only in effect once
    an IPL with CLPA has loaded the new ICHSFR00 into the PLPA.

    CVT+X'F8' (CVTSAF) points to the SAFV, whose word at +12 is the address
    of ICHSFR00 (the LOAD in ICHSEC00); CVT+X'3E0' (CVTRAC) points to the
    RCVT, whose word at +48 (RCVTISTL) is the address of CJYRCVT's area,
    the class descriptor table among it. The message RCVT WAS PROCESSED
    SUCCESSFULLY of ICHSEC00 is no help: it has no route code, the old
    ICHSEC00 has it as well and neither shows on the console log.
    """
    rexx = f"""
/* REXX - the RAKF in storage */
cvt = c2d(storage(10, 4))
saf = c2d(storage(d2x(cvt + 248), 4))
sfr = c2d(storage(d2x(saf + 12), 4))
rac = c2d(storage(d2x(cvt + 992), 4))
cdt = c2d(storage(d2x(rac + 48), 4))
a = ''
DO i = 0 TO {sfr_len} - 1 BY 512
  a = a || storage(d2x(sfr + i), MIN(512, {sfr_len} - i))
END
b = ''
DO i = 0 TO {sec_len} - 1 BY 512
  b = b || storage(d2x(cdt + i), MIN(512, {sec_len} - i))
END
s1 = pos('UNDEFINED CLASS', a) > 0
s2 = pos('RAKF0012', a) > 0
s3 = pos(x2c('08') || 'JESSPOOL', b) > 0
r = 'RAKFRUN UNDEF=' || word('NO YES', 1 + s1)
r = r 'R12=' || word('NO YES', 1 + s2)
r = r 'CDT=' || word('NO YES', 1 + s3)
say r
"""
    try:
        offset = os.path.getsize(PRINTER)
    except FileNotFoundError:
        offset = 0
    run_job(herc, name, lambda: submit_ascii(brexx_job(name, 'RAKF IN STORAGE', rexx)),
            ['REXX'])
    pat = re.compile(r'RAKFRUN UNDEF=(YES|NO) R12=(YES|NO) CDT=(YES|NO)')
    m = None
    start = time.time()
    while not m and time.time() - start < 60:   # JES2 prints a job after it has ended
        time.sleep(2)
        with open(PRINTER, 'r', errors='replace') as f:
            f.seek(offset)
            m = pat.search(f.read())
    if not m:
        fail(herc, f'{name}: no result line')
    facts = dict(zip(('ICHSFR00 in storage has UNDEFINED CLASS',
                      'ICHSFR00 in storage has RAKF0012',
                      'CDT in storage has X\'08\' JESSPOOL'), m.groups()))
    for what, found in facts.items():
        log(f'  {what}: {found.lower()}')
    if set(facts.values()) != {'YES'}:
        fail(herc, 'the running MVS does not have RAKF 2.0.0 in storage')


def set_clpa(herc, on):
    """CLPA in SYS1.PARMLIB(IEASYS00), after its BLDLF line, or out again."""
    log(f'{"Adding" if on else "Removing"} CLPA in SYS1.PARMLIB(IEASYS00)...')
    rexx = f"""
/* REXX - CLPA line in IEASYS00 (columns 73-80 are the sequence number) */
ADDRESS TSO
new = LEFT('CLPA,', 20)
new = new || LEFT('CLPA FOR RAKF 2.0.0 (IMAGE BUILD)', 52)
new = new || '00000025'
"ALLOC F(SYS) DA('SYS1.PARMLIB(IEASYS00)') SHR REUSE"
"EXECIO * DISKR SYS (STEM LINE. FINIS"
o = 0; clpa = 0; bldlf = 0
DO i = 1 TO line.0
  IF LEFT(line.i, 5) = 'CLPA,' THEN DO
    clpa = clpa + 1
    IF {0 if on else 1} THEN ITERATE
  END
  o = o + 1; out.o = line.i
  IF LEFT(line.i, 6) = 'BLDLF=' THEN DO
    bldlf = bldlf + 1
    IF {1 if on else 0} THEN DO
      o = o + 1; out.o = new
    END
  END
END
IF bldlf <> 1 THEN EXIT 8
IF {1 if on else 0} & clpa <> 0 THEN EXIT 8
IF {0 if on else 1} & clpa <> 1 THEN EXIT 8
out.0 = o
"EXECIO" out.0 "DISKW SYS (STEM OUT. FINIS"
"FREE F(SYS)"
EXIT 0
"""
    name = 'CLPAON' if on else 'CLPAOFF'
    run_job(herc, name,
            lambda: submit_ascii(brexx_job(name, 'IEASYS00 CLPA', rexx)),
            ['REXX'])


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
    run_job(herc, 'HTTPPRM', lambda: submit_ascii(jcl), ['WRITE'])


def write_ftpd_proc(herc):
    log('Writing SYS2.PROCLIB(FTPD)...')
    jcl = f"""{jobcard('FTPDPROC', 'FTPD PROC')}
//WRITE    EXEC PGM=IEBGENER
//SYSUT1   DD DATA,DLM=@@
{FTPD_PROC.strip()}
@@
//SYSUT2   DD DISP=SHR,DSN=SYS2.PROCLIB(FTPD)
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
"""
    run_job(herc, 'FTPDPROC', lambda: submit_ascii(jcl), ['WRITE'])


def add_autostart(herc):
    log('Adding S UFSD / S HTTPD / S FTPD to SYS1.PARMLIB(COMMND00)...')
    rexx = """
/* REXX - append UFSD, HTTPD and FTPD autostart to COMMND00 */
ADDRESS TSO
"ALLOC F(CFG) DA('SYS1.PARMLIB(COMMND00)') SHR REUSE"
"EXECIO * DISKR CFG (STEM LINE. FINIS"
have_ufsd = 0
have_httpd = 0
have_ftpd = 0
DO i = 1 TO line.0
  IF POS('S UFSD', line.i) > 0 THEN have_ufsd = 1
  IF POS('S HTTPD', line.i) > 0 THEN have_httpd = 1
  IF POS('S FTPD', line.i) > 0 THEN have_ftpd = 1
END
IF have_ufsd = 0 THEN DO
  n = line.0 + 1; line.n = "COM='S UFSD'"; line.0 = n
END
IF have_httpd = 0 THEN DO
  n = line.0 + 1; line.n = "COM='S HTTPD'"; line.0 = n
END
IF have_ftpd = 0 THEN DO
  n = line.0 + 1; line.n = "COM='S FTPD'"; line.0 = n
END
"EXECIO" line.0 "DISKW CFG (STEM LINE. FINIS"
"FREE F(CFG)"
EXIT 0
"""
    run_job(herc, 'AUTOSTRT',
            lambda: submit_ascii(brexx_job('AUTOSTRT', 'AUTOSTART', rexx)),
            ['REXX'])


def raise_dmn1_mpl(herc):
    """DMN=1,CNSTR=(1,50,1) -> (10,50,1) in SYS1.PARMLIB(IEAIPS00).

    With a minimum MPL of 1 the SRM keeps swappable domain-1 address
    spaces (batch and, with no IEAICS, the started tasks) swapped out for
    about 30 s after the IPL: FTPD sat between FTPD001I READY and its
    first accept(), SETPFKEY before its first instruction. Measured by
    ftpd (ftpd#176): SET IPS to a copy with a minimum of 10 released both
    within a second, re-applying the minimum of 1 did not. Takes effect
    at the next IPL, i.e. in every container started from the image.
    """
    log('Raising domain 1 minimum MPL in SYS1.PARMLIB(IEAIPS00) to 10...')
    rexx = """
/* REXX - DMN=1 minimum MPL 1 -> 10, columns after it unchanged */
ADDRESS TSO
"ALLOC F(IPS) DA('SYS1.PARMLIB(IEAIPS00)') SHR REUSE"
"EXECIO * DISKR IPS (STEM LINE. FINIS"
old = 'DMN=1,CNSTR=(1,50,1) '
hit = 0
DO i = 1 TO line.0
  IF LEFT(line.i, LENGTH(old)) = old THEN DO
    line.i = 'DMN=1,CNSTR=(10,50,1)' || SUBSTR(line.i, LENGTH(old) + 1)
    hit = hit + 1
  END
END
IF hit <> 1 THEN EXIT 8
"EXECIO" line.0 "DISKW IPS (STEM LINE. FINIS"
"FREE F(IPS)"
EXIT 0
"""
    run_job(herc, 'IPSDMN1',
            lambda: submit_ascii(brexx_job('IPSDMN1', 'IEAIPS00 DMN1', rexx)),
            ['REXX'])


def setup_rakf(herc):
    """RAKF users for FTPD and HTTPD, and FTPAUTH.

    Both servers drop from STC (operations authority) to their own user
    at startup; without that user RAKF answers RAKF0004 and the server
    keeps running as STC (FTPD004W / HTTPD004W). ftpd's
    docs/FTPD_RAKF_SETUP.md and httpd's docs/installation.md (section 8).

    The group of the users is STCGROUP, not USER. Since RAKF 2.0.0 the USERS
    entry of a started task decides its group (before, the entry only had
    to exist), and FACILITY SVC244 is granted to ADMIN and STCGROUP alone:
    in group USER HTTPD ends with HTTPD012E (no APF authorization) and FTPD
    runs on with APF SETUP FAILED RC=4. The operations authority stays N,
    so neither can log in as an operator.

    Users are added with ADDUSER (the password goes to
    SYS1.SECURE.SHADOW), profiles are edited in SYS1.SECURE.CNTL(PROFILES).
    Both need the RAKFADM group; IBMUSER's default group ADMIN has no
    access to SYS1.SECURE.*. RAKF 2.0.0 also wants the SPECIAL authority
    (column 30 of USERS) for ADDUSER and the other administration commands;
    MVS/CE's USERS has IBMUSER and MVSCE01 with the operations flag only,
    so all the lines of exactly those two users (one per group) get the
    SPECIAL flag first (the job ends RC 8 unless both users are found; no
    other user is touched), and S RAKFUSER follows, since the job's authority is the one in the loaded table.

    Both sign on with PASSCHK=NO and never use the password, so it is
    random and not kept. FTPAUTH is granted to ADMIN only, so the FTPD
    user itself cannot log in over FTP. One step per user, so each
    ADDUSER has a condition code of its own.
    """
    log('Setting up RAKF (users FTPD and HTTPD, facility FTPAUTH)...')
    alphabet = string.ascii_uppercase + string.digits
    pws = {u: secrets.choice(string.ascii_uppercase)
              + ''.join(secrets.choice(alphabet) for _ in range(7))
           for u in ('FTPD', 'HTTPD')}
    rexx = """
/* REXX - SPECIAL (col 30) for IBMUSER and MVSCE01 only */
ADDRESS TSO
"ALLOC F(USR) DA('SYS1.SECURE.CNTL(USERS)') SHR REUSE"
"EXECIO * DISKR USR (STEM IN. FINIS"
found = ''
DO i = 1 TO in.0
  l = LEFT(in.i, 80)
  out.i = l
  IF LEFT(l, 1) = '*' THEN ITERATE
  u = STRIP(LEFT(l, 8))
  IF u = 'IBMUSER' | u = 'MVSCE01' THEN DO
    out.i = LEFT(l, 28) || ' Y' || SUBSTR(l, 31)
    found = found u
  END
END
IF POS('IBMUSER', found) = 0 | POS('MVSCE01', found) = 0 THEN EXIT 8
out.0 = in.0
"EXECIO" out.0 "DISKW USR (STEM OUT. FINIS"
"FREE F(USR)"
EXIT 0
"""
    run_job(herc, 'USRSPEC',
            lambda: submit_ascii(brexx_job('USRSPEC', 'USERS SPECIAL', rexx,
                                           'RAKFADM')),
            ['REXX'])
    since = len(read_log())
    console(herc, 'RAKFUSR', 'S RAKFUSER')
    if not wait_for_string('RAKFUIDS4  USER TABLE UPDATED', START_TIMEOUT, since):
        fail(herc, 'RAKF reload: RAKFUIDS4  USER TABLE UPDATED not seen')

    steps = ''.join(f"""//ADD{u:<5} EXEC PGM=IKJEFT01,REGION=4096K
//SYSPRINT DD  SYSOUT=*
//SYSTERM  DD  SYSOUT=*
//SYSIN    DD  DUMMY
//SYSTSPRT DD  SYSOUT=*
//SYSTSIN  DD  *
 ADDUSER {u} PASSWORD({pw}) DFLTGRP(STCGROUP) NOOPERATIONS
/*
""" for u, pw in pws.items())
    jcl = f"""{jobcard('ADDUSERS', 'ADDUSER FTPD HTTPD', 'RAKFADM')}
{steps}"""
    run_job(herc, 'ADDUSERS', lambda: submit_ascii(jcl),
            [f'ADD{u}' for u in pws])

    # Ascending order on columns 1-60 with the universal (blank group)
    # line first, or RAKF rejects the whole table.
    rexx = """
/* REXX - insert FTPAUTH into SYS1.SECURE.CNTL(PROFILES), in order */
ADDRESS TSO
"ALLOC F(PRF) DA('SYS1.SECURE.CNTL(PROFILES)') SHR REUSE"
"EXECIO * DISKR PRF (STEM IN. FINIS"
new.1 = LEFT('FACILITYFTPAUTH', 60) || 'NONE'
new.2 = LEFT(LEFT('FACILITYFTPAUTH', 52) || 'ADMIN', 60) || 'READ'
new.0 = 2
o = 0; k = 1
DO i = 1 TO in.0
  IF POS('FACILITYFTPAUTH ', in.i) = 1 THEN EXIT 8
  DO WHILE k <= new.0 & LEFT(in.i, 60) >> LEFT(new.k, 60)
    o = o + 1; out.o = new.k; k = k + 1
  END
  o = o + 1; out.o = in.i
END
DO WHILE k <= new.0
  o = o + 1; out.o = new.k; k = k + 1
END
out.0 = o
"EXECIO" out.0 "DISKW PRF (STEM OUT. FINIS"
"FREE F(PRF)"
EXIT 0
"""
    run_job(herc, 'FTPAUTH',
            lambda: submit_ascii(brexx_job('FTPAUTH', 'FTPAUTH', rexx,
                                           'RAKFADM')),
            ['REXX'])

    since = len(read_log())
    console(herc, 'RAKFLOAD', 'S RAKFUSER', 'S RAKFPROF')
    for msg in ('RAKFUIDS4  USER TABLE UPDATED', 'RAKFPROF7  RAKF PROFILES UPDATED'):
        if not wait_for_string(msg, START_TIMEOUT, since):
            fail(herc, f'RAKF reload: {msg} not seen')
        log(f'  {msg}')
    return pws['FTPD']


def check_identity(herc, name, since, ready):
    """No RAKF0004 for the server, no <name>004W, no HTTPD012E (for HTTPD)
    and <name>002I present.

    Checked once <ready> has appeared, so the startup lines are all in.
    """
    if not wait_for_string(ready, START_TIMEOUT, since):
        fail(herc, f'{name} not ready ({ready} not seen)')
    started = read_log()[since:]
    if f'USER:{name}' in started:
        fail(herc, f'{name} start reports RAKF0004 for USER:{name}')
    if f'{name}004W' in started:
        fail(herc, f'{name} start reports {name}004W')
    if f'{name}012E' in started:
        fail(herc, f'{name} start reports {name}012E (no APF authorization)')
    if f'{name}002I AUTHORIZED BY' not in started:
        fail(herc, f'no {name}002I AUTHORIZED BY line')
    log(f'  {name}: no RAKF0004, no {name}004W, no {name}012E, '
        f'{name}002I present')


def console(herc, name, *commands):
    rexx = 'ADDRESS CONSOLE\n' + '\n'.join(f"'{c}'" for c in commands)
    run_job(herc, name, lambda: submit_ascii(brexx_job(name, name, rexx)),
            ['REXX'])


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


def check_ftpd(herc, expected, since, ftpd_pw):
    """FTPD001I READY only follows a successful bind; then log in for real."""
    want = f'FTPD001I FTPD {expected.upper()} READY' if expected else 'FTPD001I'
    if not wait_for_string(want, START_TIMEOUT, since):
        fail(herc, f'FTPD not ready ({want} not seen)')
    log(f'  {want}')
    started = read_log()[since:]
    for bad in ('RAKF0004', 'FTPD004W', 'APF SETUP FAILED'):
        if bad in started:
            fail(herc, f'FTPD start reports {bad}')
    if 'FTPD004I STC IDENTITY SET TO FTPD/USER' not in started:
        fail(herc, 'FTPD did not switch to FTPD/USER (no FTPD004I)')
    log('  FTPD004I STC IDENTITY SET TO FTPD/USER, no RAKF0004/FTPD004W, '
        'no APF SETUP FAILED')
    try:
        with ftplib.FTP() as ftp:
            ftp.connect('127.0.0.1', FTP_PORT, timeout=30)
            welcome = ftp.getwelcome()
            ftp.login(USER, PASSWORD)
            pwd = ftp.pwd()
    except Exception as e:  # noqa: BLE001 - any failure fails the build
        fail(herc, f'FTP login as {USER} failed: {e}')
    log(f'  FTP login as {USER}: {welcome!r}, PWD {pwd!r}')
    try:
        with ftplib.FTP() as ftp:
            ftp.connect('127.0.0.1', FTP_PORT, timeout=30)
            ftp.login('FTPD', ftpd_pw)
        fail(herc, 'FTPAUTH let the FTPD user log in')
    except ftplib.error_perm as e:
        if not str(e).startswith('530'):
            fail(herc, f'FTP login as FTPD: unexpected {e}')
        log(f'  FTP login as FTPD refused: {e}')
    except Exception as e:  # noqa: BLE001 - any failure fails the build
        fail(herc, f'FTP login as FTPD failed: {e}')


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


SHUTDOWN_RC = '/MVSCE/SCRIPTS/SHUTDOWN.RC'
# One command per pause: of two lines typed into the 3215-C console within
# the same second, MVS acts on the second only (measured: /P FTPD then
# /P HTTPD stopped HTTPD alone, /P FTPD then /D T only displayed the time).
STOP_SERVERS = """* Stopping FTPD, HTTPD and UFSD (added by mvslovers/mvs-docker)
/P FTPD
pause 1
/P HTTPD
pause 3
/P UFSD
pause 3
"""


# SHUTDOWN.RC's poweroff (stopall, sysclear, quit) is armed on
# "HHC00814I Processor CP00/CP01: SIGP Stop", which only a second CPU
# produces; with this image's NUMCPU 1 MVS stopped in wait CCC and
# Hercules ran on. TK5 arms its poweroff on the wait state itself; this
# one only on MVS/CE's wait CCC after QUIESCE, not on a crash's wait code.
POWEROFF_RULE = """hao tgt HHC00809I Processor CP00: disabled wait state 000A0000 00000CCC
hao cmd script SCRIPTS/poweroff
"""


def patch_shutdown_rc():
    """P FTPD / P HTTPD / P UFSD in MVS/CE's SCRIPTS/SHUTDOWN.RC.

    SHUTDOWN and SHUTFAST end in this Hercules script. It stops TSO,
    VTAM and JES2's devices but not the servers, and with those still up
    JES2 never says $HASP099 ALL AVAILABLE FUNCTIONS COMPLETE, which is
    what its hao rule waits for to $PJES2: the shutdown stopped after
    HALT NET. The stops go in once logons are refused, FTPD and HTTPD
    before UFSD; a server that is not running only answers IEE341I.
    """
    with open(SHUTDOWN_RC, newline='') as f:
        s = f.read()
    anchor = '/MODIFY TSO,USERMAX=0\npause 2\n'
    rules = 'hao cmd script SCRIPTS/poweroff\n'
    if s.count(anchor) != 1 or s.count(rules) != 2:
        log(f'ERROR: {SHUTDOWN_RC}: not the expected script')
        sys.exit(1)
    s = s.replace(anchor, anchor + STOP_SERVERS)
    i = s.rindex(rules) + len(rules)
    s = s[:i] + POWEROFF_RULE + s[i:]
    with open(SHUTDOWN_RC, 'w', newline='') as f:
        f.write(s)
    log(f'{SHUTDOWN_RC}: P FTPD / P HTTPD / P UFSD and a 1-CPU poweroff rule added')


def start_hercules(session):
    """IPL MVS in a new Hercules process; its log is /tmp/hercules-build-<session>.log."""
    global LOGFILE
    LOGFILE = f'/tmp/hercules-build-{session}.log'
    log(f'Starting Hercules (session {session})...')
    # stdin stays open: at EOF on stdin a --daemon Hercules shuts down
    # unless a CPU happens to be started (see entrypoint.sh), and the
    # shutdown below types 'quit' into it.
    herc = subprocess.Popen(
        ['hercules', '-f', 'conf/local.cnf', '-r', 'conf/mvsce.rc', '--daemon'],
        stdin=subprocess.PIPE, stdout=open(LOGFILE, 'w'),
        stderr=subprocess.STDOUT, cwd='/MVSCE')

    check_hercules(herc, os.environ.get('HERCULES_REF'))

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
    return herc


def purge_spool(herc):
    log('Purging the spool...')
    console(herc, 'PURGESPL', '$PS1-9999', '$PT1-9999', '$PJ1-9999')
    time.sleep(5)


def shutdown_mvs(herc, servers):
    """MVS/CE's own shutdown (SYS2.JCLLIB(SHUTFAST)), then quit Hercules.

    It stops JES2, runs Z EOD and QUIESCE, so the DASDs baked into the
    layer are consistent. MVS then sits in disabled wait CCC and Hercules
    is told to quit. servers: the started tasks SHUTDOWN.RC has to have
    stopped (patch_shutdown_rc).
    """
    log('Shutting down MVS (SHUTFAST)...')
    since = len(read_log())
    submit_ascii(f"""{jobcard('SHUTFAST', 'SHUTFAST')}
//SHUTFAST EXEC SHUTDOWN,TYPE='SHUTFAST'
""")
    if not wait_for_line('HHC00809I Processor CP00: disabled wait state 000A0000 00000CCC',
                         SHUTDOWN_TIMEOUT, since):
        fail(herc, 'SHUTFAST did not reach wait CCC (servers not stopped?)')
    for name in servers:
        if f'$HASP395 {name}' not in read_log()[since:]:
            fail(herc, f'SHUTFAST did not stop {name}')
    if servers:
        log(f'  {", ".join(servers)} stopped by SHUTDOWN.RC')
    log('MVS quiesced (wait CCC), quitting Hercules')
    herc.stdin.write(b'quit\n')
    # Hercules finishes its shutdown, but the process only exits once
    # stdin reaches EOF (measured with a742398074: 'Hercules terminated'
    # and then 300 s of nothing until SIGTERM).
    herc.stdin.close()
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


def main():
    global START_TIME
    START_TIME = time.time()

    for xmit, _, _ in MODULES:
        if not os.path.exists(xmit):
            log(f'ERROR: {xmit} not found')
            sys.exit(1)
    patch_shutdown_rc()

    # Session 1: RAKF 2.0.0, and CLPA for the next IPL.
    herc = start_hercules(1)
    log('RAKF before the install (information only):')
    for what, found in rakf_content(herc, 'RAKFOLD')[0].items():
        log(f'  {what}: {"yes" if found else "no"}')
    install_rakf(herc)
    sfr_len, sec_len = check_rakf_content(herc, 'RAKFCHK')
    set_clpa(herc, True)
    purge_spool(herc)
    shutdown_mvs(herc, [])

    # Session 2: the CLPA IPL loads the new ICHSFR00 and ICHRIN00 into the
    # PLPA; everything else on top of it.
    herc = start_hercules(2)
    check_running_rakf(herc, 'RAKFRUN', sfr_len, sec_len)
    set_clpa(herc, False)

    # UFSD and HTTPD are installed but not started, so the libraries are
    # free for DISP=OLD.
    for xmit, name, target in MODULES:
        install_modules(herc, xmit, name, target)

    write_httpprm0(herc)
    write_ftpd_proc(herc)
    add_autostart(herc)
    raise_dmn1_mpl(herc)
    ftpd_pw = setup_rakf(herc)

    start_stc(herc, 'UFSD', 'UFSD000I', os.environ.get('UFSD_VERSION'))
    since = len(read_log())
    start_stc(herc, 'HTTPD', 'HTTPD000I', os.environ.get('HTTPD_VERSION'))
    check_identity(herc, 'HTTPD', since, 'HTTPD001I')
    check_mvsmf(herc, os.environ.get('MVSMF_VERSION'))
    since = len(read_log())
    start_stc(herc, 'FTPD', 'FTPD000I', os.environ.get('FTPD_VERSION'))
    check_ftpd(herc, os.environ.get('FTPD_VERSION'), since, ftpd_pw)

    # The servers stay up: SHUTFAST has to stop them (patch_shutdown_rc).
    purge_spool(herc)
    shutdown_mvs(herc, ['FTPD', 'HTTPD', 'UFSD'])

    # the printed job output (and the ADDUSER card) stays out of the image
    for name in os.listdir(os.path.dirname(PRINTER)):
        open(os.path.join(os.path.dirname(PRINTER), name), 'w').close()

    log('Done: RAKF 2.0.0, UFSD, HTTPD, mvsMF and FTPD installed and set to autostart.')


if __name__ == '__main__':
    main()
