// capture_mod.addon64
// ReShade add-on: saves the current frame whenever the RedLua script publishes
// a request file, then writes an ack file the script waits for.
//
// Files in the output directory (ReShade.ini [CAPTURE_MOD] OutputDir):
//   request.txt   written by the script:  id=<id>  name=<relative image stem>
//   <name>.bmp    written here
//   ack.txt       written here:  id, status (ok|error), message, file, width, height
//
// The frame is read in reshade_present, which runs after the ReShade overlay
// is drawn, so keep the overlay closed while capturing.

#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <reshade.hpp>

#include <cstdint>
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

	// Writes RGBA8 pixels (top row first) as a 24-bit BMP.
	bool write_bmp(const fs::path &path, const uint8_t *rgba, uint32_t width, uint32_t height)
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
			const uint8_t *src = rgba + static_cast<size_t>(height - 1 - y) * width * 4;
			for (uint32_t x = 0; x < width; ++x)
			{
				row[x * 3 + 0] = src[x * 4 + 2]; // B
				row[x * 3 + 1] = src[x * 4 + 1]; // G
				row[x * 3 + 2] = src[x * 4 + 0]; // R
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
				<< "height=" << height << '\n';
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

	void handle_request(reshade::api::effect_runtime *runtime, const fs::path &request_path)
	{
		std::map<std::string, std::string> request;
		if (!read_key_values(request_path, request))
			return; // still being written or locked; try again next frame

		std::error_code ec;
		fs::remove(request_path, ec);

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

		std::vector<uint8_t> pixels(static_cast<size_t>(width) * height * 4);
		if (!runtime->capture_screenshot(pixels.data()))
		{
			log_message(reshade::log::level::error, "capture_screenshot failed for " + name);
			write_ack(id, false, "capture_screenshot failed", "", width, height);
			return;
		}

		if (!write_bmp(image_path, pixels.data(), width, height))
		{
			log_message(reshade::log::level::error, "could not write " + image_path.u8string());
			write_ack(id, false, "could not write image file", "", width, height);
			return;
		}

		write_ack(id, true, "", name + ".bmp", width, height);
	}

	void on_reshade_present(reshade::api::effect_runtime *runtime)
	{
		ensure_ready(runtime);

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
