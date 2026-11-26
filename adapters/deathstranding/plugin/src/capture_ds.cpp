// capture_ds.asi: Death Stranding Director's Cut's script layer for captures, which the game lacks.
// An ASI loader (Ultimate ASI Loader as winhttp.dll) loads it at start. It hooks three places in
// ds.exe, found by byte patterns (adapters/deathstranding/probes, 2026-11-25, game 1.004):
//
//   the frame's clock update (RVA 0x2F3AAD0 in 1.004): marks the start of each frame;
//   Clock::Advance (RVA 0x2F3ACF0): every game clock gets its frame step here, in 32.32 fixed point
//       ticks (2^32 per second). Holding gives every clock a step of 0; a step command spreads an
//       exact number of ticks evenly over a number of frames (what the game's float rounding
//       drops is carried into the next frame), then holds again;
//   the render camera's view setup (RVA 0x361AEE2): after the game has put its camera (position,
//       rotation, vertical FOV) into the render camera and before the view matrices are built from
//       it. An override puts our camera there instead.
//
// Control: a file the capture scripts write, read every 2 ms:
//     <seq> run                       the game's own time
//     <seq> hold                      every clock stands still (steps of 0)
//     <seq> step <ticks> <frames> [force]   advance exactly <ticks> over <frames> frames, then hold;
//                                     force: at scale 1 even while the game pauses (photo mode)
//     <seq> cam <x> <y> <z> <r00> <r01> <r02> <r10> <r11> <r12> <r20> <r21> <r22> <fov>
//                                     render from this camera (world position, rows of the rotation
//                                     as the game stores them, vertical FOV in degrees)
//     <seq> cam off                   the game's own camera
// After each command, and every 250 ms, the status file says what is in force and what the game
// last did: seq=, state=, frame=, step_left=, ticks=, cam=, game_pos=, game_rot=, game_fov=,
// render_pos=, render_fov=, hooks=. A control file there when the game starts is removed unread.
//
// capture_ds.ini, next to the ASI:
//     [capture]
//     Control=<absolute path>   Status=<absolute path>   Log=<absolute path, optional>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>

#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

namespace {

std::string g_control, g_status, g_log;
std::mutex g_log_mu;

void logf(const char* fmt, ...) {
	std::lock_guard<std::mutex> lk(g_log_mu);
	FILE* f = fopen(g_log.c_str(), "a");
	if (!f) return;
	SYSTEMTIME t;
	GetLocalTime(&t);
	fprintf(f, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
	va_list ap;
	va_start(ap, fmt);
	vfprintf(f, fmt, ap);
	va_end(ap);
	fputc('\n', f);
	fclose(f);
}

// ---------------------------------------------------------------- state shared with the hooks

enum Mode { RUN = 0, HOLD = 1, STEP = 2 };
std::atomic<int> g_mode{RUN};
std::atomic<uint64_t> g_step_ticks{0};   // ticks still to give (STEP)
std::atomic<int64_t> g_step_frames{0};   // frames still to spread them over
uint64_t g_frame_share = 0;              // this frame's step for every clock (main thread only)
int g_frame_mode = RUN;                  // the mode for the frame in progress (main thread only)
std::atomic<uint64_t> g_frame{0};
std::atomic<uint64_t> g_given{0};        // ticks given in steps since the last hold/step command

struct Cam {
	double pos[3];
	float rot[9];
	float fov;
};
std::mutex g_cam_mu;
bool g_cam_on = false;
Cam g_cam{};          // the override
Cam g_game{};         // what the game had put in the render camera, last frame
Cam g_rendered{};     // what was rendered (after the override)
void* g_render_cam = nullptr;
std::atomic<uint64_t> g_cam_calls{0};

uint8_t* g_base = nullptr;
size_t g_size = 0;
std::string g_hooks;

// ---------------------------------------------------------------- patterns and hooks

uint8_t* find(const char* pat) {
	std::vector<int> bytes;
	for (const char* p = pat; *p;) {
		while (*p == ' ') ++p;
		if (!*p) break;
		if (*p == '?') {
			bytes.push_back(-1);
			while (*p == '?') ++p;
		} else {
			bytes.push_back((int)strtoul(p, nullptr, 16));
			p += 2;
		}
	}
	auto* dos = (IMAGE_DOS_HEADER*)g_base;
	auto* nt = (IMAGE_NT_HEADERS*)(g_base + dos->e_lfanew);
	auto* sec = IMAGE_FIRST_SECTION(nt);
	uint8_t* hit = nullptr;
	int hits = 0;
	for (int s = 0; s < nt->FileHeader.NumberOfSections; ++s, ++sec) {
		if (!(sec->Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
		uint8_t* start = g_base + sec->VirtualAddress;
		size_t n = sec->Misc.VirtualSize;
		for (size_t i = 0; i + bytes.size() <= n; ++i) {
			bool ok = true;
			for (size_t k = 0; k < bytes.size(); ++k)
				if (bytes[k] >= 0 && start[i + k] != (uint8_t)bytes[k]) { ok = false; break; }
			if (ok) { if (!hit) hit = start + i; ++hits; }
		}
	}
	if (hits != 1) {
		logf("pattern %s: %d matches", pat, hits);
		return nullptr;
	}
	return hit;
}

uint8_t* alloc_near(uint8_t* where, size_t size) {
	// executable memory for stubs and trampolines (absolute jumps, so anywhere will do)
	(void)where;
	return (uint8_t*)VirtualAlloc(nullptr, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
}

void put_jmp(uint8_t* at, const void* to) {   // jmp qword ptr [rip+0]; dq to   (14 bytes)
	at[0] = 0xFF; at[1] = 0x25;
	memset(at + 2, 0, 4);
	memcpy(at + 6, &to, 8);
}

bool patch(uint8_t* at, const uint8_t* bytes, size_t n) {
	DWORD old;
	if (!VirtualProtect(at, n, PAGE_EXECUTE_READWRITE, &old)) return false;
	memcpy(at, bytes, n);
	VirtualProtect(at, n, old, &old);
	FlushInstructionCache(GetCurrentProcess(), at, n);
	return true;
}

// Entry hook: `stolen` plain bytes (no RIP-relative operands) move to a trampoline that jumps back.
void* hook_entry(uint8_t* fn, size_t stolen, void* detour) {
	uint8_t* tramp = alloc_near(fn, 64);
	memcpy(tramp, fn, stolen);
	put_jmp(tramp + stolen, fn + stolen);
	uint8_t jmp[32];
	memset(jmp, 0x90, sizeof jmp);
	put_jmp(jmp, detour);
	if (!patch(fn, jmp, stolen)) return nullptr;
	return tramp;
}

// Mid-function hook: saves the volatile registers, calls cb(rsi), restores them, runs the `stolen`
// plain bytes and jumps back.
bool hook_mid_rsi(uint8_t* at, size_t stolen, void (*cb)(void*)) {
	uint8_t* s = alloc_near(at, 256);
	uint8_t* p = s;
	auto emit = [&](std::initializer_list<uint8_t> b) { for (uint8_t x : b) *p++ = x; };
	emit({0x9C});                                   // pushfq
	emit({0x50, 0x51, 0x52, 0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53});   // push rax rcx rdx r8 r9 r10 r11
	emit({0x55});                                   // push rbp
	emit({0x48, 0x89, 0xE5});                       // mov rbp, rsp
	emit({0x48, 0x83, 0xE4, 0xF0});                 // and rsp, -16
	emit({0x48, 0x81, 0xEC, 0x80, 0x00, 0x00, 0x00});   // sub rsp, 0x80
	for (int i = 0; i < 6; ++i) {                   // movdqu [rsp+0x20+16i], xmm_i
		emit({0xF3, 0x0F, 0x7F, (uint8_t)(0x44 | (i << 3)), 0x24, (uint8_t)(0x20 + 16 * i)});
	}
	emit({0x48, 0x89, 0xF1});                       // mov rcx, rsi
	emit({0x48, 0xB8}); memcpy(p, &cb, 8); p += 8;  // mov rax, cb
	emit({0xFF, 0xD0});                             // call rax
	for (int i = 0; i < 6; ++i) {                   // movdqu xmm_i, [rsp+0x20+16i]
		emit({0xF3, 0x0F, 0x6F, (uint8_t)(0x44 | (i << 3)), 0x24, (uint8_t)(0x20 + 16 * i)});
	}
	emit({0x48, 0x89, 0xEC});                       // mov rsp, rbp
	emit({0x5D});                                   // pop rbp
	emit({0x41, 0x5B, 0x41, 0x5A, 0x41, 0x59, 0x41, 0x58, 0x5A, 0x59, 0x58});   // pop r11 r10 r9 r8 rdx rcx rax
	emit({0x9D});                                   // popfq
	memcpy(p, at, stolen); p += stolen;             // the displaced instructions
	put_jmp(p, at + stolen); p += 14;
	uint8_t jmp[32];
	memset(jmp, 0x90, sizeof jmp);
	put_jmp(jmp, s);
	return patch(at, jmp, stolen);
}

// ---------------------------------------------------------------- the hooks

// Both return what the originals leave in rax, in case a caller reads it.
using AdvanceFn = uint64_t(__fastcall*)(void* clock, uint64_t extra, uint64_t dt);
AdvanceFn g_advance = nullptr;
using FrameFn = uint64_t(__fastcall*)(void* timers, void* a, void* b);
FrameFn g_frame_fn = nullptr;

// The order within a frame: the game timers tick (tick_hook), then the frame's clock update
// (frame_hook, which calls Clock::Advance for each clock). So frame_hook decides, after the clock
// update, what the next frame does; a command takes effect from the frame after it arrives.
void schedule_next_frame() {
	int mode = g_mode.load();
	if (mode == STEP) {
		int64_t frames = g_step_frames.load();
		uint64_t left = g_step_ticks.load();
		if (frames <= 0) {
			g_mode = HOLD;
			mode = HOLD;
			g_frame_share = 0;
		} else {
			uint64_t share = left / (uint64_t)frames;   // even shares; the last one takes the remainder
			if (frames == 1) share = left;
			g_frame_share = share;
			g_step_ticks = left - share;
			g_step_frames = frames - 1;
			g_given += share;
		}
	} else {
		g_frame_share = 0;
	}
	g_frame_mode = mode;
}

uint64_t __fastcall frame_hook(void* timers, void* a, void* b) {
	uint64_t r = g_frame_fn(timers, a, b);
	g_frame++;
	schedule_next_frame();
	return r;
}

uint64_t __fastcall advance_hook(void* clock, uint64_t extra, uint64_t dt) {
	int mode = g_frame_mode;
	if (mode == HOLD) return g_advance(clock, 0, 0);
	if (mode == STEP) return g_advance(clock, 0, g_frame_share);
	return g_advance(clock, extra, dt);
}

// Timer::Tick(timer, raw): the timer's step is (int)((float)raw * scale), the scale being the
// game's (0 while it pauses). Held: a raw step of 0. Stepping: the frame's share (exact up to the
// float's 24 bits, about 1 tick of 2^-32 s in a share of 1/240 s).
using TickFn = uint64_t(__fastcall*)(void* timer, uint32_t raw);
TickFn g_tick = nullptr;
std::atomic<uint64_t> g_ticks_called{0};

std::atomic<bool> g_force{false};   // step at scale 1 even while the game pauses (photo mode)

// The timers seen (the game ticks two each frame): their accumulated time (ticks at +8) for the status.
void* g_timers[4] = {};
std::atomic<uint64_t> g_timer_acc[4];

uint64_t __fastcall tick_hook(void* timer, uint32_t raw) {
	g_ticks_called++;
	int mode = g_frame_mode;
	uint64_t r;
	if (mode == HOLD) {
		r = g_tick(timer, 0);
	} else if (mode == STEP) {
		if (g_force) *(float*)((uint8_t*)timer + 0x24) = 1.0f;   // the game sets it again every frame
		r = g_tick(timer, (uint32_t)g_frame_share);
		// The tick goes through a float (24 bits): a share of 17.9 million ticks comes out a tick or
		// two short. What the game clock (the first timer) actually got goes back into what is left,
		// so the step lands exact but for the last frame's rounding (2026-11-25: 7 ticks short over
		// 8 frames without this).
		if (timer == g_timers[0] && g_step_frames.load() > 0) {
			uint32_t got = *(uint32_t*)((uint8_t*)timer + 0x1c);
			if (got < g_frame_share) {
				g_step_ticks += g_frame_share - got;
				g_given -= g_frame_share - got;
			}
		}
	} else {
		r = g_tick(timer, raw);
	}
	for (int i = 0; i < 4; ++i) {
		if (!g_timers[i]) g_timers[i] = timer;
		if (g_timers[i] == timer) {
			g_timer_acc[i] = *(uint64_t*)((uint8_t*)timer + 8);
			break;
		}
	}
	return r;
}

void cam_hook(void* cam) {
	auto* c = (uint8_t*)cam;
	g_cam_calls++;
	std::lock_guard<std::mutex> lk(g_cam_mu);
	if (!g_render_cam) g_render_cam = cam;
	if (cam != g_render_cam) return;
	memcpy(g_game.pos, c + 0x20, 24);
	memcpy(g_game.rot, c + 0x38, 36);
	memcpy(&g_game.fov, c + 0x74, 4);
	if (g_cam_on) {
		memcpy(c + 0x20, g_cam.pos, 24);
		memcpy(c + 0x38, g_cam.rot, 36);
		memcpy(c + 0x74, &g_cam.fov, 4);
	}
	memcpy(g_rendered.pos, c + 0x20, 24);
	memcpy(g_rendered.rot, c + 0x38, 36);
	memcpy(&g_rendered.fov, c + 0x74, 4);
}

// ---------------------------------------------------------------- control and status

long g_seq = -1;

void write_status() {
	Cam game, rendered;
	bool on;
	{
		std::lock_guard<std::mutex> lk(g_cam_mu);
		game = g_game; rendered = g_rendered; on = g_cam_on;
	}
	const char* names[] = {"run", "hold", "step"};
	std::string tmp = g_status + ".tmp";
	FILE* f = fopen(tmp.c_str(), "w");
	if (!f) return;
	fprintf(f, "seq=%ld\nstate=%s\nframe=%llu\nstep_left=%lld\nticks=%llu\ncam=%s\n", g_seq, names[g_mode.load()],
	        (unsigned long long)g_frame.load(), (long long)g_step_frames.load(), (unsigned long long)g_given.load(), on ? "on" : "off");
	fprintf(f, "game_pos=%.6f,%.6f,%.6f\ngame_rot=", game.pos[0], game.pos[1], game.pos[2]);
	for (int i = 0; i < 9; ++i) fprintf(f, "%s%.7f", i ? "," : "", game.rot[i]);
	fprintf(f, "\ngame_fov=%.5f\nrender_pos=%.6f,%.6f,%.6f\nrender_rot=", game.fov, rendered.pos[0], rendered.pos[1], rendered.pos[2]);
	for (int i = 0; i < 9; ++i) fprintf(f, "%s%.7f", i ? "," : "", rendered.rot[i]);
	fprintf(f, "\nrender_fov=%.5f\ncam_calls=%llu\ntick_calls=%llu\n", rendered.fov, (unsigned long long)g_cam_calls.load(),
	        (unsigned long long)g_ticks_called.load());
	for (int i = 0; i < 4; ++i)   // a timer's time in ticks (exact) and seconds, and the game's scale for it (0 while it pauses)
		if (g_timers[i])
			fprintf(f, "timer%d=%llu,%.9f\nscale%d=%.4f\n", i, (unsigned long long)g_timer_acc[i].load(), g_timer_acc[i].load() / 4294967296.0,
			        i, *(float*)((uint8_t*)g_timers[i] + 0x24));
	fprintf(f, "hooks=%s\n", g_hooks.c_str());
	fclose(f);
	MoveFileExA(tmp.c_str(), g_status.c_str(), MOVEFILE_REPLACE_EXISTING);
}

void handle(const char* line) {
	long seq = 0;
	char cmd[16] = {0};
	int used = 0;
	if (sscanf(line, "%ld %15s %n", &seq, cmd, &used) < 2 || seq == g_seq) return;
	const char* rest = line + used;
	g_seq = seq;
	if (!strcmp(cmd, "run")) {
		g_mode = RUN;
	} else if (!strcmp(cmd, "hold")) {
		g_step_frames = 0; g_step_ticks = 0; g_given = 0;
		g_mode = HOLD;
	} else if (!strcmp(cmd, "step")) {
		unsigned long long ticks = 0;
		long long frames = 1;
		char force[16] = {0};
		sscanf(rest, "%llu %lld %15s", &ticks, &frames, force);
		if (frames < 1) frames = 1;
		g_force = !strcmp(force, "force");
		g_given = 0;
		g_step_ticks = ticks;
		g_step_frames = frames;
		g_mode = STEP;
	} else if (!strcmp(cmd, "cam")) {
		Cam c{};
		if (!strncmp(rest, "off", 3)) {
			std::lock_guard<std::mutex> lk(g_cam_mu);
			g_cam_on = false;
		} else if (sscanf(rest, "%lf %lf %lf %f %f %f %f %f %f %f %f %f %f", &c.pos[0], &c.pos[1], &c.pos[2], &c.rot[0], &c.rot[1],
		                  &c.rot[2], &c.rot[3], &c.rot[4], &c.rot[5], &c.rot[6], &c.rot[7], &c.rot[8], &c.fov) == 13) {
			std::lock_guard<std::mutex> lk(g_cam_mu);
			g_cam = c;
			g_cam_on = true;
		} else {
			logf("bad cam command: %s", line);
		}
	} else {
		logf("unknown command: %s", line);
	}
	logf("command %ld %s", seq, cmd);
	write_status();
}

DWORD WINAPI control_thread(void*) {
	DeleteFileA(g_control.c_str());
	ULONGLONG last_status = 0;
	FILETIME last_write{};
	for (;;) {
		WIN32_FILE_ATTRIBUTE_DATA fa;
		if (GetFileAttributesExA(g_control.c_str(), GetFileExInfoStandard, &fa) &&
		    CompareFileTime(&fa.ftLastWriteTime, &last_write) != 0) {
			FILE* f = fopen(g_control.c_str(), "r");
			if (f) {
				char line[1024] = {0};
				if (fgets(line, sizeof line, f)) handle(line);
				fclose(f);
				last_write = fa.ftLastWriteTime;
			}
		}
		ULONGLONG now = GetTickCount64();
		if (now - last_status > 250) {
			write_status();
			last_status = now;
		}
		Sleep(2);
	}
}

std::string ini_get(const std::string& ini, const char* key) {
	char buf[1024] = {0};
	GetPrivateProfileStringA("capture", key, "", buf, sizeof buf, ini.c_str());
	return buf;
}

void install() {
	HMODULE exe = GetModuleHandleA(nullptr);
	g_base = (uint8_t*)exe;
	auto* nt = (IMAGE_NT_HEADERS*)(g_base + ((IMAGE_DOS_HEADER*)g_base)->e_lfanew);
	g_size = nt->OptionalHeader.SizeOfImage;
	std::string hooks;

	// the frame's clock update: mov [rsp+10],rbx; mov [rsp+18],rbp; mov [rsp+20],rsi; push rdi; push r12..r15
	uint8_t* frame = find("48 89 5C 24 10 48 89 6C 24 18 48 89 74 24 20 57 41 54 41 55 41 56 41 57 48 83 EC 30 48 8B FA 48 8B E9 48 8B 0D");
	// Clock::Advance: mov [rsp+8],rbx; push rdi; sub rsp,20; mov rbx,rcx; mov [rcx+8],r8; mov rcx,[rcx+28]; mov rdi,rdx
	uint8_t* adv = find("48 89 5C 24 08 57 48 83 EC 20 48 8B D9 4C 89 41 08 48 8B 49 28 48 8B FA");
	// view setup: vmulss xmm0,xmm0,[rsi+74]; vmovss [rsi+74],xmm0; | vmovss xmm0,[rsi+38]; vmovss xmm1,[rsi+44]; vmovss [rsp+60],xmm0
	uint8_t* view = find("C5 FA 59 46 74 C5 FA 11 46 74 C5 FA 10 46 38 C5 FA 10 4E 44 C5 FA 11 44 24 60");
	// Timer::Tick: inc [rcx+20]; vxorps xmm0; mov r10d,edx; vcvtsi2ss xmm0,r10; vmulss xmm0,[rcx+24]; vcvttss2si r8,xmm0
	uint8_t* tick = find("FF 41 20 C5 F8 57 C0 44 8B D2 C4 C1 FA 2A C2 C5 FA 59 41 24 C4 61 FA 2C C0");

	if (frame && adv && tick) {
		g_frame_fn = (FrameFn)hook_entry(frame, 15, (void*)frame_hook);
		g_advance = (AdvanceFn)hook_entry(adv, 17, (void*)advance_hook);
		g_tick = (TickFn)hook_entry(tick, 15, (void*)tick_hook);
		hooks += (g_frame_fn && g_advance && g_tick) ? "time" : "time-failed";
		logf("time hooks: frame rva %llx, advance rva %llx, tick rva %llx", (unsigned long long)(frame - g_base),
		     (unsigned long long)(adv - g_base), (unsigned long long)(tick - g_base));
	} else {
		hooks += "time-missing";
	}
	if (view) {
		bool ok = hook_mid_rsi(view + 10, 16, cam_hook);
		hooks += ok ? ",camera" : ",camera-failed";
		logf("camera hook at %p (rva %llx)", view + 10, (unsigned long long)(view + 10 - g_base));
	} else {
		hooks += ",camera-missing";
	}
	g_hooks = hooks;
	logf("hooks: %s", hooks.c_str());
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE mod, DWORD reason, LPVOID) {
	if (reason != DLL_PROCESS_ATTACH) return TRUE;
	DisableThreadLibraryCalls(mod);
	char path[MAX_PATH];
	GetModuleFileNameA(mod, path, MAX_PATH);
	std::string dir(path);
	dir = dir.substr(0, dir.find_last_of("\\/") + 1);
	std::string ini = dir + "capture_ds.ini";
	g_control = ini_get(ini, "Control");
	g_status = ini_get(ini, "Status");
	g_log = ini_get(ini, "Log");
	if (g_log.empty()) g_log = dir + "capture_ds.log";
	logf("capture_ds loaded (control %s)", g_control.c_str());
	install();
	if (!g_control.empty() && !g_status.empty()) CreateThread(nullptr, 0, control_thread, nullptr, 0, nullptr);
	return TRUE;
}
