// capture_mod.addon64
// ReShade add-on: saves the current frame whenever the RedLua script publishes
// a request file, then writes an ack file the script waits for.
//
// Files in the output directory (ReShade.ini [CAPTURE_MOD] OutputDir):
//   request.txt   written by the script:  id=<id>  name=<relative image stem>
//                 optional: after=<n>  save the n-th frame presented after the request is seen
//                           (for a game whose script layer cannot count frames itself);
//                           op=frame   save nothing, only answer (the frame counter, the size)
//   <name>.bmp    written here
//   ack.txt       written here:  id, status (ok|error), message, file, width, height,
//                 frame (frames presented since the add-on loaded), time_ms (GetTickCount64)
//
// The frame is read in reshade_present, which runs after the ReShade overlay
// is drawn, so keep the overlay closed while capturing.

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <reshade.hpp>

#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

extern "C" __declspec(dllexport) const char *NAME = "Capture Mod";
extern "C" __declspec(dllexport) const char *DESCRIPTION =
	"Saves a frame when the RedLua capture script publishes a request file.";

namespace
{
	const char *const CONFIG_SECTION = "CAPTURE_MOD";
	const char *const CONFIG_KEY_DIR = "OutputDir";

	fs::path g_out_dir;
	bool g_ready = false;
	uint64_t g_frame = 0;                              // frames presented since the add-on loaded
	bool g_pending = false;                            // a request waiting for its frame (after=<n>)
	uint64_t g_pending_frame = 0;
	std::map<std::string, std::string> g_pending_request;

	void log_message(reshade::log::level level, const std::string &text)
	{
		reshade::log::message(level, ("[capture_mod] " + text).c_str());
	}

	fs::path default_output_dir()
	{
		wchar_t profile[MAX_PATH] = L"";
		if (GetEnvironmentVariableW(L"USERPROFILE", profile, MAX_PATH) == 0)
			return fs::path(L"C:\\RDR2Modding\\captures");
		return fs::path(profile) / L"Documents" / L"RDR2Modding" / L"captures";
	}

	// Reads the output directory from ReShade.ini, writing the default back on first run.
	void ensure_ready(reshade::api::effect_runtime *runtime)
	{
		if (g_ready)
			return;

		char value[1024] = "";
		size_t value_size = sizeof(value);
		if (reshade::get_config_value(runtime, CONFIG_SECTION, CONFIG_KEY_DIR, value, &value_size) && value[0] != '\0')
		{
			g_out_dir = fs::u8path(value);
		}
		else
		{
			g_out_dir = default_output_dir();
			reshade::set_config_value(runtime, CONFIG_SECTION, CONFIG_KEY_DIR, g_out_dir.u8string().c_str());
		}

		std::error_code ec;
		fs::create_directories(g_out_dir, ec);
		if (ec)
			log_message(reshade::log::level::error, "cannot create output directory " + g_out_dir.u8string() + ": " + ec.message());
		else
			log_message(reshade::log::level::info, "watching " + g_out_dir.u8string());

		g_ready = true;
	}

	bool read_key_values(const fs::path &path, std::map<std::string, std::string> &out)
	{
		std::ifstream file(path);
		if (!file)
			return false;

		std::string line;
		while (std::getline(file, line))
		{
			if (!line.empty() && line.back() == '\r')
				line.pop_back();
			const size_t eq = line.find('=');
			if (eq != std::string::npos)
				out[line.substr(0, eq)] = line.substr(eq + 1);
		}
		return true;
	}

	// Image names come from a file on disk, so only allow plain relative paths.
	bool is_safe_name(const std::string &name)
	{
		if (name.empty() || name.size() > 200 || name.front() == '/' || name.find("..") != std::string::npos)
			return false;
		for (const char c : name)
		{
			const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
				c == '_' || c == '-' || c == '/';
			if (!ok)
				return false;
		}
		return true;
	}

	// Byte offsets of red, green, blue in each 4-byte pixel that capture_screenshot returns.
	// Despite its documentation ("RGBA"), capture_screenshot returns the back buffer's own
	// layout (runtime.hpp passes _back_buffer_format as the output format): BGRA for
	// RDR2's VK_FORMAT_B8G8R8A8_UNORM swap chain. Measured 2026-11-20: assuming RGBA there
	// swapped red and blue in every saved frame.
	struct channel_order { int r, g, b; };

	bool channel_order_of(reshade::api::effect_runtime *runtime, channel_order &order, std::string &format_name)
	{
		using reshade::api::format;
		const reshade::api::resource back_buffer = runtime->get_current_back_buffer();
		const format f = reshade::api::format_to_default_typed(runtime->get_device()->get_resource_desc(back_buffer).texture.format, 0);
		switch (f)
		{
		case format::r8g8b8a8_unorm:
		case format::r8g8b8x8_unorm:
			order = { 0, 1, 2 };
			format_name = "rgba8";
			return true;
		case format::b8g8r8a8_unorm:
		case format::b8g8r8x8_unorm:
			order = { 2, 1, 0 };
			format_name = "bgra8";
			return true;
		default:
			format_name = "format " + std::to_string(static_cast<uint32_t>(f));
			return false; // 10-bit and float back buffers are packed differently; not handled
		}
	}

	// Writes 8-bit 4-channel pixels (top row first, channel order as given) as a 24-bit BMP.
	bool write_bmp(const fs::path &path, const uint8_t *pixels, const channel_order &order, uint32_t width, uint32_t height)
	{
		const uint32_t row_size = (width * 3 + 3) & ~3u;
		const uint32_t data_size = row_size * height;

		BITMAPFILEHEADER file_header = {};
		file_header.bfType = 0x4D42; // "BM"
		file_header.bfOffBits = sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER);
		file_header.bfSize = file_header.bfOffBits + data_size;

		BITMAPINFOHEADER info_header = {};
		info_header.biSize = sizeof(BITMAPINFOHEADER);
		info_header.biWidth = static_cast<LONG>(width);
		info_header.biHeight = static_cast<LONG>(height); // positive: rows stored bottom-up
		info_header.biPlanes = 1;
		info_header.biBitCount = 24;
		info_header.biCompression = BI_RGB;
		info_header.biSizeImage = data_size;

		std::ofstream file(path, std::ios::binary | std::ios::trunc);
		if (!file)
			return false;

		file.write(reinterpret_cast<const char *>(&file_header), sizeof(file_header));
		file.write(reinterpret_cast<const char *>(&info_header), sizeof(info_header));

		std::vector<uint8_t> row(row_size, 0);
		for (uint32_t y = 0; y < height; ++y)
		{
			const uint8_t *src = pixels + static_cast<size_t>(height - 1 - y) * width * 4;
			for (uint32_t x = 0; x < width; ++x)
			{
				// BMP stores blue, green, red.
				row[x * 3 + 0] = src[x * 4 + order.b];
				row[x * 3 + 1] = src[x * 4 + order.g];
				row[x * 3 + 2] = src[x * 4 + order.r];
			}
			file.write(reinterpret_cast<const char *>(row.data()), row_size);
		}
		return file.good();
	}

	// Writes ack.txt through a temp file so the script never reads a partial ack.
	void write_ack(const std::string &id, bool ok, const std::string &message, const std::string &file, uint32_t width, uint32_t height)
	{
		const fs::path tmp_path = g_out_dir / L"ack.tmp";
		const fs::path ack_path = g_out_dir / L"ack.txt";
		{
			std::ofstream ack(tmp_path, std::ios::trunc);
			ack << "id=" << id << '\n'
				<< "status=" << (ok ? "ok" : "error") << '\n'
				<< "message=" << message << '\n'
				<< "file=" << file << '\n'
				<< "width=" << width << '\n'
				<< "height=" << height << '\n'
				<< "frame=" << g_frame << '\n'
				<< "time_ms=" << GetTickCount64() << '\n';
		}

		// The script may have ack.txt open for reading; retry briefly.
		for (int attempt = 0; attempt < 100; ++attempt)
		{
			if (MoveFileExW(tmp_path.c_str(), ack_path.c_str(), MOVEFILE_REPLACE_EXISTING))
				return;
			Sleep(2);
		}
		log_message(reshade::log::level::error, "could not replace ack.txt");
	}

	// Saves the current frame as the request asks and answers it.
	void save_frame(reshade::api::effect_runtime *runtime, std::map<std::string, std::string> &request)
	{
		std::error_code ec;
		const std::string id = request["id"];
		const std::string name = request["name"];
		if (!is_safe_name(name))
		{
			log_message(reshade::log::level::warning, "rejected request with invalid name");
			write_ack(id, false, "invalid image name", "", 0, 0);
			return;
		}

		const fs::path image_path = g_out_dir / fs::u8path(name + ".bmp");
		fs::create_directories(image_path.parent_path(), ec);

		uint32_t width = 0, height = 0;
		runtime->get_screenshot_width_and_height(&width, &height);
		if (width == 0 || height == 0)
		{
			write_ack(id, false, "back buffer has no size", "", 0, 0);
			return;
		}

		channel_order order;
		std::string format_name;
		if (!channel_order_of(runtime, order, format_name))
		{
			log_message(reshade::log::level::error, "unsupported back buffer " + format_name);
			write_ack(id, false, "unsupported back buffer " + format_name, "", width, height);
			return;
		}

		std::vector<uint8_t> pixels(static_cast<size_t>(width) * height * 4);
		if (!runtime->capture_screenshot(pixels.data()))
		{
			log_message(reshade::log::level::error, "capture_screenshot failed for " + name);
			write_ack(id, false, "capture_screenshot failed", "", width, height);
			return;
		}

		if (!write_bmp(image_path, pixels.data(), order, width, height))
		{
			log_message(reshade::log::level::error, "could not write " + image_path.u8string());
			write_ack(id, false, "could not write image file", "", width, height);
			return;
		}

		write_ack(id, true, "", name + ".bmp", width, height);
	}

	void handle_request(reshade::api::effect_runtime *runtime, const fs::path &request_path)
	{
		std::map<std::string, std::string> request;
		if (!read_key_values(request_path, request))
			return; // still being written or locked; try again next frame

		std::error_code ec;
		fs::remove(request_path, ec);

		if (request["op"] == "frame")
		{
			// no picture: the frame counter and the size, for timing and for counting frames
			uint32_t width = 0, height = 0;
			runtime->get_screenshot_width_and_height(&width, &height);
			write_ack(request["id"], true, "", "", width, height);
			return;
		}

		const int after = std::atoi(request["after"].c_str());
		if (after > 0)
		{
			g_pending = true;
			g_pending_frame = g_frame + static_cast<uint64_t>(after);
			g_pending_request = request;
			return;
		}
		save_frame(runtime, request);
	}

	void on_reshade_present(reshade::api::effect_runtime *runtime)
	{
		++g_frame;
		ensure_ready(runtime);

		if (g_pending)
		{
			if (g_frame < g_pending_frame)
				return;
			g_pending = false;
			save_frame(runtime, g_pending_request);
			return;
		}

		const fs::path request_path = g_out_dir / L"request.txt";
		if (GetFileAttributesW(request_path.c_str()) == INVALID_FILE_ATTRIBUTES)
			return;

		handle_request(runtime, request_path);
	}
}

BOOL APIENTRY DllMain(HMODULE addon_module, DWORD reason, LPVOID)
{
	switch (reason)
	{
	case DLL_PROCESS_ATTACH:
		if (!reshade::register_addon(addon_module))
			return FALSE;
		reshade::register_event<reshade::addon_event::reshade_present>(on_reshade_present);
		break;
	case DLL_PROCESS_DETACH:
		reshade::unregister_event<reshade::addon_event::reshade_present>(on_reshade_present);
		reshade::unregister_addon(addon_module);
		break;
	}
	return TRUE;
}
