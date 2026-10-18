#!/usr/bin/env python3
"""Install UFSD, HTTPD, mvsMF and FTPD on TK5 with SMP, enable their autostart.

Runs at image build time in /tk5. Each product comes as its release
distribution package (/tmp/dist/<product>-<version>/: the load and sample
library XMITs, an allocation job and an SMP install job) and is installed
the way its README describes, by its own jobs:

  1. IPLs TK5 (minimal configuration, as the image runs it).
  2. Moves TK5's own HTTPD 3.3.0 load library out of the way
     (HTTPD.LINKLIB -> HTTPD.V3R3M0.LINKLIB): HTTPD 4's allocation job
     creates HTTPD.LINKLIB. The XMITs go in through the card reader,
     switched to EBCDIC for them.
  3. Per product, in the order the READMEs require (UFSD, HTTPD, mvsMF,
     FTPD): the shipped allocation job, then the shipped install job
     (RECEIVE, APPLY CHECK, APPLY, ACCEPT), each with the job card's
     USER/PASSWORD added (RAKF) and the CHANGE.ME names filled in, the
     libraries on TSO001. An install counts only when every module the
     APPLY reports as copied (HMA2380) is in the target library's member
     list: SMP ends RC 0 also when it installs nothing.
  4. Configuration, the TK5 way: procedures from the SAMPLIBs into
     SYS2.PROCLIB with TK5's values (SYS1.PARMLIB, the spool on SPOOL0,
     MVSMF.LINKLIB ahead of HTTPD.LINKLIB), the parmlib members into
     SYS1.PARMLIB, the UFS disks UFSD.ROOT, UFSD.SCRATCH (/tmp) and
     HERC01.UFSHOME (/u/herc01), the RAKF users HTTPD and FTPD in group
     USER, and S UFSD / S HTTPD / S FTPD in the BSPPILOT scripts TK5
     starts its tasks from, SYS1.PARMLIB(STARTMIN) and (STARTSTD), the
     matching P commands in its shutdown scripts SYS1.PARMLIB(SDMIN*,
     SDSTD*), and
     domain 1's minimum MPL in SYS1.PARMLIB(IEAIPS00) from 1 to 10.
     No APF entries: on TK5 the servers authorise themselves through
     RAKF's SVC 244, as their READMEs describe.
  5. Starts all three and checks what runs: the banners against the
     versions, the identity switches (HTTPD004I, FTPD004I), the
     readiness messages, an FTP login, FTPAUTH refusing the FTPD user,
     /zosmf/test?fn=version against MVSMF_VERSION, and the SMP inventory.
  6. Shuts TK5 down with its own scripts (scripts/shutdown), the servers
     still running: BSPPILOT's shutdown scripts now stop them (step 4).

Job output goes to the class A printer, prt/prt00e.txt; a failed build
shows its tail. Printers and logs are emptied at the end.
"""
import ftplib
import glob
import os
import re
import secrets
import socket
import string
import subprocess
import sys
import time
import urllib.request
import base64

TK5 = '/tk5'
DIST = '/tmp/dist'
LOGFILE = f'{TK5}/log/3033.log'
PRINTER = f'{TK5}/prt/prt00e.txt'
READER_PORT = int(os.environ.get('RDRPORT', '3505'))
FTP_PORT = 2121
HTTP_PORT = 8080
VOLUME = 'TSO001'           # product libraries and UFS disks
USER, PASSWORD = 'HERC01', 'CUL8TR'
HERCULES_TIMEOUT = 300
JOB_TIMEOUT = 300
START_TIMEOUT = 120

PRODUCTS = [   # name, data set prefix of its XMIT staging, version env
    ('ufsd', 'UFSD_VERSION'),
    ('httpd', 'HTTPD_VERSION'),
    ('mvsmf', 'MVSMF_VERSION'),
    ('ftpd', 'FTPD_VERSION'),
]

JOBCARD = """//{name:<8} JOB (TSO),'{title}',CLASS=A,MSGCLASS=A,
//             MSGLEVEL=(1,1),REGION=0M,USER={user},PASSWORD={pw}"""

START_TIME = time.time()


def log(msg):
    print(f'[setup {time.time() - START_TIME:6.1f}s] {msg}', flush=True)


def jobcard(name, title):
    return JOBCARD.format(name=name, title=title[:20], user=USER, pw=PASSWORD)


def read_log():
    try:
        with open(LOGFILE, 'r', errors='replace') as f:
            return f.read()
    except FileNotFoundError:
        return ''


def read_printer():
    try:
        with open(PRINTER, 'rb') as f:
            return f.read().decode('latin-1')
    except FileNotFoundError:
        return ''


def wait_for_string(target, timeout=HERCULES_TIMEOUT, since=0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if target in read_log()[since:]:
            return True
        time.sleep(1)
    return False


def dump_tails():
    lines = read_log().splitlines()[-30:]
    log('  hercules log tail:')
    for l in lines:
        print(f'    | {l}', flush=True)
    content = [l.rstrip() for l in read_printer().replace('\f', '\n').splitlines()
               if l.strip()][-80:]
    log(f'  printer tail ({PRINTER}):')
    for l in content:
        print(f'    > {l}', flush=True)


def fail(herc, msg):
    log(f'ERROR: {msg}')
    time.sleep(3)
    dump_tails()
    herc.kill()
    sys.exit(1)


def console(herc, *commands):
    for c in commands:
        log(f'  console: {c}')
        herc.stdin.write(f'/{c}\n'.encode())
        herc.stdin.flush()
        time.sleep(1)


def hercules_cmd(herc, cmd):
    herc.stdin.write(f'{cmd}\n'.encode())
    herc.stdin.flush()


def to_reader(herc, data):
    """Send a deck to the reader; after a devinit it takes a moment to bind."""
    deadline = time.time() + 30
    while True:
        try:
            s = socket.create_connection(('127.0.0.1', READER_PORT), timeout=30)
            break
        except OSError:
            if time.time() > deadline:
                fail(herc, f'card reader port {READER_PORT} not available')
            time.sleep(1)
    s.sendall(data)
    s.close()


def submit(herc, jcl, timeout=JOB_TIMEOUT):
    """Submit through the ASCII reader; return the job's printed output.

    Waits for $HASP395 <name> ENDED on the console, then for JES2 to have
    printed the job (the END JOB separator for it on PRINTER1).
    """
    name = re.match(r'//(\S+)', jcl).group(1)
    long = [l for l in jcl.splitlines() if len(l) > 80]
    if long:    # the reader cuts every card at column 80
        fail(herc, f'job {name}: line longer than 80 columns: {long[0]!r}')
    since = len(read_log())
    poff = len(read_printer())
    to_reader(herc, jcl.encode('ascii'))
    if not wait_for_string(f'$HASP395 {name}', timeout, since):
        fail(herc, f'job {name} did not end within {timeout}s')
    end = re.compile(r'END\s+JOB\s+\d+\s+' + re.escape(name) + r'\b')
    deadline = time.time() + 60
    while time.time() < deadline:
        out = read_printer()[poff:]
        if end.search(out):
            time.sleep(2)
            return read_printer()[poff:]
        time.sleep(1)
    fail(herc, f'job {name}: no printed output')


def step_codes(out):
    """[(step, 'nnnn' | 'NOT EXECUTED' | 'ABEND ...')] from IEF142I/IEF272I/IEF450I."""
    res = []
    for m in re.finditer(r'IEF142I \S+ (\S+)(?: \S+)? - STEP WAS EXECUTED - COND CODE (\d{4})', out):
        res.append((m.group(1), m.group(2)))
    for m in re.finditer(r'IEF272I \S+ (\S+)(?: \S+)? - STEP WAS NOT EXECUTED', out):
        res.append((m.group(1), 'NOT EXECUTED'))
    for m in re.finditer(r'IEF450I \S+ (\S+)(?: \S+)? - ABEND (\S+)', out):
        res.append((m.group(1), f'ABEND {m.group(2)}'))
    return res


def run_job(herc, jcl, allowed=None, timeout=JOB_TIMEOUT):
    """Submit; fail unless every step ran and ended with a code in allowed."""
    name = re.match(r'//(\S+)', jcl).group(1)
    out = submit(herc, jcl, timeout)
    codes = step_codes(out)
    if not codes:
        fail(herc, f'job {name}: no step ran (JCL error?)')
    for step, cc in codes:
        ok = cc in (allowed or {}).get(step, ('0000',))
        log(f'  {name}.{step}: {cc}{"" if ok else "  <-- unexpected"}')
        if not ok:
            fail(herc, f'job {name} step {step} ended {cc}')
    return out


def add_user(jcl):
    """USER/PASSWORD on a shipped job card (RAKF), held output to class A."""
    lines = jcl.splitlines()
    if not re.match(r'//\S+\s+JOB\b.*,\s*$', lines[0]):
        raise ValueError(f'unexpected job card: {lines[0]!r}')
    lines.insert(1, f'//             USER={USER},PASSWORD={PASSWORD},')
    out = '\n'.join(lines) + '\n'
    return out.replace('MSGCLASS=H', 'MSGCLASS=A')


def ieblist(herc, dsn):
    """Member names of a PDS on VOLUME."""
    jcl = f"""{jobcard('LISTPDS', 'LIST ' + dsn)}
//LIST     EXEC PGM=IEHLIST
//SYSPRINT DD  SYSOUT=*
//DD1      DD  UNIT=3390,VOL=SER={VOLUME},DISP=SHR
//SYSIN    DD  *
  LISTPDS DSNAME={dsn},VOL=3390={VOLUME}
/*
"""
    out = run_job(herc, jcl)
    members = set()
    for line in out.splitlines():
        m = re.match(r'\s+([A-Z@#$][A-Z0-9@#$]{0,7})\s+[0-9A-F]{6,}', line)
        if m:
            members.add(m.group(1))
    return members


# --- steps -----------------------------------------------------------------

def start_hercules():
    log('Starting Hercules (TK5, minimal configuration)...')
    os.makedirs(f'{TK5}/log', exist_ok=True)
    herc = subprocess.Popen(
        ['hercules', '-d', '-f', 'conf/tk5.cnf'],
        stdin=subprocess.PIPE, stdout=open(LOGFILE, 'w'),
        stderr=subprocess.STDOUT, cwd=TK5)
    if not wait_for_string('HHC01413I', 60):
        fail(herc, 'no Hercules banner')
    banner = re.search(r'HHC01413I .*', read_log()).group(0)
    log(f'  {banner}')
    ref = os.environ.get('HERCULES_REF', '')
    sha = re.search(r'-g([0-9a-f]{7,})', banner)
    if not sha or not ref.startswith(sha.group(1)):
        fail(herc, f'Hercules is not {ref}')
    if not wait_for_string('IKT005I', HERCULES_TIMEOUT):
        fail(herc, 'TSO not up (IKT005I)')
    log('TK5 is up (IKT005I)')
    return herc


def rename_tk5_httpd(herc):
    log("Moving TK5's HTTPD 3.3.0 load library out of the way...")
    run_job(herc, f"""{jobcard('HTTPDREN', 'RENAME HTTPD 3.3.0')}
//RENAME   EXEC PGM=IDCAMS
//SYSPRINT DD  SYSOUT=*
//SYSIN    DD  *
  ALTER HTTPD.LINKLIB NEWNAME(HTTPD.V3R3M0.LINKLIB)
/*
""")


def ebcdic_card(text):
    return text.ljust(80)[:80].encode('cp037')


def pick_delimiter(cards):
    for a in string.ascii_uppercase:
        for b in string.ascii_uppercase:
            d = a + b
            if not any(c[:2] == d.encode('cp037') for c in cards):
                return d
    raise ValueError('no free in-stream delimiter')


def reader_mode(herc, mode):
    """Re-initialise reader 00C as a socket reader in mode (ascii/ebcdic).

    The re-bind can fail while the old socket is still held ("bind():
    Address already in use", HHC02244E); then it is retried.
    """
    for attempt in range(10):
        since = len(read_log())
        hercules_cmd(herc, f'devinit 000C {READER_PORT} sockdev {mode} trunc eof')
        deadline = time.time() + 10
        while time.time() < deadline:
            out = read_log()[since:]
            if 'HHC02245I 0:000C' in out:
                return
            if 'HHC02244E 0:000C' in out:
                break
            time.sleep(0.5)
        time.sleep(3)
    fail(herc, f'reader 00C: devinit to {mode} failed')


def upload_xmits(herc, files):
    """files: [(local path, DSN)]: each XMIT, binary, into a new data set.

    TK5 has one JES2 reader (READER1, 00C), an ASCII socket reader. It is
    switched to EBCDIC for the uploads and back: each XMIT goes in as the
    in-stream data of an IEBGENER job, 80-byte records as they are.
    (TK5's own FTP server, FTPD 1.0.1, answers every STOR with 553 Access
    denied.)
    """
    log(f'Uploading {len(files)} XMITs through the reader, in EBCDIC...')
    reader_mode(herc, 'ebcdic')
    for n, (path, dsn) in enumerate(files, 1):
        data = open(path, 'rb').read()
        if len(data) % 80:
            fail(herc, f'{path}: not a sequence of 80-byte records')
        cards = [data[i:i + 80] for i in range(0, len(data), 80)]
        dlm = pick_delimiter(cards)
        name = f'XMIT{n}'
        trks = len(cards) // 600 + 5
        deck = b''.join([ebcdic_card(l) for l in jobcard(name, 'UPLOAD ' + dsn).splitlines()] + [
            ebcdic_card('//COPY     EXEC PGM=IEBGENER'),
            ebcdic_card('//SYSPRINT DD  SYSOUT=*'),
            ebcdic_card('//SYSIN    DD  DUMMY'),
            ebcdic_card(f'//SYSUT2   DD  DSN={dsn},DISP=(NEW,CATLG,DELETE),'),
            ebcdic_card(f'//             UNIT=3390,VOL=SER={VOLUME},SPACE=(TRK,({trks},10)),'),
            ebcdic_card('//             DCB=(DSORG=PS,RECFM=FB,LRECL=80,BLKSIZE=3120)'),
            ebcdic_card(f'//SYSUT1   DD  DATA,DLM={dlm}'),
        ] + cards + [ebcdic_card(dlm), ebcdic_card('//')])
        since = len(read_log())
        to_reader(herc, deck)
        if not wait_for_string(f'$HASP395 {name}', JOB_TIMEOUT, since):
            fail(herc, f'upload job {name} did not end')
        out = read_log()[since:]
        if 'JCL ERROR' in out or 'ABEND' in out:
            fail(herc, f'upload job {name} failed')
        log(f'  {os.path.basename(path)} -> {dsn} ({len(cards)} records)')
    reader_mode(herc, 'ascii')


def install_product(herc, prod, version, staged):
    """The shipped alloc and install jobs; verify by HMA2380 vs member list."""
    d = f'{DIST}/{prod}-{version}'
    alloc = open(f'{d}/{prod}-{version}-alloc.jcl').read()
    inst = open(f'{d}/{prod}-{version}-inst.jcl').read()
    log(f'Installing {prod} {version} with SMP...')

    alloc = add_user(alloc)
    if alloc.count('UNIT=SYSDA') < 1:
        fail(herc, f'{prod} alloc job: no UNIT=SYSDA to pin')
    alloc = alloc.replace('UNIT=SYSDA', f'UNIT=3390,VOL=SER={VOLUME}')
    run_job(herc, alloc)

    inst = add_user(inst)
    names = sorted(set(re.findall(r"CHANGE\.ME\.[A-Z0-9]+", inst)))
    if len(names) != 2:
        fail(herc, f'{prod} install job: expected two CHANGE.ME names, got {names}')
    for n in names:
        kind = 'SAMP' if n.endswith('SAMPLIB') else 'LOAD'
        inst = inst.replace(n, staged[kind])
    out = run_job(herc, inst, timeout=600)

    fmid = re.search(r'HMA3930\s+SYSMOD (\S+) SUCCESSFULLY RECEIVED', out)
    copied = re.findall(r'HMA2380\s+COPY SUCCESSFUL - MOD=(\S+) - LMOD=(\S+)', out)
    if not fmid or not copied:
        fail(herc, f'{prod}: no HMA3930 / HMA2380 in the SMP output')
    if 'NOT SEL' in out:
        fail(herc, f'{prod}: an element was NOT SEL (owned by another SYSMOD)')
    lib = f'{prod.upper()}.LINKLIB'
    members = ieblist(herc, lib)
    lmods = sorted({lm for _, lm in copied})
    missing = [m for m in lmods if m not in members]
    if missing:
        fail(herc, f'{prod}: {missing} reported copied but not in {lib}')
    log(f'  {fmid.group(1)}: {", ".join(lmods)} in {lib}')
    return fmid.group(1)


def copy_member(herc, name, src, dst, subs=(), inserts=()):
    """Copy src to dst with string substitutions (each must hit), in REXX.

    The counter is not called o or n: those are tails of s.k.o / s.k.n,
    and REXX would substitute a variable of that name into them. No '|'
    anywhere: through the ASCII reader it does not arrive as the
    character BREXX reads as the or/concatenation operator.

    inserts: (prefix, line) -- line goes in before the first line starting
    with prefix.
    """
    # one assignment per line: the reader cuts cards at column 80
    rexx_subs = ''.join(
        f'  s.{i}.o = "{o}"\n  s.{i}.n = "{n}"\n  s.{i}.hit = 0\n'
        for i, (o, n) in enumerate(subs, 1))
    rexx_ins = ''.join(
        f'  p.{i}.o = "{o}"\n  p.{i}.n = "{n}"\n  p.{i}.hit = 0\n'
        for i, (o, n) in enumerate(inserts, 1))
    rexx = f"""/* REXX - copy a member with substitutions */
  s.0 = {len(subs)}
{rexx_subs}  p.0 = {len(inserts)}
{rexx_ins}  "ALLOC F(IN) DA('{src}') SHR REUSE"
  "EXECIO * DISKR IN (STEM L. FINIS"
  "FREE F(IN)"
  cnt = 0
  DO i = 1 TO l.0
    line = l.i
    DO k = 1 TO p.0
      IF p.k.hit = 0 & LEFT(line, LENGTH(p.k.o)) = p.k.o THEN DO
        cnt = cnt + 1; out.cnt = p.k.n; p.k.hit = 1
      END
    END
    DO k = 1 TO s.0
      x = POS(s.k.o, line)
      IF x > 0 THEN DO
        line = INSERT(s.k.n, DELSTR(line, x, LENGTH(s.k.o)), x - 1)
        s.k.hit = 1
      END
    END
    cnt = cnt + 1; out.cnt = line
  END
  DO k = 1 TO s.0
    IF s.k.hit = 0 THEN DO; SAY 'NOT FOUND:' s.k.o; EXIT 8; END
  END
  DO k = 1 TO p.0
    IF p.k.hit = 0 THEN DO; SAY 'NOT FOUND:' p.k.o; EXIT 8; END
  END
  out.0 = cnt
  "ALLOC F(OUT) DA('{dst}') SHR REUSE"
  "EXECIO" out.0 "DISKW OUT (STEM OUT. FINIS"
  "FREE F(OUT)"
  EXIT 0
"""
    run_job(herc, brexx_job(name, f'COPY {dst}'[:20], rexx))


def brexx_job(name, title, rexx):
    """A REXX program run by TK5's BREXX in a TSO batch step."""
    return f"""{jobcard(name, title)}
//REXX     EXEC PGM=IKJEFT01,PARM='BREXX EXEC',REGION=8M
//EXEC     DD  DATA,DLM=##
{rexx.strip()}
##
//SYSPRINT DD  SYSOUT=*
//SYSTSPRT DD  SYSOUT=*
//SYSTSIN  DD  DUMMY
//STDOUT   DD  SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD  SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD  DUMMY
"""


def write_member(herc, name, dsn, text):
    data = '\n'.join(l.rstrip()[:80] for l in text.strip('\n').splitlines())
    if '\n@@' in '\n' + data:
        raise ValueError('member text would end the in-stream data')
    run_job(herc, f"""{jobcard(name, 'WRITE ' + dsn)}
//COPY     EXEC PGM=IEBGENER
//SYSPRINT DD  SYSOUT=*
//SYSIN    DD  DUMMY
//SYSUT2   DD  DISP=SHR,DSN={dsn}
//SYSUT1   DD  DATA,DLM=@@
{data}
@@
""")


UFSDPRM0 = f"""
/* SYS1.PARMLIB(UFSDPRM0) - written by tk5 (mvslovers/mvs-docker) */
ROOT     DSN(UFSD.ROOT)
MOUNT    DSN(UFSD.SCRATCH)       PATH(/tmp)          MODE(RW)
MOUNT    DSN(HERC01.UFSHOME)     PATH(/u/herc01)     MODE(RW) OWNER(HERC01)
"""

UFS_DISKS = [   # dsn, blocks of 4096, owner
    ('UFSD.ROOT', 256, None),
    ('UFSD.SCRATCH', 1280, None),
    ('HERC01.UFSHOME', 1280, 'HERC01'),
]


def configure(herc):
    log('Procedures into SYS2.PROCLIB, members into SYS1.PARMLIB...')
    parm = [("D='SYS2.PARMLIB'", "D='SYS1.PARMLIB'")]
    spool = [('VOL=SER=MVS000', 'VOL=SER=SPOOL0'),
             ('VOL=SER=SPOOL1', 'VOL=SER=SPOOL0')]
    copy_member(herc, 'CPYUFSD', 'UFSD.SAMPLIB(UFSD)', 'SYS2.PROCLIB(UFSD)', parm)
    copy_member(herc, 'CPYUFSDC', 'UFSD.SAMPLIB(UFSDCLNP)', 'SYS2.PROCLIB(UFSDCLNP)')
    # mvsMF lives in a library of its own and goes first (its README)
    steplib = '//STEPLIB  DD  DISP=SHR,DSN=HTTPD.LINKLIB'
    copy_member(herc, 'CPYHTTPD', 'HTTPD.SAMPLIB(HTTPD)', 'SYS2.PROCLIB(HTTPD)',
                parm + spool + [(steplib, '//         DD  DISP=SHR,DSN=HTTPD.LINKLIB')],
                [(steplib, '//STEPLIB  DD  DISP=SHR,DSN=MVSMF.LINKLIB')])
    copy_member(herc, 'CPYFTPD', 'FTPD.SAMPLIB(FTPD)', 'SYS2.PROCLIB(FTPD)',
                parm + spool)
    copy_member(herc, 'CPYHTPRM', 'HTTPD.SAMPLIB(HTTPPRM0)', 'SYS1.PARMLIB(HTTPPRM0)')
    copy_member(herc, 'CPYFTPRM', 'FTPD.SAMPLIB(FTPDPRM0)', 'SYS1.PARMLIB(FTPDPRM0)')
    write_member(herc, 'UFSDPRM0', 'SYS1.PARMLIB(UFSDPRM0)', UFSDPRM0)

    log('Formatting the UFS disks...')
    for dsn, blocks, owner in UFS_DISKS:
        sysin = '   BLKSIZE  4096\n   INODES   10.0\n'
        if owner:
            sysin += f'   OWNER    {owner}\n   GROUP    USER\n'
        out = run_job(herc, f"""{jobcard('UFSFMT', 'FORMAT ' + dsn)}
//ALLOC    EXEC PGM=IEFBR14
//DISKFILE DD  DSN={dsn},DISP=(NEW,CATLG),
//             UNIT=3390,VOL=SER={VOLUME},SPACE=(4096,{blocks}),
//             DCB=(DSORG=PS,RECFM=U,BLKSIZE=4096)
//FORMAT   EXEC PGM=UFSFMT
//STEPLIB  DD  DISP=SHR,DSN=UFSD.LINKLIB
//DISKFILE DD  DISP=OLD,DSN={dsn}
//SYSPRINT DD  SYSOUT=*
//SYSTERM  DD  SYSOUT=*
//SYSUDUMP DD  SYSOUT=*
//SYSIN    DD  *
{sysin}/*
""")
        if 'UFSFMT26I' not in out:
            fail(herc, f'UFSFMT {dsn}: no UFSFMT26I')
        log(f'  {dsn}: {blocks} blocks')


def setup_rakf(herc):
    """Users HTTPD and FTPD in group USER, as the servers RACINIT them.

    TK5's RAKF keeps users in SYS1.SECURE.CNTL(USERS), one line per user
    and group (user, group, password, operations flag in fixed columns);
    TK5 ships FTPD in group FTPD only. Both sign on without a password
    check, so the passwords are random and not kept. Reloaded by S RAKF.
    """
    log('RAKF: users HTTPD and FTPD in group USER...')
    alphabet = string.ascii_uppercase + string.digits
    pw = {u: secrets.choice(string.ascii_uppercase)
          + ''.join(secrets.choice(alphabet) for _ in range(7))
          for u in ('HTTPD', 'FTPD')}
    lines = ''.join(f"  n.{i} = '{u:<8} USER     {pw[u]:<8} N'\n"
                    for i, u in enumerate(pw, 1))
    rexx = f"""/* REXX - add users to SYS1.SECURE.CNTL(USERS) */
{lines}  n.0 = {len(pw)}
  "ALLOC F(U) DA('SYS1.SECURE.CNTL(USERS)') SHR REUSE"
  "EXECIO * DISKR U (STEM L. FINIS"
  DO i = 1 TO l.0
    DO k = 1 TO n.0
      IF LEFT(l.i, 17) = LEFT(n.k, 17) THEN EXIT 8
    END
  END
  o = 0; done = 0
  DO i = 1 TO l.0
    IF done = 0 & LEFT(l.i, 1) <> '*' THEN DO
      DO k = 1 TO n.0
        o = o + 1; out.o = n.k
      END
      done = 1
    END
    o = o + 1; out.o = l.i
  END
  out.0 = o
  "EXECIO" out.0 "DISKW U (STEM OUT. FINIS"
  "FREE F(U)"
  EXIT 0
"""
    run_job(herc, brexx_job('RAKFUSR', 'RAKF USERS', rexx))
    since = len(read_log())
    console(herc, 'S RAKF')
    if not wait_for_string('RAKFUIDS4  USER TABLE UPDATED', START_TIMEOUT, since):
        fail(herc, 'S RAKF: no RAKFUIDS4 USER TABLE UPDATED')
    log('  RAKFUIDS4  USER TABLE UPDATED')


def raise_dmn1_mpl(herc):
    """DMN=1,CNSTR=(1,50,1) -> (10,50,1) in SYS1.PARMLIB(IEAIPS00).

    TK5's IEAIPS00 has MVS/CE's value, and with a minimum MPL of 1 the
    SRM keeps the swappable domain-1 started tasks swapped out for a while
    after the IPL: with the start script run early (local_conf/ipl.rc),
    FTPD's first greeting came 20 s after the connect. The same change as
    mvsce's, measured there by ftpd (ftpd#176).
    """
    log('Domain 1 minimum MPL 1 -> 10 in SYS1.PARMLIB(IEAIPS00)...')
    copy_member(herc, 'IPSDMN1', 'SYS1.PARMLIB(IEAIPS00)', 'SYS1.PARMLIB(IEAIPS00)',
                subs=[('DMN=1,CNSTR=(1,50,1) ', 'DMN=1,CNSTR=(10,50,1)')])


def add_autostart(herc):
    """S UFSD / S HTTPD / S FTPD in TK5's own startup scripts.

    TK5 starts its system tasks from BSPPILOT scripts, not from COMMND00:
    JES2's start member ($TA,I=30 in SYS1.JES2PARM(STARTMIN) or
    (STARTSTD)) runs SYS1.PARMLIB(STARTMIN) in the minimal configuration
    and (STARTSTD) in the default one. The servers go in both, ahead of
    the closing broadcast, UFSD first: HTTPD and FTPD mount from it.
    """
    log('S UFSD / S HTTPD / S FTPD into SYS1.PARMLIB(STARTMIN) and (STARTSTD)...')
    lines = [('COM SE', f'CMD S {s}') for s in ('UFSD', 'HTTPD', 'FTPD')]
    for m in ('STARTMIN', 'STARTSTD'):
        copy_member(herc, f'AUTO{m[5:]}', f'SYS1.PARMLIB({m})',
                    f'SYS1.PARMLIB({m})', inserts=lines)


def start_stc(herc, name, ready, msgid, expected, extra=()):
    """S name; wait for ready; check the banner version and extra messages."""
    since = len(read_log())
    console(herc, f'S {name}')
    if not wait_for_string(ready, START_TIMEOUT, since):
        fail(herc, f'{name} not ready ({ready} not seen)')
    started = read_log()[since:]
    m = re.search(rf'{msgid} {name} (\S+)', started)
    if not m or (expected and m.group(1) != expected):
        fail(herc, f'{name}: {msgid} reports {m and m.group(1)}, expected {expected}')
    for bad in ('RAKF0004', f'{name}004W', f'{name}003W'):
        if bad in started:
            fail(herc, f'{name} start reports {bad}')
    for want in extra:
        if want not in started:
            fail(herc, f'{name}: no "{want}"')
    log(f'  {name} {m.group(1)}: {ready}' + ''.join(f', {w}' for w in extra))


def check_mvsmf(herc, expected):
    auth = base64.b64encode(f'{USER}:{PASSWORD}'.encode()).decode()
    req = urllib.request.Request(
        f'http://127.0.0.1:{HTTP_PORT}/zosmf/test?fn=version',
        headers={'Authorization': f'Basic {auth}'})
    try:
        body = urllib.request.urlopen(req, timeout=30).read().decode()
    except Exception as e:  # noqa: BLE001 - any failure fails the build
        fail(herc, f'mvsMF fn=version: {e}')
    m = re.search(r'"version"\s*:\s*"([^"]+)"', body)
    if not m or (expected and m.group(1) != expected):
        fail(herc, f'mvsMF reports {body!r}, expected {expected}')
    log(f'  mvsMF {m.group(1)}: {body.strip()}')


def check_ftp(herc):
    try:
        with ftplib.FTP() as ftp:
            ftp.connect('127.0.0.1', FTP_PORT, timeout=60)
            welcome = ftp.getwelcome()
            ftp.login(USER, PASSWORD)
            pwd = ftp.pwd()
    except Exception as e:  # noqa: BLE001
        fail(herc, f'FTP login as {USER}: {e}')
    log(f'  FTP login as {USER}: {welcome!r}, PWD {pwd!r}')
    # TK5's FACILITY FTPAUTH is ADMIN only: HERC03 (group USER, TK5's
    # documented password) must be refused for that, not for its password.
    try:
        with ftplib.FTP() as ftp:
            ftp.connect('127.0.0.1', FTP_PORT, timeout=30)
            ftp.login('HERC03', 'PASS4U')
        fail(herc, 'FTPAUTH let HERC03 (group USER) log in')
    except ftplib.error_perm as e:
        if 'incorrect' in str(e).lower():
            fail(herc, f'FTP login as HERC03: {e} (password, not FTPAUTH)')
        log(f'  FTP login as HERC03 refused: {e}')


def check_inventory(herc, fmids):
    log('SMP inventory...')
    out = run_job(herc, f"""{jobcard('SMPLIST', 'SMP LIST')}
//LIST     EXEC SMPAPP
//SMPCNTL  DD  *
 LIST CDS SYSMOD({','.join(fmids)}) .
 LIST ACDS SYSMOD({','.join(fmids)}) .
/*
""", allowed={'HMASMP': ('0000', '0004')})
    for f in fmids:
        st = re.findall(rf'^{f}\s+TYPE\s+= FUNCTION\s*\n\s+STATUS\s+= (REC\s+APP\s+ACC\b.*)$',
                        out, re.M)
        if len(st) != 2:    # once in the CDS, once in the ACDS
            fail(herc, f'{f}: not REC APP ACC in both zones ({st})')
    log(f'  {", ".join(fmids)}: REC APP ACC in CDS and ACDS')


def stop_servers_at_shutdown(herc):
    """P FTPD / P HTTPD / P UFSD in TK5's BSPPILOT shutdown scripts.

    F BSPPILOT,SHUTNOW (and SHUTFAST, SHUTDOWN) run SYS1.PARMLIB(SDMINNOW,
    SDMINFST, SDMIN) or the SDSTD* ones, through aliases INISDxxx renews at
    every IPL. They stop TSO, VTAM and JES2's devices but know nothing of
    our servers, and with those still up JES2 never says $HASP099 ALL
    AVAILABLE FUNCTIONS COMPLETE: the shutdown stopped after BSPPILOT
    ENDED. FTPD and HTTPD go first, UFSD after them; IF skips a server
    that is not running.
    """
    log('P FTPD / P HTTPD / P UFSD into the BSPPILOT shutdown scripts...')
    lines = [('COM P TSO', l) for l in (
        'IF FTPD', 'COM P FTPD', 'ENDIF', 'IF HTTPD', 'COM P HTTPD', 'ENDIF',
        'WAIT 3', 'IF UFSD', 'COM P UFSD', 'ENDIF', 'WAIT 3')]
    for m in ('SDMINNOW', 'SDMINFST', 'SDMIN', 'SDSTDNOW', 'SDSTDFST', 'SDSTD'):
        copy_member(herc, f'SD{m[2:]}'[:8], f'SYS1.PARMLIB({m})',
                    f'SYS1.PARMLIB({m})', inserts=lines)
    # BSPPILOT reads SHUTNOW etc. through aliases, and a rewritten member
    # moves: the aliases still name the old text until INISDMIN renews
    # them, which TK5 does at every IPL. The build shuts down without one.
    since = len(read_log())
    console(herc, 'S INISDMIN')
    if not wait_for_string('$HASP395 INISDMIN', START_TIMEOUT, since):
        fail(herc, 'S INISDMIN did not end')
    log('  shutdown aliases renewed (INISDMIN)')


def shutdown(herc):
    """TK5's own shutdown, with the servers still running: the test that
    the shutdown scripts stop them."""
    log('Purging the spool...')
    console(herc, '$PJ1-9999', '$PS1-9999', '$PT1-9999')
    time.sleep(5)
    log("Shutting TK5 down (its scripts/shutdown), the servers still up...")
    since = len(read_log())
    hercules_cmd(herc, 'script scripts/shutdown')
    # 'IEE334I HALT', not 'IEE334I': the echo of scripts/shutdown's own
    # "hao tgt IEE334I" has that too.
    if not wait_for_string('IEE334I HALT', 300, since):
        fail(herc, 'shutdown: no IEE334I HALT EOD SUCCESSFUL; servers not stopped?')
    for name in ('FTPD', 'HTTPD', 'UFSD'):
        if f'$HASP395 {name}' not in read_log()[since:]:
            fail(herc, f'shutdown: {name} was not stopped')
    log('  FTPD, HTTPD and UFSD stopped by the shutdown script, IEE334I HALT EOD')
    # scripts/poweroff (armed on HHC00809I, the CPU's wait state after
    # QUIESCE) ends in quit; Hercules then exits only at EOF on stdin.
    if not wait_for_string('HHC01420I', 120, since):
        fail(herc, 'shutdown: Hercules did not begin its own shutdown (no HHC01420I)')
    log('  scripts/poweroff: Hercules shutting down (HHC01420I)')
    herc.stdin.close()
    try:
        herc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        fail(herc, 'Hercules did not exit after its shutdown')


def main():
    versions = {p: os.environ.get(v, '') for p, v in PRODUCTS}
    for p, v in versions.items():
        if not glob.glob(f'{DIST}/{p}-{v}/{p}-{v}-inst.jcl'):
            log(f'ERROR: no {DIST}/{p}-{v}')
            sys.exit(1)

    herc = start_hercules()
    rename_tk5_httpd(herc)

    files, staged = [], {}
    for p, v in versions.items():
        d = f'{DIST}/{p}-{v}'
        q = p.upper()[:8]
        staged[p] = {'LOAD': f'{USER}.{q}.LOAD.XMIT', 'SAMP': f'{USER}.{q}.SAMP.XMIT'}
        files.append((f'{d}/{p}-{v}-load.xmit', staged[p]['LOAD']))
        files.append((f'{d}/{p}-{v}-samplib.xmit', staged[p]['SAMP']))
    upload_xmits(herc, files)

    fmids = [install_product(herc, p, v, staged[p]) for p, v in versions.items()]

    configure(herc)
    setup_rakf(herc)
    add_autostart(herc)
    stop_servers_at_shutdown(herc)
    raise_dmn1_mpl(herc)

    log('Starting the servers...')
    start_stc(herc, 'UFSD', 'UFSD001I', 'UFSD000I', versions['ufsd'])
    start_stc(herc, 'HTTPD', 'HTTPD001I', 'HTTPD000I', versions['httpd'],
              ['HTTPD004I STC IDENTITY SET TO HTTPD/USER'])
    check_mvsmf(herc, versions['mvsmf'])
    start_stc(herc, 'FTPD', 'FTPD001I', 'FTPD000I', versions['ftpd'],
              ['FTPD004I STC IDENTITY SET TO FTPD/USER'])
    check_ftp(herc)
    check_inventory(herc, fmids)

    shutdown(herc)
    for f in glob.glob(f'{TK5}/prt/*.txt') + glob.glob(f'{TK5}/log/*.log'):
        open(f, 'w').close()
    log('Done: UFSD, HTTPD, mvsMF and FTPD installed with SMP and set to autostart.')


if __name__ == '__main__':
    main()
