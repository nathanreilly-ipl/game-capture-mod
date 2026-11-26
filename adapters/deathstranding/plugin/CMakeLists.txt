cmake_minimum_required(VERSION 3.20)
project(capture_ds LANGUAGES CXX)

if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
	message(FATAL_ERROR "configure with -A x64")
endif()

add_library(capture_ds SHARED src/capture_ds.cpp)

set_target_properties(capture_ds PROPERTIES
	CXX_STANDARD 17
	CXX_STANDARD_REQUIRED ON
	CXX_EXTENSIONS OFF
	PREFIX ""
	OUTPUT_NAME "capture_ds"
	SUFFIX ".asi"
	# the static C runtime: nothing to find in the game folder
	MSVC_RUNTIME_LIBRARY "MultiThreaded")

target_compile_definitions(capture_ds PRIVATE _CRT_SECURE_NO_WARNINGS)

if(MSVC)
	target_compile_options(capture_ds PRIVATE /W4 /utf-8)
endif()
