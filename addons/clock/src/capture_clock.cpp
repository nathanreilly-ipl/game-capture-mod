// capture_clock.asi: holds the clock a game reads, so what animates on real time (video screens,
// holograms, blinking lights) stands still while a held world is captured. Game-agnostic.
//
// An ASI loader loads it into the game. It rewrites the import tables of the modules listed in
// capture_clock.ini (the game's exe, its video player...), so their calls to
// QueryPerformanceCounter, GetTickCount, GetTickCount64 and timeGetTime (and GetProcAddress for
// those) come here. Every other module (the graphics driver, DLSS, ReShade, script hosts) still
// reads the real clock.
//
// Each hooked (module, function) pair follows its own virtual clock:
//     virtual = base_virtual + (real - base_real) * rate
// rate 1 while running, `scale` while held (0: stands still). A change of rate re-bases the
// clock where it is, so it never jumps; after a hold the game's clocks run behind real time by
// as long as they were held. A game may not take a clock that stands still: Cyberpunk 2077
// shuts down at once, below about a microsecond per frame.
//
// Control: a file the capture scripts write, read every 10 ms:
//     <seq> hold <scale> [mask]   hold the clocks (mask, hex: bit 8*module + function; all by default)
//     <seq> run                   let them run
// After each command, and every second, the status file says what is in force:
//     seq=, state=hold|run, scale=, mask=, lag_ms=, module<i>=, calls<i>=, held<i>=
// A control file there when the game starts is removed unread (it may be left from a session
// that crashed holding), so the clock always starts running.
//
// capture_clock.ini, next to the ASI:
//     [clock]
//     Control=<absolute path of the control file>
//     Status=<absolute path of the status file>
//     Log=<absolute path of the log>        (optional; capture_clock.log next to the ASI by default)
//     Modules=Game.exe,bink2w64.dll         (up to four)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

namespace {

constexpr int MAX_MODULES = 4;
enum Fn { QPC, GTC, GTC64, TGT, GPA, FN_COUNT };
constexpr int CLOCKS = GPA;  // the functions that read a clock
const char* const FN_NAMES[FN_COUNT] = {"QueryPerformanceCounter", "GetTickCount", "GetTickCount64", "timeGetTime",
                                        "GetProcAddress"};
const char* const FN_SHORT[FN_COUNT] = {"qpc", "gtc", "gtc64", "tgt", "gpa"};

struct Slot {
	int64_t base_real;
	int64_t base_virtual;
	double rate;
};

// Never changed once published: a command publishes a new one (a few hundred per session, never freed).
struct State {
	Slot slot[MAX_MODULES][CLOCKS];
	bool hold;
	double scale;
	uint32_t mask;
	unsigned seq;
};

struct Module {
	wchar_t name[MAX_PATH];
	bool patched;
	void* orig[FN_COUNT];
	std::atomic<uint64_t> calls[FN_COUNT];
	std::atomic<uint64_t> held[FN_COUNT];
};

std::atomic<const State*> g_state{nullptr};
Module g_mod[MAX_MODULES];
int g_mod_count = 0;
int64_t g_freq = 1;
BOOL(WINAPI* g_real_qpc)(LARGE_INTEGER*) = nullptr;
wchar_t g_control[MAX_PATH], g_status[MAX_PATH], g_log[MAX_PATH];

void logf(const char* fmt, ...) {
	FILE* f = _wfopen(g_log, L"a");
	if (!f) return;
	SYSTEMTIME t;
	GetLocalTime(&t);
	fprintf(f, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
	va_list a;
	va_start(a, fmt);
	vfprintf(f, fmt, a);
	va_end(a);
	fputc('\n', f);
	fclose(f);
}

int64_t real_ticks() {
	LARGE_INTEGER t;
	g_real_qpc(&t);
	return t.QuadPart;
}

int64_t slot_virtual(const Slot& s, int64_t real) {
	if (s.rate == 1.0) return s.base_virtual + (real - s.base_real);
	return s.base_virtual + static_cast<int64_t>(static_cast<double>(real - s.base_real) * s.rate);
}

int64_t to_virtual(int64_t real, int m, int f) {
	const State* s = g_state.load(std::memory_order_acquire);
	const Slot& sl = s->slot[m][f];
	if (sl.rate != 1.0) g_mod[m].held[f].fetch_add(1, std::memory_order_relaxed);
	return slot_virtual(sl, real);
}

// how far a millisecond clock of this module lags real time
template <int M, int F> int64_t lag_ms() {
	const int64_t r = real_ticks();
	return (r - to_virtual(r, M, F)) * 1000 / g_freq;
}

template <int M> BOOL WINAPI hook_qpc(LARGE_INTEGER* out) {
	g_mod[M].calls[QPC].fetch_add(1, std::memory_order_relaxed);
	if (!out) return g_real_qpc(out);
	LARGE_INTEGER t;
	const BOOL ok = g_real_qpc(&t);
	out->QuadPart = to_virtual(t.QuadPart, M, QPC);
	return ok;
}

template <int M> DWORD WINAPI hook_gtc() {
	g_mod[M].calls[GTC].fetch_add(1, std::memory_order_relaxed);
	return reinterpret_cast<DWORD(WINAPI*)()>(g_mod[M].orig[GTC])() - static_cast<DWORD>(lag_ms<M, GTC>());
}

template <int M> ULONGLONG WINAPI hook_gtc64() {
	g_mod[M].calls[GTC64].fetch_add(1, std::memory_order_relaxed);
	return reinterpret_cast<ULONGLONG(WINAPI*)()>(g_mod[M].orig[GTC64])() - static_cast<ULONGLONG>(lag_ms<M, GTC64>());
}

template <int M> DWORD WINAPI hook_tgt() {
	g_mod[M].calls[TGT].fetch_add(1, std::memory_order_relaxed);
	return reinterpret_cast<DWORD(WINAPI*)()>(g_mod[M].orig[TGT])() - static_cast<DWORD>(lag_ms<M, TGT>());
}

template <int M> FARPROC WINAPI hook_gpa(HMODULE h, LPCSTR name);

template <int M> struct Hooks {
	static inline void* const table[FN_COUNT] = {reinterpret_cast<void*>(&hook_qpc<M>), reinterpret_cast<void*>(&hook_gtc<M>),
	                                          reinterpret_cast<void*>(&hook_gtc64<M>), reinterpret_cast<void*>(&hook_tgt<M>),
	                                          reinterpret_cast<void*>(&hook_gpa<M>)};
};

void* hook_for(int m, int f) {
	switch (m) {
	case 0: return Hooks<0>::table[f];
	case 1: return Hooks<1>::table[f];
	case 2: return Hooks<2>::table[f];
	default: return Hooks<3>::table[f];
	}
}

// A clock looked up by name from a hooked module gets the hook too.
template <int M> FARPROC WINAPI hook_gpa(HMODULE h, LPCSTR name) {
	const FARPROC p = reinterpret_cast<FARPROC(WINAPI*)(HMODULE, LPCSTR)>(g_mod[M].orig[GPA])(h, name);
	if (!p || reinterpret_cast<uintptr_t>(name) <= 0xFFFF) return p;
	for (int f = 0; f < CLOCKS; ++f) {
		if (strcmp(name, FN_NAMES[f]) != 0) continue;
		if (!g_mod[M].orig[f]) g_mod[M].orig[f] = reinterpret_cast<void*>(p);
		g_mod[M].calls[GPA].fetch_add(1, std::memory_order_relaxed);
		return reinterpret_cast<FARPROC>(hook_for(M, f));
	}
	return p;
}

bool patch_module(int m) {
	Module& mod = g_mod[m];
	auto* base = reinterpret_cast<BYTE*>(GetModuleHandleW(mod.name));
	if (!base) return false;
	auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + reinterpret_cast<IMAGE_DOS_HEADER*>(base)->e_lfanew);
	const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
	std::string done;
	if (dir.VirtualAddress) {
		for (auto* d = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress); d->Name; ++d) {
			if (!d->OriginalFirstThunk) continue;
			auto* names = reinterpret_cast<IMAGE_THUNK_DATA*>(base + d->OriginalFirstThunk);
			auto* iat = reinterpret_cast<IMAGE_THUNK_DATA*>(base + d->FirstThunk);
			for (; names->u1.AddressOfData; ++names, ++iat) {
				if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
				const char* fn = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData)->Name;
				for (int f = 0; f < FN_COUNT; ++f) {
					if (strcmp(fn, FN_NAMES[f]) != 0) continue;
					void* hook = hook_for(m, f);
					void* cur = reinterpret_cast<void*>(iat->u1.Function);
					if (cur == hook) break;
					mod.orig[f] = cur;  // before the hook can be called
					DWORD old;
					if (VirtualProtect(&iat->u1.Function, sizeof(void*), PAGE_READWRITE, &old)) {
						iat->u1.Function = reinterpret_cast<ULONGLONG>(hook);
						VirtualProtect(&iat->u1.Function, sizeof(void*), old, &old);
						done += (done.empty() ? "" : ",");
						done += FN_NAMES[f];
					}
					break;
				}
			}
		}
	}
	mod.patched = true;
	logf("%ls: hooked %s", mod.name, done.empty() ? "nothing (it imports no clock)" : done.c_str());
	return true;
}

std::string status_text() {
	const State* s = g_state.load(std::memory_order_acquire);
	char buf[512];
	std::string t;
	const int64_t r = real_ticks();
	snprintf(buf, sizeof buf, "seq=%u\nstate=%s\nscale=%.9g\nmask=%08x\nlag_ms=%.3f\n", s->seq, s->hold ? "hold" : "run",
	         s->scale, s->mask, g_mod_count ? static_cast<double>(r - slot_virtual(s->slot[0][QPC], r)) * 1000.0 / g_freq : 0.0);
	t += buf;
	for (int m = 0; m < g_mod_count; ++m) {
		snprintf(buf, sizeof buf, "module%d=%ls %s\n", m, g_mod[m].name, g_mod[m].patched ? "hooked" : "not loaded");
		t += buf;
		for (const char* key : {"calls", "held"}) {
			snprintf(buf, sizeof buf, "%s%d=", key, m);
			t += buf;
			for (int f = 0; f < FN_COUNT; ++f) {
				const auto& c = key[0] == 'c' ? g_mod[m].calls[f] : g_mod[m].held[f];
				snprintf(buf, sizeof buf, "%s%s:%llu", f ? " " : "", FN_SHORT[f], static_cast<unsigned long long>(c.load()));
				t += buf;
			}
			t += "\n";
		}
	}
	return t;
}

void write_status() {
	if (!g_status[0]) return;
	const std::string text = status_text();
	std::wstring tmp = std::wstring(g_status) + L".tmp";
	FILE* f = _wfopen(tmp.c_str(), L"wb");
	if (!f) return;
	fwrite(text.data(), 1, text.size(), f);
	fclose(f);
	MoveFileExW(tmp.c_str(), g_status, MOVEFILE_REPLACE_EXISTING);
}

bool read_control(std::string& out) {
	FILE* f = _wfopen(g_control, L"rb");
	if (!f) return false;
	char buf[256];
	const size_t n = fread(buf, 1, sizeof buf - 1, f);
	fclose(f);
	out.assign(buf, n);
	return true;
}

void apply(const std::string& cmd) {
	unsigned seq = 0, mask = 0xFFFFFFFFu;
	char verb[16] = {};
	double scale = 0.0;
	const int n = sscanf(cmd.c_str(), "%u %15s %lf %x", &seq, verb, &scale, &mask);
	const bool hold = n >= 2 && strcmp(verb, "hold") == 0;
	if (n < 2 || (!hold && strcmp(verb, "run") != 0)) {
		logf("ignored command: %s", cmd.c_str());
		return;
	}
	if (scale < 0.0) scale = 0.0;
	const State* old = g_state.load(std::memory_order_acquire);
	auto* s = new State(*old);
	const int64_t r = real_ticks();
	for (int m = 0; m < MAX_MODULES; ++m) {
		for (int f = 0; f < CLOCKS; ++f) {
			const double rate = hold && (mask >> (m * 8 + f) & 1) ? scale : 1.0;
			Slot& sl = s->slot[m][f];
			sl.base_virtual = slot_virtual(old->slot[m][f], r);
			sl.base_real = r;
			sl.rate = rate;
		}
	}
	s->hold = hold;
	s->scale = hold ? scale : 1.0;
	s->mask = hold ? mask : 0;
	s->seq = seq;
	g_state.store(s, std::memory_order_release);
	logf("%u %s (scale %.9g, mask %08x)", seq, hold ? "hold" : "run", s->scale, s->mask);
	write_status();
}

DWORD WINAPI control_thread(void*) {
	std::string seen, cmd;
	DeleteFileW(g_control);  // left from before this start (perhaps a session that crashed holding)
	write_status();
	DWORD last_status = GetTickCount();
	for (;;) {
		for (int m = 0; m < g_mod_count; ++m) {
			if (!g_mod[m].patched) patch_module(m);  // a module loaded after the game started
		}
		if (read_control(cmd) && cmd != seen && !cmd.empty() && cmd.back() == '\n') {
			seen = cmd;
			apply(cmd);
		}
		if (GetTickCount() - last_status >= 1000) {
			write_status();
			last_status = GetTickCount();
		}
		Sleep(10);
	}
}

std::wstring ini_string(const wchar_t* ini, const wchar_t* key) {
	wchar_t buf[1024] = {};
	GetPrivateProfileStringW(L"clock", key, L"", buf, 1024, ini);
	return buf;
}

void init(HMODULE self) {
	wchar_t dir[MAX_PATH];
	GetModuleFileNameW(self, dir, MAX_PATH);
	*wcsrchr(dir, L'\\') = 0;
	const std::wstring ini = std::wstring(dir) + L"\\capture_clock.ini";
	wcsncpy(g_control, ini_string(ini.c_str(), L"Control").c_str(), MAX_PATH - 1);
	wcsncpy(g_status, ini_string(ini.c_str(), L"Status").c_str(), MAX_PATH - 1);
	std::wstring log = ini_string(ini.c_str(), L"Log");
	wcsncpy(g_log, (log.empty() ? std::wstring(dir) + L"\\capture_clock.log" : log).c_str(), MAX_PATH - 1);

	g_real_qpc = reinterpret_cast<BOOL(WINAPI*)(LARGE_INTEGER*)>(
		GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "QueryPerformanceCounter"));
	LARGE_INTEGER fq;
	QueryPerformanceFrequency(&fq);
	g_freq = fq.QuadPart ? fq.QuadPart : 1;

	auto* s = new State{};
	for (auto& row : s->slot)
		for (auto& sl : row) sl = {0, 0, 1.0};
	s->scale = 1.0;
	g_state.store(s, std::memory_order_release);

	const std::wstring mods = ini_string(ini.c_str(), L"Modules");
	size_t start = 0;
	while (start < mods.size() && g_mod_count < MAX_MODULES) {
		size_t end = mods.find(L',', start);
		if (end == std::wstring::npos) end = mods.size();
		std::wstring name = mods.substr(start, end - start);
		while (!name.empty() && name.front() == L' ') name.erase(0, 1);
		while (!name.empty() && name.back() == L' ') name.pop_back();
		if (!name.empty()) wcsncpy(g_mod[g_mod_count++].name, name.c_str(), MAX_PATH - 1);
		start = end + 1;
	}
	logf("capture_clock loaded; %d modules; control %ls", g_mod_count, g_control);
	if (!g_control[0] || !g_mod_count) {
		logf("capture_clock.ini has no Control or no Modules: doing nothing");
		return;
	}
	for (int m = 0; m < g_mod_count; ++m) patch_module(m);
	CloseHandle(CreateThread(nullptr, 0, control_thread, nullptr, 0, nullptr));
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE self, DWORD reason, LPVOID) {
	if (reason == DLL_PROCESS_ATTACH) {
		DisableThreadLibraryCalls(self);
		init(self);
	}
	return TRUE;
}
