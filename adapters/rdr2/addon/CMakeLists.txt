cmake_minimum_required(VERSION 3.20)
project(capture_mod LANGUAGES CXX)

# ReShade's add-on API is header-only. scripts/fetch_deps.ps1 clones it here.
set(RESHADE_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../deps/reshade/include"
	CACHE PATH "Directory containing reshade.hpp")

if(NOT EXISTS "${RESHADE_INCLUDE_DIR}/reshade.hpp")
	message(FATAL_ERROR
		"reshade.hpp not found in ${RESHADE_INCLUDE_DIR}. "
		"Run scripts/fetch_deps.ps1 or set RESHADE_INCLUDE_DIR.")
endif()

if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
	message(FATAL_ERROR "RDR2 is 64-bit; configure with -A x64.")
endif()

add_library(capture_mod SHARED src/capture_addon.cpp)

# C++17 exactly: the code relies on fs::path::u8string() returning std::string.
set_target_properties(capture_mod PROPERTIES
	CXX_STANDARD 17
	CXX_STANDARD_REQUIRED ON
	CXX_EXTENSIONS OFF
	PREFIX ""
	OUTPUT_NAME "capture_mod"
	SUFFIX ".addon64")

target_include_directories(capture_mod PRIVATE "${RESHADE_INCLUDE_DIR}")
target_compile_definitions(capture_mod PRIVATE _CRT_SECURE_NO_WARNINGS)

if(MSVC)
	target_compile_options(capture_mod PRIVATE /W4 /utf-8)
endif()
