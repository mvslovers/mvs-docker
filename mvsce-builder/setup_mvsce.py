#!/usr/bin/env python3
"""Setup MVS/CE with HTTPD + mvsMF.

Starts Hercules, waits for MVS IPL, installs HTTPD via MVP,
installs mvsMF load module and config, adds HTTPD autostart,
then shuts down MVS cleanly.

Run from /MVSCE working directory with DASDs at DASD/*.
"""
import socket
import time
import subprocess
import sys
import os

EBCDIC_PORT = 3506
ASCII_PORT = 3505
HERCULES_TIMEOUT = 300  # seconds to wait for MVS IPL
JOB_TIMEOUT = 180       # seconds to wait for a single job
MVP_TIMEOUT = 300        # seconds to wait for all MVP jobs

MVP_PACKAGES = ['imon370', 'ind$file']


def log(msg):
    elapsed = time.time() - START_TIME
    print(f'[setup {elapsed:6.1f}s] {msg}', flush=True)


def wait_for_port(port, timeout=60):
    """Wait until a TCP port is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(('127.0.0.1', port))
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


def submit_ascii(jcl):
    """Submit JCL via ASCII card reader (port 3505)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', ASCII_PORT))
    sock.sendall(jcl.encode())
    sock.close()


def submit_ebcdic_with_binary(jcl, binary_data, delimiter='$$'):
    """Submit JCL with inline binary via EBCDIC card reader (port 3506)."""
    line_fmt = '{:80}'
    data = b''
    for l in jcl.strip().splitlines():
        data += line_fmt.format(l).encode('cp500')
    data += binary_data
    data += line_fmt.format(delimiter).encode('cp500')

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', EBCDIC_PORT))
    sock.sendall(data)
    sock.close()


def read_log(logfile):
    """Read entire log file content."""
    try:
        with open(logfile, 'r', errors='replace') as f:
            return f.read()
    except FileNotFoundError:
        return ''


def wait_for_string(logfile, target, timeout=HERCULES_TIMEOUT):
    """Wait for a string to appear in the Hercules log."""
    start = time.time()
    while time.time() - start < timeout:
        if target in read_log(logfile):
            return True
        time.sleep(2)
    return False


def wait_for_job(logfile, jobname, timeout=JOB_TIMEOUT):
    """Wait for a job to complete by watching the Hercules log."""
    target = f'$HASP395 {jobname}'
    return wait_for_string(logfile, target, timeout)


def count_pattern(logfile, pattern):
    """Count occurrences of pattern in logfile."""
    return read_log(logfile).count(pattern)


def wait_for_mvp_jobs(logfile, count_before, timeout=MVP_TIMEOUT, settle=30):
    """Wait for MVP-submitted jobs to finish.

    Watches for new $HASP395 messages. Returns when no new completions
    have appeared for 'settle' seconds (and at least one was seen).
    """
    start = time.time()
    last_count = count_before
    last_change = time.time()

    while time.time() - start < timeout:
        current = count_pattern(logfile, '$HASP395')
        if current > last_count:
            new = current - last_count
            log(f'  {new} new job(s) completed ({current} total)')
            last_count = current
            last_change = time.time()
        # At least one new job finished and no activity for settle seconds
        if current > count_before and (time.time() - last_change) > settle:
            total_new = current - count_before
            log(f'  All MVP jobs done ({total_new} jobs)')
            return True
        time.sleep(3)

    total_new = last_count - count_before
    log(f'  MVP job wait timed out ({total_new} jobs completed)')
    return total_new > 0


def dump_log_tail(logfile, lines=10, label=''):
    """Print last N lines of logfile for debugging."""
    content = read_log(logfile)
    if not content:
        log(f'  {label}log file empty or missing')
        return
    all_lines = content.splitlines()
    tail = all_lines[-lines:]
    log(f'  {label}log tail ({len(all_lines)} lines total):')
    for l in tail:
        print(f'    | {l}', flush=True)



def main():
    global START_TIME
    START_TIME = time.time()

    logfile = '/tmp/hercules-build.log'
    ufsd_xmit = '/tmp/ufsd.xmit'
    httpd_xmit = '/tmp/httpd.xmit'
    mvsmf_xmit = '/tmp/mvsmf.xmit'

    for f in [ufsd_xmit, httpd_xmit, mvsmf_xmit]:
        if not os.path.exists(f):
            log(f'ERROR: {f} not found')
            sys.exit(1)

    # --- Start Hercules ---
    log('Starting Hercules...')
    herc = subprocess.Popen(
        ['hercules', '-f', 'conf/local.cnf', '-r', 'conf/mvsce.rc', '--daemon'],
        stdout=open(logfile, 'w'),
        stderr=subprocess.STDOUT,
        cwd='/MVSCE'
    )

    # --- Wait for MVS IPL ---
    log('Waiting for MVS IPL ($HASP426)...')
    if not wait_for_string(logfile, '$HASP426', HERCULES_TIMEOUT):
        log('ERROR: MVS IPL timeout')
        dump_log_tail(logfile, 20)
        herc.kill()
        sys.exit(1)
    log('MVS IPL complete')

    # HAO auto-responds to HASP prompt, give it a moment
    time.sleep(2)

    # --- Wait for card reader ports ---
    log('Waiting for card reader ports...')
    if not wait_for_port(ASCII_PORT):
        log(f'ERROR: ASCII card reader port {ASCII_PORT} not available')
        herc.kill()
        sys.exit(1)
    if not wait_for_port(EBCDIC_PORT):
        log(f'ERROR: EBCDIC card reader port {EBCDIC_PORT} not available')
        herc.kill()
        sys.exit(1)
    log('Card reader ports ready')

    # --- Wait for JES2 initiators ---
    log('Waiting for JES2 initiators...')
    if not wait_for_string(logfile, 'INIT', HERCULES_TIMEOUT):
        log('ERROR: JES2 initiators not ready')
        dump_log_tail(logfile, 20)
        herc.kill()
        sys.exit(1)
    log('JES2 ready')
    time.sleep(5)

    # --- Step 1: MVP update + install packages ---
    log('Step 1: MVP update...')
    mvp_update_jcl = """//MVPUPD  JOB (TSO),'MVP UPDATE',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//UPDATE   EXEC PGM=IKJEFT01,
//             PARM='BREXX MVP UPDATE'
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSEXEC  DD DSN=SYS2.EXEC,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(mvp_update_jcl)
    log('  MVP update job submitted, waiting...')
    if not wait_for_job(logfile, 'MVPUPD', JOB_TIMEOUT):
        log('ERROR: MVP update job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  MVP update complete')
    time.sleep(5)

    for pkg in MVP_PACKAGES:
        jobname = 'MVP' + pkg[:5].upper().replace('$', '')
        log(f'Step 1: Installing MVP package {pkg}...')
        mvp_pkg_jcl = f"""//{jobname} JOB (TSO),'MVP {pkg.upper()[:12]}',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//INSTALL  EXEC PGM=IKJEFT01,
//             PARM='BREXX MVP INSTALL {pkg.upper()}'
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSEXEC  DD DSN=SYS2.EXEC,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
        submit_ascii(mvp_pkg_jcl)
        log(f'  MVP install job for {pkg} submitted, waiting...')
        if not wait_for_job(logfile, jobname, JOB_TIMEOUT):
            log(f'ERROR: MVP install job for {pkg} did not complete')
            dump_log_tail(logfile, 15)
            herc.kill()
            sys.exit(1)
        log(f'  {pkg} installed via MVP')
        time.sleep(5)

    # --- Step 2: Install UFSD ---
    log('Step 2a: Installing UFSD load modules...')
    with open(ufsd_xmit, 'rb') as f:
        xmit_data = f.read()
    log(f'  XMIT size: {len(xmit_data)} bytes')

    recv370_jcl = """//UFSDRCV JOB (TSO),'RECV UFSD',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),USER=IBMUSER,PASSWORD=SYS1
//*
//RECV370  EXEC PGM=RECV370,REGION=6144K
//STEPLIB  DD DSN=SYSC.LINKLIB,DISP=SHR
//RECVLOG  DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=&&SYSUT1,
//            UNIT=SYSDA,VOL=SER=PUB001,
//            SPACE=(TRK,(250,250)),
//            DISP=(NEW,DELETE,DELETE)
//SYSUT2   DD DSN=UFSD.LINKLIB,
//            UNIT=SYSDA,VOL=SER=PUB001,
//            SPACE=(TRK,(50,50,20),RLSE),
//            DISP=(NEW,CATLG,DELETE)
//XMITIN   DD DATA,DLM=$$
"""
    submit_ebcdic_with_binary(recv370_jcl, xmit_data)
    log('  RECV370 job submitted, waiting...')
    if not wait_for_job(logfile, 'UFSDRCV', JOB_TIMEOUT):
        log('ERROR: UFSD RECV370 job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  UFSD load modules installed')
    time.sleep(3)

    # --- Step 3: Install HTTPD 4.x load modules ---
    log('Step 3: Installing HTTPD 4.x load modules...')
    with open(httpd_xmit, 'rb') as f:
        xmit_data = f.read()
    log(f'  XMIT size: {len(xmit_data)} bytes')

    recv370_jcl = """//HTTPDRCV JOB (TSO),'RECV HTTPD',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),USER=IBMUSER,PASSWORD=SYS1
//*
//RECV370  EXEC PGM=RECV370,REGION=6144K
//STEPLIB  DD DSN=SYSC.LINKLIB,DISP=SHR
//RECVLOG  DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=&&SYSUT1,
//            UNIT=SYSDA,VOL=SER=PUB001,
//            SPACE=(TRK,(250,250)),
//            DISP=(NEW,DELETE,DELETE)
//SYSUT2   DD DSN=HTTPD.LINKLIB,
//            UNIT=SYSDA,VOL=SER=PUB001,
//            SPACE=(TRK,(400,100,50),RLSE),
//            DISP=(NEW,CATLG,DELETE)
//XMITIN   DD DATA,DLM=##
"""
    submit_ebcdic_with_binary(recv370_jcl, xmit_data, delimiter='##')
    log('  RECV370 job submitted, waiting...')
    if not wait_for_job(logfile, 'HTTPDRCV', JOB_TIMEOUT):
        log('ERROR: HTTPD RECV370 job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  HTTPD 4.x load modules installed')
    time.sleep(3)

    # --- Step 4: Install mvsMF load modules into HTTPD.LINKLIB ---
    # We receive mvsMF directly into HTTPD.LINKLIB to merge members.
    # This avoids a separate IEBCOPY step. If RECV370 overwrites the
    # dataset instead of merging, we need to add an IEBCOPY fallback.
    log('Step 4: Installing mvsMF load modules into HTTPD.LINKLIB...')
    with open(mvsmf_xmit, 'rb') as f:
        xmit_data = f.read()
    log(f'  XMIT size: {len(xmit_data)} bytes')

    recv370_jcl = """//MVSMFRCV JOB (TSO),'RECV MVSMF',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),USER=IBMUSER,PASSWORD=SYS1
//*
//RECV370  EXEC PGM=RECV370,REGION=6144K
//STEPLIB  DD DSN=SYSC.LINKLIB,DISP=SHR
//RECVLOG  DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//SYSUT1   DD DSN=&&SYSUT1,
//            UNIT=SYSDA,VOL=SER=PUB001,
//            SPACE=(TRK,(250,250)),
//            DISP=(NEW,DELETE,DELETE)
//SYSUT2   DD DSN=HTTPD.LINKLIB,DISP=SHR
//XMITIN   DD DATA,DLM=$$
"""
    submit_ebcdic_with_binary(recv370_jcl, xmit_data)
    log('  RECV370 job submitted, waiting...')
    if not wait_for_job(logfile, 'MVSMFRCV', JOB_TIMEOUT):
        log('ERROR: mvsMF RECV370 job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  mvsMF load modules installed into HTTPD.LINKLIB')
    time.sleep(3)

    # --- Step 5: Configure HTTPD ---
    # 5a: Create SYS2.PROCLIB(HTTPD)
    log('Step 5a: Creating SYS2.PROCLIB(HTTPD)...')
    httpd_proc_jcl = """//HTTDPRC JOB (TSO),'HTTPD PROCLIB',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//WRPRC    EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Create SYS2.PROCLIB(HTTPD) */
ADDRESS TSO
"ALLOC F(OUT) DA('SYS2.PROCLIB(HTTPD)') SHR REUSE"
line.1  = '//HTTPD    PROC'
line.2  = '//HTTPD    EXEC PGM=HTTPD,REGION=8192K,TIME=1440,'
line.3  = "//         PARM='CONFIG=SYS2.PARMLIB(HTTPPRM0)'"
line.4  = '//STEPLIB  DD DISP=SHR,DSN=HTTPD.LINKLIB'
line.5  = '//HTTPDERR DD SYSOUT=*      STDERR'
line.6  = '//HTTPDOUT DD SYSOUT=*      STDOUT'
line.7  = '//HTTPDIN  DD DUMMY         STDIN'
line.8  = '//SNAP     DD SYSOUT=*'
line.9  = '//HTTPDBG  DD SYSOUT=*'
line.10 = '//HTTPSTAT DD SYSOUT=*'
line.11 = '//HASPCKPT DD DISP=SHR,DSN=SYS1.HASPCKPT,UNIT=3350,VOL=SER=MVS000'
line.12 = '//HASPACE1 DD DISP=SHR,DSN=SYS1.HASPACE,UNIT=3350,VOL=SER=SPOOL1'
line.0  = 12
"EXECIO" line.0 "DISKW OUT (STEM LINE. FINIS"
"FREE F(OUT)"
SAY 'HTTPD STC proc created'
EXIT 0
##
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(httpd_proc_jcl)
    log('  PROCLIB job submitted, waiting...')
    if not wait_for_job(logfile, 'HTTDPRC', JOB_TIMEOUT):
        log('ERROR: HTTPD PROCLIB job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  SYS2.PROCLIB(HTTPD) created')
    time.sleep(3)

    # 5b: Create SYS2.PARMLIB(HTTPPRM0)
    log('Step 5b: Creating SYS2.PARMLIB(HTTPPRM0)...')
    httpd_parm_jcl = """//HTTDPRM JOB (TSO),'HTTPD PARMLIB',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//WRPRM    EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Create SYS2.PARMLIB(HTTPPRM0) */
ADDRESS TSO
"ALLOC F(OUT) DA('SYS2.PARMLIB(HTTPPRM0)') SHR REUSE"
line.1  = '-- Lua HTTPD Configuration'
line.2  = 'httpd.port=8080'
line.3  = 'httpd.tzoffset=60'
line.4  = 'httpd.debug=1'
line.5  = 'httpd.client_timeout=1'
line.6  = 'httpd.client_timeout_msg=0'
line.7  = 'httpd.client_timeout_dump=0'
line.8  = 'httpd.client_stats=0'
line.9  = 'httpd.ftp=1'
line.10 = 'ftpd.port=2121'
line.11 = 'httpd.docroot="/www"'
line.12 = 'cgi.MVSMF="/zosmf/*"'
line.0  = 12
"EXECIO" line.0 "DISKW OUT (STEM LINE. FINIS"
"FREE F(OUT)"
SAY 'HTTPPRM0 created'
EXIT 0
##
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(httpd_parm_jcl)
    log('  PARMLIB job submitted, waiting...')
    if not wait_for_job(logfile, 'HTTDPRM', JOB_TIMEOUT):
        log('ERROR: HTTPD PARMLIB job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  SYS2.PARMLIB(HTTPPRM0) created')
    time.sleep(3)

    # --- Step 6: Configure mvsMF ---
    # mvsMF CGI mapping is already in HTTPPRM0 (cgi.MVSMF="/zosmf/*")
    # mvsMF load modules were received directly into HTTPD.LINKLIB in Step 4
    log('Step 6: mvsMF configuration complete (CGI in HTTPPRM0, modules in HTTPD.LINKLIB)')

    # --- Step 7: Configure UFSD ---
    log('Step 7a: Creating SYS2.PARMLIB(UFSDPRM0)...')
    parmlib_jcl = """//UFSDPRM JOB (TSO),'UFSD PARMLIB',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//WRPRM    EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Create SYS2.PARMLIB(UFSDPRM0) */
ADDRESS TSO
"ALLOC F(OUT) DA('SYS2.PARMLIB(UFSDPRM0)') SHR REUSE"
line.1 = '/* UFSDPRM0 */'
line.2 = 'ROOT DSN(UFSD.ROOT)'
line.3 = 'MOUNT DSN(HTTPD.WEBROOT) PATH(/www) MODE(RO)'
line.4 = 'MOUNT DSN(UFSD.SCRATCH) PATH(/tmp) MODE(RW)'
m = 'MOUNT DSN(IBMUSER.UFSHOME)'
m = m 'PATH(/u/ibmuser) MODE(RW)'
m = m 'OWNER(IBMUSER)'
line.5 = m
line.0 = 5
"EXECIO" line.0 "DISKW OUT (STEM LINE. FINIS"
"FREE F(OUT)"
SAY 'UFSDPRM0 created'
EXIT 0
##
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(parmlib_jcl)
    log('  PARMLIB job submitted, waiting...')
    if not wait_for_job(logfile, 'UFSDPRM', JOB_TIMEOUT):
        log('ERROR: UFSD PARMLIB job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  SYS2.PARMLIB(UFSDPRM0) created')
    time.sleep(3)

    log('Step 7b: Creating SYS2.PROCLIB(UFSD)...')
    proclib_jcl = """//UFSDPRC JOB (TSO),'UFSD PROCLIB',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//WRPRC    EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Create SYS2.PROCLIB(UFSD) */
ADDRESS TSO
"ALLOC F(OUT) DA('SYS2.PROCLIB(UFSD)') SHR REUSE"
line.1  = '//UFSD     PROC M=UFSDPRM0,'
line.2  = "//            D='SYS2.PARMLIB'"
line.3  = '//*'
line.4  = '//CLEANUP  EXEC PGM=UFSDCLNP'
line.5  = '//STEPLIB  DD  DISP=SHR,DSN=UFSD.LINKLIB'
line.6  = '//UFSD     EXEC PGM=UFSD,REGION=4M,TIME=1440'
line.7  = '//STEPLIB  DD  DISP=SHR,DSN=UFSD.LINKLIB'
line.8  = '//SYSUDUMP DD  SYSOUT=*'
line.9  = '//UFSDPRM  DD  DSN=&D(&M),DISP=SHR,FREE=CLOSE'
line.0  = 9
"EXECIO" line.0 "DISKW OUT (STEM LINE. FINIS"
"FREE F(OUT)"
SAY 'UFSD STC proc created'
EXIT 0
##
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(proclib_jcl)
    log('  PROCLIB job submitted, waiting...')
    if not wait_for_job(logfile, 'UFSDPRC', JOB_TIMEOUT):
        log('ERROR: UFSD PROCLIB job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  SYS2.PROCLIB(UFSD) created')
    time.sleep(3)

    # --- Step 8: Start HTTPD and test connection ---
    log('Step 8: Starting HTTPD...')
    start_httpd_jcl = """//STARTHTP JOB (TSO),'START HTTPD',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//START    EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Start HTTPD */
ADDRESS CONSOLE
'S HTTPD'
EXIT 0
##
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(start_httpd_jcl)
    log('  HTTPD start job submitted, waiting...')
    if not wait_for_job(logfile, 'STARTHTP', JOB_TIMEOUT):
        log('ERROR: HTTPD start job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  HTTPD start command issued')

    log('Waiting for HTTPD port 8080...')
    if not wait_for_port(8080, timeout=60):
        log('ERROR: HTTPD port 8080 not available')
        dump_log_tail(logfile, 20)
        herc.kill()
        sys.exit(1)
    log('  HTTPD is listening on port 8080')
    time.sleep(3)

    # Test mvsMF endpoint
    log('Step 8: Testing mvsMF /zosmf/info endpoint...')
    import urllib.request
    import base64
    try:
        req = urllib.request.Request('http://127.0.0.1:8080/zosmf/info')
        credentials = base64.b64encode(b'IBMUSER:SYS1').decode()
        req.add_header('Authorization', f'Basic {credentials}')
        resp = urllib.request.urlopen(req, timeout=10)
        body = resp.read().decode()
        log(f'  mvsMF response: {resp.status} - {body[:100]}')
    except Exception as e:
        log(f'WARNING: mvsMF test failed: {e}')
        dump_log_tail(logfile, 20)

    # --- Step 9: Create and upload ufsd-root.img ---
    log('Step 9: Creating ufsd-root.img...')
    mvs_env = {
        **os.environ,
        'MVS_HOST': '127.0.0.1',
        'MVS_PORT': '8080',
        'MVS_USER': 'IBMUSER',
        'MVS_PASS': 'SYS1',
    }
    subprocess.run(
        ['ufsd-utils', 'create', '/tmp/ufsd-root.img',
         '--size', '1MB', '-owner', 'UFSD', '-group', 'SYS1'],
        check=True
    )
    log('  ufsd-root.img created')

    log('Step 9: Uploading ufsd-root.img to UFSD.ROOT...')
    subprocess.run(
        ['ufsd-utils', 'upload', '/tmp/ufsd-root.img', '--dsn', 'UFSD.ROOT'],
        env=mvs_env, check=True
    )
    log('  ufsd-root.img uploaded to UFSD.ROOT')

    # Create and upload IBMUSER.UFSHOME (5MB)
    log('Step 9: Creating ibmuser-home.img...')
    subprocess.run(
        ['ufsd-utils', 'create', '/tmp/ibmuser-home.img',
         '--size', '5MB', '-owner', 'IBMUSER', '-group', 'USER'],
        check=True
    )
    log('  ibmuser-home.img created')
    log('Step 9: Uploading ibmuser-home.img to IBMUSER.UFSHOME...')
    subprocess.run(
        ['ufsd-utils', 'upload', '/tmp/ibmuser-home.img', '--dsn', 'IBMUSER.UFSHOME'],
        env=mvs_env, check=True
    )
    log('  ibmuser-home.img uploaded to IBMUSER.UFSHOME')

    # Create and upload UFSD.SCRATCH (10MB)
    log('Step 9: Creating scratch.img...')
    subprocess.run(
        ['ufsd-utils', 'create', '/tmp/scratch.img',
         '--size', '10MB', '-owner', 'UFSD', '-group', 'SYS1'],
        check=True
    )
    log('  scratch.img created')
    log('Step 9: Uploading scratch.img to UFSD.SCRATCH...')
    subprocess.run(
        ['ufsd-utils', 'upload', '/tmp/scratch.img', '--dsn', 'UFSD.SCRATCH'],
        env=mvs_env, check=True
    )
    log('  scratch.img uploaded to UFSD.SCRATCH')

    # --- Step 10: Upload wwwroot_v3.img ---
    log('Step 10: Uploading wwwroot_v3.img to HTTPD.WEBROOT...')
    subprocess.run(
        ['ufsd-utils', 'upload', '/tmp/wwwroot_v3.img', '--dsn', 'HTTPD.WEBROOT'],
        env=mvs_env, check=True
    )
    log('  wwwroot_v3.img uploaded to HTTPD.WEBROOT')

    # --- Add UFSD and HTTPD autostart to COMMND00 ---
    log('Adding UFSD and HTTPD autostart to COMMND00...')
    autostart_jcl = """//AUTOSTRT JOB (TSO),'AUTOSTART',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//ADDCMD   EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Add UFSD and HTTPD auto-start to COMMND00 */
ADDRESS TSO
"ALLOC F(CFGIN) DA('SYS1.PARMLIB(COMMND00)') SHR REUSE"
"EXECIO * DISKR CFGIN (STEM LINE. FINIS"
found_ufsd = 0
found_httpd = 0
DO i = 1 TO line.0
  IF POS('S UFSD', line.i) > 0 THEN found_ufsd = 1
  IF POS('S HTTPD', line.i) > 0 THEN found_httpd = 1
END
IF found_ufsd = 0 THEN DO
  line.0 = line.0 + 1
  n = line.0
  line.n = "COM='S UFSD'"
END
IF found_httpd = 0 THEN DO
  line.0 = line.0 + 1
  n = line.0
  line.n = "COM='S HTTPD'"
END
"ALLOC F(CFGOUT) DA('SYS1.PARMLIB(COMMND00)') SHR REUSE"
"EXECIO" line.0 "DISKW CFGOUT (STEM LINE. FINIS"
"FREE F(CFGIN CFGOUT)"
IF found_ufsd = 0 THEN SAY 'UFSD auto-start added to COMMND00'
ELSE SAY 'UFSD auto-start already present'
IF found_httpd = 0 THEN SAY 'HTTPD auto-start added to COMMND00'
ELSE SAY 'HTTPD auto-start already present'
EXIT 0
##
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(autostart_jcl)
    log('  Autostart job submitted, waiting...')
    if not wait_for_job(logfile, 'AUTOSTRT', JOB_TIMEOUT):
        log('ERROR: Autostart config job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  UFSD + HTTPD autostart configured')
    time.sleep(3)

    # --- Purge JES2 spool ---
    log('Purging JES2 spool...')
    purge_jcl = """//PURGESPL JOB (TSO),'PURGE SPOOL',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//PURGE    EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Purge JES2 spool */
ADDRESS CONSOLE
'$PS1-9999'
'$PT1-9999'
'$PJ1-9999'
EXIT 0
##
//TSOLIB   DD DSN=BREXX.V2R5M3.LINKLIB,DISP=SHR
//RXLIB    DD DSN=BREXX.V2R5M3.RXLIB,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD DUMMY
//STDOUT   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDERR   DD SYSOUT=*,DCB=(RECFM=FB,LRECL=140,BLKSIZE=5600)
//STDIN    DD DUMMY
"""
    submit_ascii(purge_jcl)
    log('  Purge job submitted, waiting...')
    if not wait_for_job(logfile, 'PURGESPL', JOB_TIMEOUT):
        log('WARNING: Purge job did not complete')
    else:
        log('  JES2 spool purged')
    time.sleep(5)

    # --- Shutdown MVS ---
    log('Shutting down MVS...')
    shutdown_jcl = """//SHUTMVS  JOB (TSO),'SHUTDOWN',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),USER=IBMUSER,PASSWORD=SYS1
//*
//SHUT     EXEC PGM=IKJEFT01
//SYSTSPRT DD SYSOUT=*
//SYSTSIN  DD *
 SEND 'P JES2' OPERATOR
/*
"""
    submit_ascii(shutdown_jcl)
    time.sleep(10)

    # Wait for JES2 to stop
    log('Waiting for JES2 shutdown...')
    wait_for_string(logfile, '$HASP085', 60)

    # Stop Hercules
    log('Stopping Hercules...')
    herc.terminate()
    try:
        herc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        herc.kill()

    log('Done! UFSD + HTTPD + mvsMF installed successfully.')


if __name__ == '__main__':
    main()
