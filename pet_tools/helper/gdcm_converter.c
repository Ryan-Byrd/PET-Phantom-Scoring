#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>

#include "gdcmReader.h"
#include "gdcmWriter.h"
#include "gdcmDataSet.h"
#include "gdcmFile.h"
#include "gdcmFilename.h"

/**
 * GDCM-Based Flat-Directory DICOM Normalization
 * 
 * Converts a flat directory of mixed files into standard Explicit VR Little Endian DICOM.
 * Detects DICOM based on file content, not extension.
 * 
 * Returns:
 *   0 on success
 *   1 on error
 */

typedef struct {
    int total_files;
    int dicom_files;
    int converted_files;
    int failed_files;
    int skipped_files;
} ConversionStats;

static ConversionStats stats = {0, 0, 0, 0, 0};

/**
 * Check if a file is readable
 */
static int file_exists(const char* path) {
    struct stat buffer;
    return (stat(path, &buffer) == 0);
}

/**
 * Ensure output directory exists
 */
static int ensure_dir_exists(const char* dir) {
    if (file_exists(dir)) {
        return 1;
    }
#ifdef _WIN32
    return _mkdir(dir) == 0;
#else
    return mkdir(dir, 0755) == 0;
#endif
}

/**
 * Get filename from full path
 */
static void get_filename(const char* full_path, char* filename, size_t max_len) {
    const char* last_slash = strrchr(full_path, '/');
    if (!last_slash) {
        last_slash = strrchr(full_path, '\\');
    }
    if (last_slash) {
        strncpy(filename, last_slash + 1, max_len - 1);
    } else {
        strncpy(filename, full_path, max_len - 1);
    }
    filename[max_len - 1] = '\0';
}

/**
 * Check if file has .dcm extension
 */
static int has_dcm_extension(const char* filename) {
    const char* ext = strrchr(filename, '.');
    return ext && strcasecmp(ext, ".dcm") == 0;
}

/**
 * Build output filename with .dcm extension if needed
 */
static void build_output_filename(const char* input_filename, char* output_filename, size_t max_len) {
    if (has_dcm_extension(input_filename)) {
        strncpy(output_filename, input_filename, max_len - 1);
    } else {
        snprintf(output_filename, max_len, "%s.dcm", input_filename);
    }
    output_filename[max_len - 1] = '\0';
}

/**
 * Attempt to read file as DICOM using GDCM
 * Returns 1 if valid DICOM with pixel data, 0 otherwise
 */
static int is_valid_dicom(const char* filepath) {
    gdcm::Reader reader;
    reader.SetFileName(filepath);
    
    if (!reader.Read()) {
        return 0;
    }
    
    const gdcm::DataSet& ds = reader.GetFile().GetDataSet();
    
    // Check for PixelData (indicates image DICOM)
    if (!ds.FindDataElement(gdcm::Tag(0x7fe0, 0x0010))) {
        return 0;
    }
    
    return 1;
}

/**
 * Convert a single DICOM file to Explicit VR Little Endian
 * Returns 1 on success, 0 on failure
 */
static int convert_single_file(const char* input_path, const char* output_path, int verbose) {
    gdcm::Reader reader;
    reader.SetFileName(input_path);
    
    if (!reader.Read()) {
        if (verbose) {
            fprintf(stderr, "  [SKIP] Not a valid DICOM: %s\n", input_path);
        }
        stats.skipped_files++;
        return 0;
    }
    
    gdcm::File& file = reader.GetFile();
    const gdcm::DataSet& ds = file.GetDataSet();
    
    // Check for pixel data
    if (!ds.FindDataElement(gdcm::Tag(0x7fe0, 0x0010))) {
        if (verbose) {
            fprintf(stderr, "  [SKIP] No pixel data: %s\n", input_path);
        }
        stats.skipped_files++;
        return 0;
    }
    
    stats.dicom_files++;
    
    // Set transfer syntax to Explicit VR Little Endian
    file.GetDataSet().SetTransferSyntax(gdcm::TransferSyntax::ExplicitVRLittleEndian);
    
    // Write the file
    gdcm::Writer writer;
    writer.SetFileName(output_path);
    writer.SetFile(file);
    
    if (!writer.Write()) {
        if (verbose) {
            fprintf(stderr, "  [FAIL] Could not write: %s\n", output_path);
        }
        stats.failed_files++;
        return 0;
    }
    
    if (verbose) {
        fprintf(stdout, "  [OK] Converted: %s\n", output_path);
    }
    stats.converted_files++;
    return 1;
}

/**
 * Main conversion function (C ABI compatible)
 * 
 * Parameters:
 *   input_dir:  Path to input directory containing mixed files
 *   output_dir: Path to output directory for converted DICOMs
 *   verbose:    1 for verbose output, 0 for silent
 * 
 * Returns:
 *   0 on success, 1 on error
 */
int convert_dicom_directory(
    const char* input_dir,
    const char* output_dir,
    int verbose)
{
    if (!input_dir || !output_dir) {
        fprintf(stderr, "ERROR: input_dir and output_dir must not be NULL\n");
        return 1;
    }
    
    // Ensure output directory exists
    if (!ensure_dir_exists(output_dir)) {
        if (verbose) {
            fprintf(stderr, "WARNING: Could not create output directory: %s\n", output_dir);
        }
        // Continue anyway; writer may create it
    }
    
    if (verbose) {
        fprintf(stdout, "Scanning input directory: %s\n", input_dir);
    }
    
    // Reset stats
    memset(&stats, 0, sizeof(ConversionStats));
    
    DIR* dir = opendir(input_dir);
    if (!dir) {
        fprintf(stderr, "ERROR: Cannot open input directory: %s\n", input_dir);
        return 1;
    }
    
    struct dirent* entry;
    while ((entry = readdir(dir)) != NULL) {
        // Skip directories and hidden files
        if (entry->d_type == DT_DIR) {
            continue;
        }
        if (entry->d_name[0] == '.') {
            continue;
        }
        
        stats.total_files++;
        
        // Build full input path
        char input_path[4096];
        snprintf(input_path, sizeof(input_path), "%s/%s", input_dir, entry->d_name);
        
        // Build output filename
        char output_filename[4096];
        build_output_filename(entry->d_name, output_filename, sizeof(output_filename));
        
        // Build full output path
        char output_path[4096];
        snprintf(output_path, sizeof(output_path), "%s/%s", output_dir, output_filename);
        
        // Attempt conversion
        convert_single_file(input_path, output_path, verbose);
    }
    
    closedir(dir);
    
    if (verbose) {
        fprintf(stdout, "\n=== Conversion Summary ===\n");
        fprintf(stdout, "Total files processed: %d\n", stats.total_files);
        fprintf(stdout, "Valid DICOM files:     %d\n", stats.dicom_files);
        fprintf(stdout, "Successfully converted: %d\n", stats.converted_files);
        fprintf(stdout, "Failed conversions:    %d\n", stats.failed_files);
        fprintf(stdout, "Skipped (invalid):     %d\n", stats.skipped_files);
    }
    
    return stats.failed_files > 0 ? 1 : 0;
}

/**
 * Return stats from last conversion
 * Callable from Python to get detailed results
 */
void get_conversion_stats(
    int* total,
    int* dicom,
    int* converted,
    int* failed,
    int* skipped)
{
    if (total) *total = stats.total_files;
    if (dicom) *dicom = stats.dicom_files;
    if (converted) *converted = stats.converted_files;
    if (failed) *failed = stats.failed_files;
    if (skipped) *skipped = stats.skipped_files;
}
