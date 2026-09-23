cmake_minimum_required(VERSION 3.10)
project(gdcm_converter)

set(CMAKE_CXX_STANDARD 11)

# Find GDCM
find_package(GDCM REQUIRED)

# Create shared library
add_library(gdcm_converter SHARED gdcm_converter.c)

# Link against GDCM
target_link_libraries(gdcm_converter PRIVATE gdcmCommon gdcmDICT gdcmDSED gdcmIO)

# Include GDCM headers
target_include_directories(gdcm_converter PRIVATE ${GDCM_INCLUDE_DIRS})

# Set output directory
set_target_properties(gdcm_converter PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

# Windows-specific settings
if(WIN32)
    set_target_properties(gdcm_converter PROPERTIES
        PREFIX ""
        SUFFIX ".dll"
    )
endif()

# Expose functions for ctypes
if(MSVC)
    set_target_properties(gdcm_converter PROPERTIES
        WINDOWS_EXPORT_ALL_SYMBOLS ON
    )
else()
    target_compile_options(gdcm_converter PRIVATE -fvisibility=default)
endif()
