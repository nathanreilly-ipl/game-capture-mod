/* tls32.so: lets Wine run 32-bit Windows programs where the 32-bit system call entry is
 * forbidden (a container whose seccomp filter kills every `int $0x80` call).
 *
 * Wine's 64-bit ntdll.so gives each thread of a 32-bit Windows program a 32-bit %fs segment
 * for its TEB by calling set_thread_area through `int $0x80` (alloc_fs_sel in
 * dlls/ntdll/unix/signal_x86_64.c): the 64-bit system call table has no set_thread_area. Under
 * such a filter the first 32-bit program dies with "Bad system call".
 *
 * Preloaded into Wine (LD_PRELOAD), this library waits for ntdll.so to be loaded and replaces
 * that one function. The replacement sets the same per-thread GDT entry through an interface
 * the 64-bit table does have: a short-lived child process attaches to the thread with ptrace
 * and calls PTRACE_SET_THREAD_AREA. No 32-bit system call is made; 32-bit Windows code never
 * makes system calls itself (Wine's WoW64 layer turns them into 64-bit ones).
 *
 * It also turns Wine's other `int $0x80` call (modify_ldt, for NtSetLdtEntries) into the 64-bit
 * system call with the same arguments.
 *
 * Found and measured on a CoreWeave Slurm node, 2026-11-23, wine-staging 11.0 (GE-Proton11-12).
 * TLS32_DEBUG=1 prints what it does.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <link.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <asm/ldt.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/ptrace.h>
#include <sys/syscall.h>
#include <sys/wait.h>

#ifndef PTRACE_SET_THREAD_AREA
#define PTRACE_SET_THREAD_AREA 26
#endif
#define GDT_ENTRY_TLS_MIN 12        /* x86-64: the three per-thread GDT entries are 12, 13, 14 */

static int debug = -1;

static void say(const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    int n;
    if (debug < 0) debug = getenv("TLS32_DEBUG") ? 1 : 0;
    if (!debug) return;
    va_start(ap, fmt);
    n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n > 0) (void)!write(2, buf, n < (int)sizeof(buf) ? n : (int)sizeof(buf) - 1);
}

/* The replacement for alloc_fs_sel(sel, base): GDT entry `sel` (-1: the first of the three) of
 * the calling thread gets a 32-bit segment at `base`; returns its selector, as the original. */
static int alloc_fs_sel(int sel, void *base)
{
    struct user_desc desc;
    int idx = sel < 0 ? GDT_ENTRY_TLS_MIN : sel;
    int fds[2], err = EIO, status;
    pid_t tid = syscall(SYS_gettid), child;

    memset(&desc, 0, sizeof(desc));
    desc.entry_number = idx;
    desc.base_addr = (unsigned int)(uintptr_t)base;
    desc.limit = 0xffffffff;        /* as Wine asks for it: flags 0x41 */
    desc.seg_32bit = 1;
    desc.useable = 1;

    if (pipe2(fds, O_CLOEXEC) < 0) goto done;
    prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0);     /* Wine sets the same for its debugger */
    child = syscall(SYS_clone, 0, 0, 0, 0, 0);              /* a plain fork that raises no SIGCHLD */
    if (child == 0)
    {
        int e = 0;
        if (syscall(SYS_ptrace, PTRACE_SEIZE, tid, 0, 0) < 0) e = errno ? errno : EIO;
        else
        {
            if (syscall(SYS_ptrace, PTRACE_INTERRUPT, tid, 0, 0) < 0) e = errno ? errno : EIO;
            else
            {
                syscall(SYS_wait4, tid, &status, __WALL, 0);
                if (syscall(SYS_ptrace, PTRACE_SET_THREAD_AREA, tid, (long)idx, &desc) < 0) e = errno ? errno : EIO;
            }
            syscall(SYS_ptrace, PTRACE_DETACH, tid, 0, 0);
        }
        (void)!write(fds[1], &e, sizeof(e));
        syscall(SYS_exit_group, 0);
    }
    close(fds[1]);
    if (child > 0)
    {
        ssize_t n;
        do n = read(fds[0], &err, sizeof(err)); while (n < 0 && errno == EINTR);
        if (n != sizeof(err)) err = EIO;
        while (syscall(SYS_wait4, child, &status, __WCLONE, 0) < 0 && errno == EINTR) {}
    }
    else err = errno;
    close(fds[0]);
done:
    say("tls32: thread %d, GDT entry %d at %p: %s\n", (int)tid, idx, base, err ? strerror(err) : "set");
    if (err) return -1;             /* Wine does not check; a 32-bit program will then fault */
    return (idx << 3) | 3;
}

static unsigned char *find(unsigned char *start, size_t len, const unsigned char *pat, size_t n)
{
    return memmem(start, len, pat, n);
}

struct seg { uintptr_t base; const struct dl_phdr_info *hit; unsigned char *text; size_t text_len; };

static int phdr_cb(struct dl_phdr_info *info, size_t size, void *data)
{
    struct seg *s = data;
    (void)size;
    const char *name = info->dlpi_name;
    size_t n = name ? strlen(name) : 0;
    int i;
    if (n < 9 || strcmp(name + n - 9, "/ntdll.so")) return 0;
    for (i = 0; i < info->dlpi_phnum; i++)
    {
        const ElfW(Phdr) *p = &info->dlpi_phdr[i];
        if (p->p_type == PT_LOAD && (p->p_flags & PF_X))
        {
            s->text = (unsigned char *)(info->dlpi_addr + p->p_vaddr);
            s->text_len = p->p_memsz;
            return 1;
        }
    }
    return 0;
}

static int write_code(unsigned char *at, const unsigned char *bytes, size_t n)
{
    long page = sysconf(_SC_PAGESIZE);
    unsigned char *lo = (unsigned char *)((uintptr_t)at & ~(page - 1));
    size_t span = (at + n) - lo;
    if (mprotect(lo, span, PROT_READ | PROT_WRITE | PROT_EXEC) < 0) return -1;
    memcpy(at, bytes, n);
    mprotect(lo, span, PROT_READ | PROT_EXEC);
    return 0;
}

static int patched;

static void patch_ntdll(void)
{
    /* alloc_fs_sel: ... mov %esp,%ebx; mov $0xf3,%eax; int $0x80; mov (%rsp),%eax */
    static const unsigned char sig_fs[] = { 0x89, 0xe3, 0xb8, 0xf3, 0x00, 0x00, 0x00, 0xcd, 0x80, 0x8b, 0x04, 0x24 };
    static const unsigned char prologue[] = { 0x53, 0x41, 0x54, 0x49, 0x89, 0xe4 };   /* push %rbx; push %r12; mov %rsp,%r12 */
    /* the LDT writer: mov $0x7b,%eax; mov $0x11,%ebx; mov %esp,%ecx; mov $0x10,%edx; int $0x80 */
    static const unsigned char sig_ldt[] = { 0xb8, 0x7b, 0x00, 0x00, 0x00, 0xbb, 0x11, 0x00, 0x00, 0x00, 0x89, 0xe1,
                                             0xba, 0x10, 0x00, 0x00, 0x00, 0xcd, 0x80 };
    /* the same call in the 64-bit table: mov $154,%eax; mov $0x11,%edi; mov %esp,%esi; mov $0x10,%edx; syscall */
    static const unsigned char new_ldt[] = { 0xb8, 0x9a, 0x00, 0x00, 0x00, 0xbf, 0x11, 0x00, 0x00, 0x00, 0x89, 0xe6,
                                             0xba, 0x10, 0x00, 0x00, 0x00, 0x0f, 0x05 };
    struct seg s = { 0 };
    unsigned char *hit, *fn, jump[12] = { 0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0xff, 0xe0 };   /* movabs $addr,%rax; jmp *%rax */
    uintptr_t target = (uintptr_t)alloc_fs_sel;
    int back;

    if (patched || !dl_iterate_phdr(phdr_cb, &s)) return;
    patched = 1;
    hit = find(s.text, s.text_len, sig_fs, sizeof(sig_fs));
    if (!hit) { say("tls32: ntdll.so has no int $0x80 set_thread_area call (another Wine?); nothing changed\n"); return; }
    for (fn = NULL, back = 8; back <= 96; back++)
        if (!memcmp(hit - back, prologue, sizeof(prologue))) { fn = hit - back; break; }
    if (!fn) { say("tls32: the function around the call was not recognised; nothing changed\n"); return; }
    memcpy(jump + 2, &target, sizeof(target));
    if (write_code(fn, jump, sizeof(jump)) < 0) { say("tls32: could not write to ntdll.so's code: %s\n", strerror(errno)); return; }
    say("tls32: alloc_fs_sel at %p now sets the thread's GDT entry through ptrace\n", (void *)fn);
    hit = find(s.text, s.text_len, sig_ldt, sizeof(sig_ldt));
    if (hit && !write_code(hit, new_ldt, sizeof(new_ldt))) say("tls32: the modify_ldt call at %p is now a 64-bit system call\n", (void *)hit);
}

/* Wine's loader opens ntdll.so with dlopen and calls into it at once: patch between the two. */
void *dlopen(const char *file, int mode)
{
    static void *(*real)(const char *, int);
    void *ret;
    if (!real) real = dlsym(RTLD_NEXT, "dlopen");
    ret = real(file, mode);
    if (ret && !patched && file)
    {
        size_t n = strlen(file);
        if (n >= 8 && !strcmp(file + n - 8, "ntdll.so")) patch_ntdll();
    }
    return ret;
}

__attribute__((constructor)) static void init(void)
{
    patch_ntdll();      /* in case ntdll.so is already there */
}
