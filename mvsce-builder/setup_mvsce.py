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
    sock.send(jcl.encode())
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
    sock.send(data)
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
    mvsmf_xmit = '/tmp/mvsmf.xmit'

    if not os.path.exists(mvsmf_xmit):
        log(f'ERROR: {mvsmf_xmit} not found')
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

    # --- Step 1: Install HTTPD via MVP REXX on MVS ---
    # The Python MVP script only submits an unzip job for ZIP packages,
    # but doesn't run the actual install. We call the REXX-based MVP
    # directly on MVS which handles the full install (like TSO `RX MVP`).
    log('Step 1: Installing HTTPD via MVP REXX...')
    mvp_jcl = """//MVPHTTP JOB (TSO),'MVP INSTALL',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//INSTALL  EXEC PGM=IKJEFT01,
//             PARM='BREXX MVP INSTALL HTTPD'
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
    submit_ascii(mvp_jcl)
    log('  MVP install job submitted, waiting...')
    if not wait_for_job(logfile, 'MVPHTTP', JOB_TIMEOUT):
        log('ERROR: MVP HTTPD install job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  HTTPD installed via MVP')
    time.sleep(5)

    # --- Step 2: Upload mvsMF XMIT via RECV370 ---
    log('Step 2: Installing mvsMF load module...')
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
//SYSUT1   DD UNIT=VIO,SPACE=(CYL,(50,10)),DISP=(NEW,DELETE)
//SYSUT2   DD DSN='HTTPD.LINKLIB',DISP=SHR
//XMITIN   DD DATA,DLM=$$
"""
    submit_ebcdic_with_binary(recv370_jcl, xmit_data)
    log('  RECV370 job submitted, waiting...')
    if not wait_for_job(logfile, 'MVSMFRCV', JOB_TIMEOUT):
        log('ERROR: mvsMF RECV370 job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  mvsMF load module installed')
    time.sleep(3)

    # --- Step 3: Add mvsMF CGI mapping to HTTPD config ---
    log('Step 3: Adding mvsMF CGI config...')
    cgi_jcl = """//CFGMVSM JOB (TSO),'ADD MVSMF CGI',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//ADDCGI   EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Add mvsMF CGI mapping to HTTPD config */
ADDRESS TSO
"ALLOC F(CFGIN) DA('HTTPD.LUA(HTTPD)') SHR REUSE"
"EXECIO * DISKR CFGIN (STEM LINE. FINIS"
found = 0
DO i = 1 TO line.0
  IF POS('cgi.MVSMF', line.i) > 0 THEN found = 1
END
IF found = 0 THEN DO
  line.0 = line.0 + 1
  n = line.0
  line.n = 'cgi.MVSMF="/zosmf/*"'
END
"ALLOC F(CFGOUT) DA('HTTPD.LUA(HTTPD)') SHR REUSE"
"EXECIO" line.0 "DISKW CFGOUT (STEM LINE. FINIS"
"FREE F(CFGIN CFGOUT)"
IF found = 0 THEN SAY 'MVSMF CGI mapping added'
ELSE SAY 'MVSMF CGI mapping already present'
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
    submit_ascii(cgi_jcl)
    log('  CGI config job submitted, waiting...')
    if not wait_for_job(logfile, 'CFGMVSM', JOB_TIMEOUT):
        log('ERROR: CGI config job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  mvsMF CGI config added')
    time.sleep(3)

    # --- Step 4: Add HTTPD autostart to COMMND00 ---
    log('Step 4: Adding HTTPD autostart...')
    autostart_jcl = """//AUTOHTTP JOB (TSO),'HTTPD AUTOSTART',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),REGION=0M,USER=IBMUSER,PASSWORD=SYS1
//*
//ADDCMD   EXEC PGM=IKJEFT01,PARM='BREXX EXEC'
//EXEC     DD DATA,DLM=##
/* REXX - Add HTTPD auto-start to COMMND00 */
ADDRESS TSO
"ALLOC F(CFGIN) DA('SYS1.PARMLIB(COMMND00)') SHR REUSE"
"EXECIO * DISKR CFGIN (STEM LINE. FINIS"
found = 0
DO i = 1 TO line.0
  IF POS('S HTTPD', line.i) > 0 THEN found = 1
END
IF found = 0 THEN DO
  line.0 = line.0 + 1
  n = line.0
  line.n = "COM='S HTTPD'"
END
"ALLOC F(CFGOUT) DA('SYS1.PARMLIB(COMMND00)') SHR REUSE"
"EXECIO" line.0 "DISKW CFGOUT (STEM LINE. FINIS"
"FREE F(CFGIN CFGOUT)"
IF found = 0 THEN SAY 'HTTPD auto-start added to COMMND00'
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
    if not wait_for_job(logfile, 'AUTOHTTP', JOB_TIMEOUT):
        log('ERROR: Autostart config job did not complete')
        dump_log_tail(logfile, 15)
        herc.kill()
        sys.exit(1)
    log('  HTTPD autostart configured')
    time.sleep(3)

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

    log('Done! HTTPD + mvsMF installed successfully.')


if __name__ == '__main__':
    main()
